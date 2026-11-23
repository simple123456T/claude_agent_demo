import pytest

from app.demo.dataset import build_demo_dataset
from app.presentation.chart import recommend_chart
from app.presentation.summary import build_summary, describe_filter, format_number
from app.semantic.models import Filter, QuerySpec


@pytest.fixture(scope="module")
def dataset():
    return build_demo_dataset("any_schema")


def make(dataset, metrics, dimensions, rows, truncated=False, order_by=()):
    spec = QuerySpec.model_validate(
        {
            "dataset": "sales",
            "metrics": [{"name": m} for m in metrics],
            "dimensions": [{"name": d} for d in dimensions],
            "order_by": [{"field": f, "direction": d} for f, d in order_by],
        }
    )
    chart = recommend_chart(dataset, spec, rows)
    return build_summary(dataset, spec, rows, chart, truncated)


def test_number_formatting_is_exact_not_abbreviated():
    assert format_number(1234567, "元") == "1,234,567元"
    assert format_number(1234.5, "元") == "1,234.50元"
    assert format_number(None) == "无数据"


def test_stat_summary_lists_each_metric(dataset):
    text = make(dataset, ["revenue", "orders"], [], [[1500000, 420]])

    assert text == "销售额为 1,500,000元；订单数为 420单。"


def test_category_summary_names_top_and_bottom(dataset):
    rows = [["华东", 900], ["华南", 500], ["东北", 100]]

    text = make(dataset, ["revenue"], ["region"], rows)

    assert "共 3 个区域" in text
    assert "最高的是 华东（900元）" in text
    assert "最低的是 东北（100元）" in text


def test_trend_summary_reports_change_and_peak(dataset):
    rows = [["2026-01", 100], ["2026-02", 300], ["2026-03", 150]]

    text = make(dataset, ["revenue"], ["month"], rows)

    assert "从 2026-01 的 100元 变化到 2026-03 的 150元（+50.0%）" in text
    assert "峰值出现在 2026-02（300元）" in text


def test_summary_never_states_numbers_that_were_not_returned(dataset):
    rows = [["华东", 900], ["华南", 500]]

    text = make(dataset, ["revenue"], ["region"], rows)

    import re

    figures = set(re.findall(r"\d[\d,]*", text))
    assert figures <= {"2", "900", "500"}


def test_empty_result_message(dataset):
    assert "没有查到" in make(dataset, ["revenue"], ["region"], [])


RANKING = [["笔记本电脑", 900], ["台式主机", 700], ["显示器", 500]]


def test_complete_result_claims_both_extremes_and_a_total(dataset):
    text = make(dataset, ["revenue"], ["product"], RANKING, order_by=[("revenue", "desc")])

    assert "共 3 个产品" in text
    assert "最高的是 笔记本电脑" in text
    assert "最低的是 显示器" in text
    assert "还有更多" not in text


def test_top_n_ranking_is_stated_plainly_without_alarm_or_false_extremes(dataset):
    """Asking for the top 3 and getting 3 is the answer, not a problem."""

    text = make(
        dataset, ["revenue"], ["product"], RANKING, truncated=True, order_by=[("revenue", "desc")]
    )

    assert "显示前 3 个产品，还有更多未显示" in text
    assert "最高的是 笔记本电脑（900元）" in text
    assert "最低" not in text, "the lowest shown is not the lowest overall"
    assert "不完整" not in text


def test_ascending_ranking_names_the_true_lowest(dataset):
    rows = [["显示器", 500], ["台式主机", 700], ["笔记本电脑", 900]]

    text = make(dataset, ["revenue"], ["product"], rows, truncated=True, order_by=[("revenue", "asc")])

    assert "最低的是 显示器（500元）" in text
    assert "最高" not in text


def test_partial_unranked_result_is_flagged_incomplete_and_claims_no_extremes(dataset):
    rows = [["产品A", 5], ["产品B", 900], ["产品C", 1]]

    text = make(dataset, ["revenue"], ["product"], rows, truncated=True, order_by=[("product", "asc")])

    assert "还有更多未显示" in text
    assert "不完整" in text
    assert "最高" not in text and "最低" not in text


def test_partial_time_series_does_not_pass_off_the_last_shown_month_as_the_latest(dataset):
    rows = [["2025-01", 100], ["2025-02", 120], ["2025-03", 110]]

    text = make(dataset, ["revenue"], ["month"], rows, truncated=True, order_by=[("month", "asc")])

    assert "不完整" in text


def test_filter_descriptions_use_business_labels(dataset):
    assert describe_filter(dataset, Filter(field="region", operator="eq", values=["华东"])) == (
        "区域 = 华东"
    )
    assert describe_filter(
        dataset, Filter(field="month", operator="gte", values=["2026-01"])
    ) == "月份 ≥ 2026-01"
    assert describe_filter(
        dataset, Filter(field="region", operator="in", values=["华东", "华南"])
    ) == "区域 属于 华东、华南"
