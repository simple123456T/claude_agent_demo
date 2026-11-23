from typing import Any

from app.presentation.chart import ChartSpec
from app.semantic.models import Filter, FilterOperator, QuerySpec, SortDirection
from app.semantic.registry import DatasetDefinition

OPERATOR_TEXT = {
    FilterOperator.EQ: "=",
    FilterOperator.NE: "≠",
    FilterOperator.GT: ">",
    FilterOperator.GTE: "≥",
    FilterOperator.LT: "<",
    FilterOperator.LTE: "≤",
    FilterOperator.IN: "属于",
    FilterOperator.NOT_IN: "不属于",
    FilterOperator.IS_NULL: "为空",
    FilterOperator.NOT_NULL: "不为空",
}

INCOMPLETE_WARNING = "结果只显示了一部分，图表和对比并不完整，请加过滤条件缩小范围。"


def format_number(value: Any, unit: str | None = None) -> str:
    """Exact figures with thousands separators; never rounded to a different magnitude."""

    if value is None:
        return "无数据"
    text = f"{value:,}" if isinstance(value, int) else f"{float(value):,.2f}"
    return f"{text}{unit or ''}"


def describe_filter(dataset: DatasetDefinition, item: Filter) -> str:
    label = dataset.dimension_label(item.field)
    operator = OPERATOR_TEXT[item.operator]
    if item.operator in {FilterOperator.IS_NULL, FilterOperator.NOT_NULL}:
        return f"{label}{operator}"
    values = "、".join(str(value) for value in item.values)
    return f"{label} {operator} {values}"


def build_summary(
    dataset: DatasetDefinition,
    spec: QuerySpec,
    rows: list[list],
    chart: ChartSpec,
    truncated: bool,
) -> str:
    """A summary assembled only from returned values - no model involved, nothing invented.

    ``truncated`` means the database really holds more rows than were returned. A ranking
    (ordered by a metric) is meant to show only its top N, so that is stated plainly; for
    anything else a partial result is flagged as incomplete. Superlatives ("highest",
    "lowest") are only claimed when they hold for the whole result.
    """

    if not rows:
        return "没有查到符合条件的数据。可以放宽过滤条件，或检查时间范围内是否有数据。"

    dimensions = [item.name for item in spec.dimensions]
    metrics = [item.name for item in spec.metrics]
    offset = len(dimensions)
    count = len(rows)

    lead = spec.order_by[0] if spec.order_by else None
    ranked = lead is not None and lead.field in metrics
    descending = lead is not None and lead.direction == SortDirection.DESC
    parts: list[str] = []
    needs_warning = truncated and not ranked

    if not metrics:
        parts.append(f"显示前 {count} 行，还有更多未显示。" if truncated else f"共返回 {count} 行。")

    elif not dimensions and count == 1:
        parts.append(
            "；".join(
                f"{dataset.metric_label(name)}为 "
                f"{format_number(rows[0][offset + position], dataset.metrics[name].unit)}"
                for position, name in enumerate(metrics)
            )
            + "。"
        )

    elif len(dimensions) == 1:
        first = metrics[0]
        definition = dataset.metrics[first]
        label = dataset.metric_label(first)
        dimension_label = dataset.dimension_label(dimensions[0])
        parts.append(
            f"显示前 {count} 个{dimension_label}，还有更多未显示。"
            if truncated
            else f"共 {count} 个{dimension_label}。"
        )
        usable = [(row[0], row[offset]) for row in rows if row[offset] is not None]

        if chart.kind == "line" and len(usable) >= 2:
            (start_key, start), (end_key, end) = usable[0], usable[-1]
            change = ""
            if isinstance(start, (int, float)) and start:
                change = f"（{(end - start) / abs(start) * 100:+.1f}%）"
            peak_key, peak = max(usable, key=lambda pair: pair[1])
            parts.append(
                f"{label}从 {start_key} 的 {format_number(start, definition.unit)} "
                f"变化到 {end_key} 的 {format_number(end, definition.unit)}{change}，"
                f"峰值出现在 {peak_key}（{format_number(peak, definition.unit)}）。"
            )
        elif usable and not truncated:
            top_key, top = max(usable, key=lambda pair: pair[1])
            low_key, low = min(usable, key=lambda pair: pair[1])
            text = f"{label}最高的是 {top_key}（{format_number(top, definition.unit)}）"
            if len(usable) > 1:
                text += f"，最低的是 {low_key}（{format_number(low, definition.unit)}）"
            parts.append(text + "。")
        elif usable and ranked:
            # Partial result: only the end the ranking starts from is a true extreme.
            pick = max if descending else min
            key, value = pick(usable, key=lambda pair: pair[1])
            word = "最高" if descending else "最低"
            parts.append(f"{label}{word}的是 {key}（{format_number(value, definition.unit)}）。")

    else:
        parts.append(f"显示前 {count} 行，还有更多未显示。" if truncated else f"共返回 {count} 行。")

    if needs_warning:
        parts.append(INCOMPLETE_WARNING)
    return "".join(parts)
