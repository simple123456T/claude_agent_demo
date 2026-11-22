import pytest
from pydantic import ValidationError
from sqlglot import expressions as exp

from app.execution.sql_guard import validate_read_only
from app.semantic.compiler import QueryValidationError, compile_query
from app.semantic.models import QuerySpec


def test_compiles_aggregated_query_and_applies_limit(sales_dataset, sales_policy):
    spec = QuerySpec.model_validate(
        {
            "dataset": "sales",
            "metrics": [{"name": "revenue"}, {"name": "orders"}],
            "dimensions": [{"name": "month"}],
            "order_by": [{"field": "revenue", "direction": "desc"}],
            "limit": 500,
        }
    )

    compiled = compile_query(spec, sales_dataset, sales_policy, "postgres")

    assert '"analytics"."fact_sales"' in compiled.sql
    assert 'SUM("_datagent_base"."amount") AS "revenue"' in compiled.sql
    assert 'COUNT(*) AS "orders"' in compiled.sql
    assert "LIMIT 500" in compiled.sql
    validate_read_only(compiled.sql, "postgres")


@pytest.mark.parametrize("dialect", ["postgres", "mysql", "clickhouse"])
def test_generated_sql_is_read_only_for_supported_dialects(
    dialect, sales_dataset, sales_policy
):
    spec = QuerySpec.model_validate(
        {
            "dataset": "sales",
            "metrics": [{"name": "customers"}],
            "dimensions": [{"name": "region"}],
        }
    )

    compiled = compile_query(spec, sales_dataset, sales_policy, dialect)

    validate_read_only(compiled.sql, dialect)
    assert "COUNT(DISTINCT" in compiled.sql


def test_row_policy_is_applied_in_base_relation_before_aggregation(
    sales_dataset, sales_policy
):
    spec = QuerySpec.model_validate(
        {"dataset": "sales", "metrics": [{"name": "revenue"}]}
    )

    compiled = compile_query(spec, sales_dataset, sales_policy, "postgres")
    base_subquery = compiled.expression.find(exp.Subquery)

    assert isinstance(base_subquery, exp.Subquery)
    assert base_subquery.this.args.get("where") is not None
    assert "INTERNAL_TEST" in base_subquery.this.args["where"].sql()
    assert compiled.expression.args.get("where") is None


def test_hidden_dimension_cannot_be_used_to_bypass_projection_policy(
    sales_dataset, sales_policy
):
    policy = sales_policy.model_copy(update={"allowed_columns": frozenset({"amount"})})
    spec = QuerySpec.model_validate(
        {"dataset": "sales", "metrics": [{"name": "revenue"}], "dimensions": [{"name": "region"}]}
    )

    with pytest.raises(QueryValidationError, match="current policy"):
        compile_query(spec, sales_dataset, policy, "postgres")


def test_hidden_dimension_cannot_be_used_in_user_filter(sales_dataset, sales_policy):
    policy = sales_policy.model_copy(update={"allowed_columns": frozenset({"amount"})})
    spec = QuerySpec.model_validate(
        {
            "dataset": "sales",
            "metrics": [{"name": "revenue"}],
            "filters": [{"field": "region", "operator": "eq", "values": ["East"]}],
        }
    )

    with pytest.raises(QueryValidationError, match="current policy"):
        compile_query(spec, sales_dataset, policy, "postgres")


def test_policy_can_filter_on_hidden_column_without_exposing_it(sales_dataset, sales_policy):
    policy = sales_policy.model_copy(update={"allowed_columns": frozenset({"amount"})})
    spec = QuerySpec.model_validate(
        {"dataset": "sales", "metrics": [{"name": "revenue"}]}
    )

    compiled = compile_query(spec, sales_dataset, policy, "postgres")

    assert "INTERNAL_TEST" in compiled.sql
    assert '"region" AS "region"' not in compiled.sql


def test_order_by_must_reference_selected_output(sales_dataset, sales_policy):
    spec = QuerySpec.model_validate(
        {
            "dataset": "sales",
            "metrics": [{"name": "revenue"}],
            "order_by": [{"field": "orders"}],
        }
    )

    with pytest.raises(QueryValidationError, match="ORDER BY"):
        compile_query(spec, sales_dataset, sales_policy, "postgres")


def test_policy_limit_is_an_upper_bound(sales_dataset, sales_policy):
    policy = sales_policy.model_copy(update={"max_rows": 25})
    spec = QuerySpec.model_validate(
        {"dataset": "sales", "metrics": [{"name": "orders"}], "limit": 500}
    )

    compiled = compile_query(spec, sales_dataset, policy, "postgres")

    assert compiled.row_limit == 25
    assert "LIMIT 25" in compiled.sql


def test_model_output_cannot_include_raw_expression(sales_dataset, sales_policy):
    with pytest.raises(ValidationError):
        QuerySpec.model_validate(
            {
                "dataset": "sales",
                "metrics": [{"name": "revenue", "expression": "sum(amount); DROP TABLE users"}],
            }
        )
