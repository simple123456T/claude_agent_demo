from collections.abc import Callable
from dataclasses import dataclass

from sqlglot import expressions as exp

from app.policy.models import AccessPolicy
from app.semantic.models import Filter, FilterOperator, QuerySpec, Scalar
from app.semantic.registry import Aggregation, DatasetDefinition, MetricDefinition


class QueryValidationError(ValueError):
    """The QuerySpec violates semantic metadata or the caller's access policy."""


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    expression: exp.Select
    dialect: str
    semantic_version: str
    row_limit: int


def compile_query(
    spec: QuerySpec,
    dataset: DatasetDefinition,
    policy: AccessPolicy,
    dialect: str,
) -> CompiledQuery:
    """Compile a constrained QuerySpec; row policy is applied in the base relation."""

    _validate_references(spec, dataset, policy)
    base_columns = _required_base_columns(spec, dataset)
    base = exp.select(
        *[
            exp.column(column, quoted=True)
            for column in base_columns
        ]
        or [exp.alias_(exp.Literal.number(1), "_datagent_exists", quoted=True)]
    ).from_(_table(dataset))

    row_predicates = [_compile_filter(item, lambda name: name) for item in policy.row_filters]
    if row_predicates:
        base = base.where(_and(row_predicates))

    relation = "_datagent_base"
    outer = exp.Select().from_(base.subquery(relation))
    dimensions = [
        exp.alias_(
            exp.column(dataset.dimensions[item.name], table=relation, quoted=True),
            item.name,
            quoted=True,
        )
        for item in spec.dimensions
    ]
    metrics = [
        exp.alias_(
            _metric_expression(dataset.metrics[item.name], relation),
            item.name,
            quoted=True,
        )
        for item in spec.metrics
    ]
    outer = outer.select(*dimensions, *metrics)

    user_predicates = [
        _compile_filter(
            item,
            lambda name: dataset.dimensions[name],
            relation=relation,
        )
        for item in spec.filters
    ]
    if user_predicates:
        outer = outer.where(_and(user_predicates))

    if spec.dimensions:
        outer = outer.group_by(
            *[
                exp.column(dataset.dimensions[item.name], table=relation, quoted=True)
                for item in spec.dimensions
            ]
        )

    if spec.order_by:
        outer = outer.order_by(
            *[
                exp.Ordered(
                    this=exp.column(item.field, quoted=True),
                    desc=item.direction.value == "desc",
                )
                for item in spec.order_by
            ]
        )

    row_limit = min(spec.limit, policy.max_rows)
    outer = outer.limit(row_limit)
    sql = outer.sql(dialect=dialect, pretty=True, identify=True)
    return CompiledQuery(
        sql=sql,
        expression=outer,
        dialect=dialect,
        semantic_version=dataset.version,
        row_limit=row_limit,
    )


def _validate_references(
    spec: QuerySpec,
    dataset: DatasetDefinition,
    policy: AccessPolicy,
) -> None:
    if spec.dataset != dataset.name:
        raise QueryValidationError("QuerySpec dataset does not match the semantic definition")

    for dimension in spec.dimensions:
        if dimension.name not in dataset.dimensions:
            raise QueryValidationError(f"Unknown dimension: {dimension.name}")
        _require_column(policy, dataset.dimensions[dimension.name])

    for metric_ref in spec.metrics:
        metric = dataset.metrics.get(metric_ref.name)
        if metric is None:
            raise QueryValidationError(f"Unknown metric: {metric_ref.name}")
        if metric.source_required():
            _require_column(policy, metric.column or "")

    for item in spec.filters:
        if item.field not in dataset.dimensions:
            raise QueryValidationError(f"Filters must reference dimensions: {item.field}")
        _require_column(policy, dataset.dimensions[item.field])

    selected = {item.name for item in spec.dimensions} | {item.name for item in spec.metrics}
    for item in spec.order_by:
        if item.field not in selected:
            raise QueryValidationError("ORDER BY must reference a selected dimension or metric")


def _require_column(policy: AccessPolicy, column: str) -> None:
    if not policy.allows(column):
        raise QueryValidationError(f"Column is not available under the current policy: {column}")


def _required_base_columns(spec: QuerySpec, dataset: DatasetDefinition) -> list[str]:
    columns: list[str] = []
    for item in spec.dimensions:
        columns.append(dataset.dimensions[item.name])
    for item in spec.filters:
        columns.append(dataset.dimensions[item.field])
    for item in spec.metrics:
        column = dataset.metrics[item.name].column
        if column:
            columns.append(column)
    return list(dict.fromkeys(columns))


def _table(dataset: DatasetDefinition) -> exp.Table:
    return exp.Table(
        this=exp.to_identifier(dataset.table, quoted=True),
        db=exp.to_identifier(dataset.schema_name, quoted=True) if dataset.schema_name else None,
    )


def _metric_expression(metric: MetricDefinition, relation: str) -> exp.Expression:
    if metric.aggregation == Aggregation.COUNT and metric.column is None:
        return exp.Count(this=exp.Star())
    column = exp.column(metric.column or "", table=relation, quoted=True)
    expressions: dict[Aggregation, type[exp.Func]] = {
        Aggregation.SUM: exp.Sum,
        Aggregation.COUNT: exp.Count,
        Aggregation.AVG: exp.Avg,
        Aggregation.MIN: exp.Min,
        Aggregation.MAX: exp.Max,
    }
    if metric.aggregation == Aggregation.COUNT_DISTINCT:
        return exp.Count(this=exp.Distinct(expressions=[column]))
    function = expressions.get(metric.aggregation)
    if function is None:
        raise QueryValidationError(f"Unsupported aggregation: {metric.aggregation}")
    return function(this=column)


def _compile_filter(
    item: Filter,
    resolver: Callable[[str], str],
    relation: str | None = None,
) -> exp.Expression:
    column = exp.column(resolver(item.field), table=relation, quoted=True)
    if item.operator == FilterOperator.IS_NULL:
        return exp.Is(this=column, expression=exp.Null())
    if item.operator == FilterOperator.NOT_NULL:
        return exp.Not(this=exp.Is(this=column, expression=exp.Null()))
    if item.operator in {FilterOperator.IN, FilterOperator.NOT_IN}:
        expression = exp.In(this=column, expressions=[_literal(value) for value in item.values])
        return exp.Not(this=expression) if item.operator == FilterOperator.NOT_IN else expression

    comparisons = {
        FilterOperator.EQ: exp.EQ,
        FilterOperator.NE: exp.NEQ,
        FilterOperator.GT: exp.GT,
        FilterOperator.GTE: exp.GTE,
        FilterOperator.LT: exp.LT,
        FilterOperator.LTE: exp.LTE,
    }
    comparison = comparisons[item.operator]
    return comparison(this=column, expression=_literal(item.values[0]))


def _literal(value: Scalar) -> exp.Expression:
    if isinstance(value, bool):
        return exp.Boolean(this=value)
    if isinstance(value, (int, float)):
        return exp.Literal.number(value)
    return exp.Literal.string(value)


def _and(predicates: list[exp.Expression]) -> exp.Expression:
    result = predicates[0]
    for predicate in predicates[1:]:
        result = exp.And(this=result, expression=predicate)
    return result
