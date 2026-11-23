import pytest

from app.demo.dataset import build_demo_dataset
from app.presentation.chart import recommend_chart
from app.semantic.models import QuerySpec


@pytest.fixture(scope="module")
def dataset():
    return build_demo_dataset("any_schema")


def spec(metrics=(), dimensions=()):
    return QuerySpec.model_validate(
        {
            "dataset": "sales",
            "metrics": [{"name": m} for m in metrics],
            "dimensions": [{"name": d} for d in dimensions],
        }
    )


def test_empty_result_is_a_table(dataset):
    chart = recommend_chart(dataset, spec(["revenue"], ["region"]), [])

    assert chart.kind == "table"


def test_single_aggregate_is_a_stat(dataset):
    chart = recommend_chart(dataset, spec(["revenue", "orders"]), [[1000, 5]])

    assert chart.kind == "stat"
    assert chart.metrics == ["revenue", "orders"]


def test_time_dimension_gives_line(dataset):
    rows = [["2026-01", 10], ["2026-02", 12], ["2026-03", 9]]

    chart = recommend_chart(dataset, spec(["revenue"], ["month"]), rows)

    assert chart.kind == "line"
    assert chart.category == "month"


def test_single_point_in_time_is_not_a_line(dataset):
    chart = recommend_chart(dataset, spec(["revenue"], ["month"]), [["2026-01", 10]])

    assert chart.kind == "table"


def test_few_categories_give_vertical_bars(dataset):
    rows = [[f"区域{i}", i] for i in range(5)]

    chart = recommend_chart(dataset, spec(["revenue"], ["region"]), rows)

    assert chart.kind == "bar"
    assert chart.horizontal is False


def test_many_categories_switch_to_horizontal_bars(dataset):
    rows = [[f"产品{i}", i] for i in range(12)]

    chart = recommend_chart(dataset, spec(["revenue"], ["product"]), rows)

    assert chart.kind == "bar"
    assert chart.horizontal is True


def test_too_many_categories_fall_back_to_table(dataset):
    rows = [[f"产品{i}", i] for i in range(31)]

    chart = recommend_chart(dataset, spec(["revenue"], ["product"]), rows)

    assert chart.kind == "table"


def test_time_by_category_gives_multi_line(dataset):
    rows = [
        [month, region, 1]
        for month in ("2026-01", "2026-02", "2026-03")
        for region in ("华东", "华南")
    ]

    chart = recommend_chart(dataset, spec(["revenue"], ["month", "region"]), rows)

    assert chart.kind == "line"
    assert chart.series_dimension == "region"
    assert chart.category == "month"


def test_too_many_series_fall_back_to_table(dataset):
    rows = [[month, f"产品{i}", 1] for month in ("2026-01", "2026-02") for i in range(8)]

    chart = recommend_chart(dataset, spec(["revenue"], ["month", "product"]), rows)

    assert chart.kind == "table"


def test_metrics_are_never_combined_on_one_axis(dataset):
    """No dual axis: at most three metrics are charted, each as its own panel."""

    rows = [["华东", 1, 2, 3, 4], ["华南", 1, 2, 3, 4], ["华北", 1, 2, 3, 4]]
    metrics = ["revenue", "orders", "customers", "quantity"]

    chart = recommend_chart(dataset, spec(metrics, ["region"]), rows)

    assert chart.kind == "bar"
    assert chart.metrics == ["revenue", "orders", "customers"]
    assert "表格" in chart.reason


def test_dimensions_without_metrics_is_a_table(dataset):
    chart = recommend_chart(dataset, spec([], ["region"]), [["华东"], ["华南"]])

    assert chart.kind == "table"
