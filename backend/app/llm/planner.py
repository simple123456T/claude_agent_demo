import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.llm.client import ChatClient
from app.semantic.compiler import QueryValidationError
from app.semantic.models import QuerySpec
from app.semantic.registry import DatasetDefinition

MAX_VALUES_PER_DIMENSION = 30


class PlanFailed(Exception):
    """The model could not produce a valid query, even after one repair attempt."""


class PlannerOutput(BaseModel):
    """The wrapper tolerates stray keys; QuerySpec inside it stays strict."""

    status: Literal["ok", "clarify", "unsupported"]
    query: QuerySpec | None = None
    message: str | None = None
    assumptions: list[str] = []


@dataclass(frozen=True)
class PlanResult:
    status: Literal["ok", "clarify", "unsupported"]
    query: QuerySpec | None = None
    message: str | None = None
    assumptions: list[str] = field(default_factory=list)


def build_system_prompt(
    dataset: DatasetDefinition,
    metrics: list[str],
    dimensions: list[str],
    dimension_values: dict[str, list[str]],
    today: date,
) -> str:
    """Describe only what the caller may see; the model cannot name anything outside this."""

    lines = [
        "你是企业数据问数系统中的「查询规划器」。把用户的中文问题转换成一个结构化查询（JSON）。",
        "你不能编写 SQL，不能直接回答数字，也不能使用下面清单之外的名称。",
        "",
        f"# 数据集：{dataset.name}（{dataset.label or dataset.name}）",
    ]
    if dataset.description:
        lines.append(dataset.description)

    lines += ["", "## 指标（metrics，只能使用 name）"]
    for name in metrics:
        metric = dataset.metrics[name]
        extra = [f"汇总方式 {metric.aggregation.value}"]
        if metric.unit:
            extra.append(f"单位 {metric.unit}")
        if metric.description:
            extra.append(metric.description)
        if dataset.synonyms.get(name):
            extra.append("同义词：" + "、".join(dataset.synonyms[name]))
        lines.append(f"- {name}：{dataset.metric_label(name)}（{'；'.join(extra)}）")

    lines += ["", "## 维度（dimensions / filters 的 field，只能使用 name）"]
    for name in dimensions:
        extra = []
        if name in dataset.time_dimensions:
            extra.append("时间维度，值的格式为 YYYY-MM")
        if dataset.synonyms.get(name):
            extra.append("同义词：" + "、".join(dataset.synonyms[name]))
        values = dimension_values.get(name)
        if values:
            extra.append("可选值：" + "、".join(values))
        suffix = f"（{'；'.join(extra)}）" if extra else ""
        lines.append(f"- {name}：{dataset.dimension_label(name)}{suffix}")

    first_metric = metrics[0] if metrics else "metric"
    first_dimension = dimensions[0] if dimensions else "dimension"
    time_dimension = next((d for d in dimensions if d in dataset.time_dimensions), None)
    lines += [
        "",
        "# 规则",
        "1. 只输出一个 JSON 对象，不要输出解释、Markdown 或代码块。",
        "2. 过滤值必须来自「可选值」；用户说法与可选值不完全相同时，选语义最接近的并写入 assumptions。",
        f"3. 今天是 {today.isoformat()}（当前月份 {today:%Y-%m}）。"
        "「今年」「去年」「最近 N 个月」等相对时间要换算成具体月份范围，并写入 assumptions。",
        "4. 问趋势、每月、按月 → 加时间维度并按它升序；问排名、最高、前 N → 按指标降序，limit 设为 N；"
        "没有特别要求时 limit 取 50。",
        "5. 过滤操作符只能是：eq ne gt gte lt lte in not_in is_null not_null；"
        "in / not_in 的 values 是列表，eq 等比较类的 values 恰好一个值，is_null / not_null 不带 values。",
        "6. 同比、环比、占比、预测、跨数据集关联等当前不支持的问题，返回 unsupported 并说明原因。",
        "7. 问题缺少关键信息、无法合理假设时，返回 clarify 并说明需要用户补充什么。",
        "",
        "# 输出格式",
        '成功：{"status":"ok","assumptions":["..."],"query":{"dataset":"'
        + dataset.name
        + '","metrics":[{"name":"'
        + first_metric
        + '"}],"dimensions":[{"name":"'
        + first_dimension
        + '"}],"filters":[],"order_by":[{"field":"'
        + first_metric
        + '","direction":"desc"}],"limit":50}}',
        '需澄清：{"status":"clarify","message":"..."}',
        '不支持：{"status":"unsupported","message":"..."}',
    ]
    if time_dimension:
        lines.append(
            f'时间过滤示例：{{"field":"{time_dimension}","operator":"gte","values":["{today.year}-01"]}}'
        )
    return "\n".join(lines)


def parse_planner_output(text: str) -> PlannerOutput:
    """Accept a bare JSON object, tolerating code fences or leading chatter."""

    start = text.find("{")
    if start == -1:
        raise ValueError("输出里没有 JSON 对象")
    try:
        payload, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 无法解析：{exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("输出必须是 JSON 对象")
    return PlannerOutput.model_validate(payload)


def describe_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        # Report the location and rule only - never echo the offending input back.
        return "；".join(
            f"{'.'.join(str(part) for part in err['loc'])}：{err['msg']}"
            for err in exc.errors(include_input=False, include_url=False)[:6]
        )
    return str(exc)[:300]


class Planner:
    def __init__(self, client: ChatClient, today: Callable[[], date] = date.today) -> None:
        self._client = client
        self._today = today

    def plan(
        self,
        question: str,
        dataset: DatasetDefinition,
        *,
        metrics: list[str],
        dimensions: list[str],
        dimension_values: dict[str, list[str]],
        validate: Callable[[QuerySpec], None],
    ) -> PlanResult:
        """Ask the model once, and once more with the concrete error if its answer is invalid."""

        messages = [
            {
                "role": "system",
                "content": build_system_prompt(
                    dataset, metrics, dimensions, dimension_values, self._today()
                ),
            },
            {"role": "user", "content": f"用户问题：\n\"\"\"\n{question}\n\"\"\""},
        ]
        last_error = "未知错误"
        for attempt in range(2):
            reply = self._client.complete(messages)
            try:
                output = parse_planner_output(reply)
                if output.status != "ok":
                    return PlanResult(
                        status=output.status,
                        message=(output.message or "").strip() or None,
                        assumptions=output.assumptions,
                    )
                if output.query is None:
                    raise ValueError("status 为 ok 时必须提供 query")
                validate(output.query)
                return PlanResult(
                    status="ok", query=output.query, assumptions=output.assumptions
                )
            except (ValueError, ValidationError, QueryValidationError) as exc:
                last_error = describe_error(exc)
                if attempt == 0:
                    messages += [
                        {"role": "assistant", "content": reply},
                        {
                            "role": "user",
                            "content": f"上一次输出无效：{last_error}。"
                            "请严格按规则重新输出一个合法的 JSON 对象。",
                        },
                    ]
        raise PlanFailed(last_error)
