import logging
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.engine import Engine

from app.execution.runner import run_read_only, to_json_value
from app.llm.planner import MAX_VALUES_PER_DIMENSION, Planner
from app.policy.models import AccessPolicy
from app.presentation.chart import recommend_chart
from app.presentation.summary import build_summary, describe_filter
from app.query.schemas import (
    AskResponse,
    DatasetInfo,
    DimensionInfo,
    DimensionValues,
    Evidence,
    MetricInfo,
    ResultColumn,
)
from app.semantic.compiler import QueryValidationError, compile_query
from app.semantic.models import DimensionRef, OrderBy, QuerySpec, SortDirection
from app.semantic.registry import DatasetDefinition, SemanticRegistry

logger = logging.getLogger(__name__)

DIALECT = "postgres"
LOW_CARDINALITY_LIMIT = MAX_VALUES_PER_DIMENSION


class DatasetNotFound(Exception):
    pass


class AmbiguousDataset(Exception):
    pass


@dataclass(frozen=True)
class Visible:
    """What one caller is allowed to see of a dataset."""

    dataset: DatasetDefinition
    metrics: list[str]
    dimensions: list[str]


def resolve_policy(workspace_slug: str, dataset: DatasetDefinition) -> AccessPolicy:
    """Server-side policy for the caller.

    Placeholder until policy management exists: every column of the dataset is readable and
    there are no row filters. The compiler already enforces whatever this returns, so adding
    real column and row rules later changes only this function.
    """

    return AccessPolicy(
        workspace_id=workspace_slug,
        allowed_columns=frozenset(dataset.columns),
        row_filters=[],
    )


def visible_parts(dataset: DatasetDefinition, policy: AccessPolicy) -> Visible:
    metrics = [
        name
        for name, metric in dataset.metrics.items()
        if not metric.source_required() or policy.allows(metric.column or "")
    ]
    dimensions = [
        name for name, column in dataset.dimensions.items() if policy.allows(column)
    ]
    return Visible(dataset, metrics, dimensions)


def catalog(registry: SemanticRegistry, workspace_slug: str) -> list[DatasetInfo]:
    result = []
    for dataset in registry.all():
        visible = visible_parts(dataset, resolve_policy(workspace_slug, dataset))
        result.append(
            DatasetInfo(
                name=dataset.name,
                label=dataset.label or dataset.name,
                description=dataset.description,
                version=dataset.version,
                metrics=[
                    MetricInfo(
                        name=name,
                        label=dataset.metric_label(name),
                        description=dataset.metrics[name].description,
                        unit=dataset.metrics[name].unit,
                        aggregation=dataset.metrics[name].aggregation.value,
                        synonyms=dataset.synonyms.get(name, []),
                    )
                    for name in visible.metrics
                ],
                dimensions=[
                    DimensionInfo(
                        name=name,
                        label=dataset.dimension_label(name),
                        is_time=name in dataset.time_dimensions,
                        synonyms=dataset.synonyms.get(name, []),
                    )
                    for name in visible.dimensions
                ],
            )
        )
    return result


def pick_dataset(registry: SemanticRegistry, name: str | None) -> DatasetDefinition:
    if name:
        try:
            return registry.get(name)
        except KeyError as exc:
            raise DatasetNotFound(name) from exc
    datasets = registry.all()
    if not datasets:
        raise DatasetNotFound("")
    if len(datasets) > 1:
        raise AmbiguousDataset()
    return datasets[0]


def apply_default_order(spec: QuerySpec, dataset: DatasetDefinition) -> QuerySpec:
    """A LIMIT without ORDER BY returns arbitrary rows, so always order deterministically."""

    if spec.order_by:
        return spec
    time_dims = [d.name for d in spec.dimensions if d.name in dataset.time_dimensions]
    if time_dims:
        order = OrderBy(field=time_dims[0], direction=SortDirection.ASC)
    elif spec.metrics:
        order = OrderBy(field=spec.metrics[0].name, direction=SortDirection.DESC)
    elif spec.dimensions:
        order = OrderBy(field=spec.dimensions[0].name, direction=SortDirection.ASC)
    else:
        return spec
    return spec.model_copy(update={"order_by": [order]})


