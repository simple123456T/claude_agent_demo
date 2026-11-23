from typing import Literal

from pydantic import BaseModel

from app.semantic.models import QuerySpec
from app.semantic.registry import DatasetDefinition

MAX_CATEGORIES = 30
HORIZONTAL_BAR_THRESHOLD = 8
MAX_SERIES = 6
MAX_CHART_METRICS = 3
MAX_STAT_METRICS = 6


class ChartSpec(BaseModel):
    kind: Literal["stat", "line", "bar", "table"]
    category: str | None = None
    series_dimension: str | None = None
    metrics: list[str] = []
    horizontal: bool = False
    reason: str


def recommend_chart(dataset: DatasetDefinition, spec: QuerySpec, rows: list[list]) -> ChartSpec:
    """Pick the form from the shape of the result.

    Rows are laid out as the compiler emits them: dimensions first, then metrics. Charts
    never share an axis between metrics of different scale (no dual axis) - each metric is
    drawn as its own panel, at most three, and the table always carries the rest.
    """

    dimensions = [item.name for item in spec.dimensions]
    metrics = [item.name for item in spec.metrics]
    count = len(rows)

    if count == 0:
        return ChartSpec(kind="table", reason="查询没有返回数据")
    if not metrics:
        return ChartSpec(kind="table", reason="只有维度没有指标，用表格展示")

    if not dimensions:
        if count == 1 and len(metrics) <= MAX_STAT_METRICS:
            return ChartSpec(kind="stat", metrics=metrics, reason="单个汇总值，直接展示数字")
        return ChartSpec(kind="table", reason="结果形态不适合图表")

    charted = metrics[:MAX_CHART_METRICS]
    note = "" if len(metrics) <= MAX_CHART_METRICS else f"；图表只画前 {MAX_CHART_METRICS} 个指标，其余见表格"

    if len(dimensions) == 1:
        dimension = dimensions[0]
        if dimension in dataset.time_dimensions and count >= 2:
            return ChartSpec(
                kind="line", category=dimension, metrics=charted, reason="随时间变化，用折线图" + note
            )
        if 2 <= count <= MAX_CATEGORIES:
            return ChartSpec(
                kind="bar",
                category=dimension,
                metrics=charted,
                horizontal=count > HORIZONTAL_BAR_THRESHOLD,
                reason="按类别比较大小，用柱状图" + note,
            )
        return ChartSpec(
            kind="table",
            reason="类别过多，用表格展示" if count > MAX_CATEGORIES else "只有一行，用表格展示",
        )

    if len(dimensions) == 2:
        time_dims = [d for d in dimensions if d in dataset.time_dimensions]
        others = [d for d in dimensions if d not in dataset.time_dimensions]
        if len(time_dims) == 1 and len(others) == 1:
            index = {name: position for position, name in enumerate(dimensions)}
            distinct_series = {row[index[others[0]]] for row in rows}
            distinct_time = {row[index[time_dims[0]]] for row in rows}
            if 2 <= len(distinct_series) <= MAX_SERIES and len(distinct_time) >= 2:
                return ChartSpec(
                    kind="line",
                    category=time_dims[0],
                    series_dimension=others[0],
                    metrics=charted,
                    reason="按时间比较多个类别的走势，用多折线图" + note,
                )
    return ChartSpec(kind="table", reason="维度组合较复杂，用表格展示")