def execute_spec(
    engine: Engine,
    dataset: DatasetDefinition,
    policy: AccessPolicy,
    spec: QuerySpec,
    *,
    source: Literal["natural_language", "structured"],
    assumptions: list[str],
    timeout_ms: int,
) -> AskResponse:
    spec = apply_default_order(spec, dataset)
    compiled = compile_query(spec, dataset, policy, DIALECT)
    # Fetch one row beyond the limit so "there is more data" is known, not guessed from the
    # row count. The extra row is dropped; the SQL shown to the user is the one without it.
    probe_sql = compiled.expression.limit(compiled.row_limit + 1).sql(
        dialect=DIALECT, pretty=True, identify=True
    )
    raw = run_read_only(
        engine,
        probe_sql,
        dialect=DIALECT,
        max_rows=compiled.row_limit + 1,
        timeout_ms=timeout_ms,
    )
    truncated = len(raw.rows) > compiled.row_limit
    rows = [[to_json_value(value) for value in row] for row in raw.rows[: compiled.row_limit]]
    chart = recommend_chart(dataset, spec, rows)
    columns = [
        ResultColumn(name=d.name, label=dataset.dimension_label(d.name), role="dimension")
        for d in spec.dimensions
    ] + [
        ResultColumn(
            name=m.name,
            label=dataset.metric_label(m.name),
            role="metric",
            unit=dataset.metrics[m.name].unit,
        )
        for m in spec.metrics
    ]
    return AskResponse(
        status="ok",
        summary=build_summary(dataset, spec, rows, chart, truncated),
        assumptions=assumptions,
        query=spec,
        columns=columns,
        rows=rows,
        chart=chart,
        evidence=Evidence(
            dataset=dataset.name,
            dataset_label=dataset.label or dataset.name,
            semantic_version=compiled.semantic_version,
            source=source,
            sql=compiled.sql,
            row_count=len(rows),
            truncated=truncated,
            elapsed_ms=raw.elapsed_ms,
            filters=[describe_filter(dataset, item) for item in spec.filters],
        ),
    )


def fetch_dimension_values(
    engine: Engine,
    dataset: DatasetDefinition,
    policy: AccessPolicy,
    dimension: str,
    *,
    timeout_ms: int,
    limit: int = 200,
) -> DimensionValues:
    """Distinct values of one dimension, fetched through the same governed pipeline."""

    spec = QuerySpec(
        dataset=dataset.name,
        dimensions=[DimensionRef(name=dimension)],
        order_by=[OrderBy(field=dimension, direction=SortDirection.ASC)],
        limit=min(limit + 1, 500),
    )
    compiled = compile_query(spec, dataset, policy, DIALECT)
    raw = run_read_only(
        engine, compiled.sql, dialect=DIALECT, max_rows=compiled.row_limit, timeout_ms=timeout_ms
    )
    values = [str(row[0]) for row in raw.rows if row[0] is not None]
    return DimensionValues(
        dimension=dimension, values=values[:limit], truncated=len(values) > limit
    )


def planner_value_hints(
    engine: Engine, visible: Visible, policy: AccessPolicy, *, timeout_ms: int
) -> dict[str, list[str]]:
    """Valid filter values for low-cardinality dimensions, so the model maps 'east' to a real one."""

    hints: dict[str, list[str]] = {}
    for dimension in visible.dimensions:
        try:
            found = fetch_dimension_values(
                engine,
                visible.dataset,
                policy,
                dimension,
                timeout_ms=timeout_ms,
                limit=LOW_CARDINALITY_LIMIT,
            )
        except Exception:  # noqa: BLE001 - hints are best effort; planning can proceed without
            logger.warning("Could not load value hints for %s", dimension, exc_info=True)
            continue
        if not found.truncated:
            hints[dimension] = found.values
    return hints


def ask_natural_language(
    engine: Engine,
    planner: Planner,
    dataset: DatasetDefinition,
    policy: AccessPolicy,
    question: str,
    *,
    timeout_ms: int,
) -> AskResponse:
    visible = visible_parts(dataset, policy)
    hints = planner_value_hints(engine, visible, policy, timeout_ms=timeout_ms)

    def validate(candidate: QuerySpec) -> None:
        if candidate.dataset != dataset.name:
            raise QueryValidationError(f"dataset 必须是 {dataset.name}")
        compile_query(candidate, dataset, policy, DIALECT)

    plan = planner.plan(
        question,
        dataset,
        metrics=visible.metrics,
        dimensions=visible.dimensions,
        dimension_values=hints,
        validate=validate,
    )
    if plan.status != "ok" or plan.query is None:
        default_message = (
            "需要补充更多信息才能查询。"
            if plan.status == "clarify"
            else "当前数据集暂时无法回答这个问题。"
        )
        return AskResponse(
            status=plan.status,
            message=plan.message or default_message,
            assumptions=plan.assumptions,
        )
    return execute_spec(
        engine,
        dataset,
        policy,
        plan.query,
        source="natural_language",
        assumptions=plan.assumptions,
        timeout_ms=timeout_ms,
    )
