"""End-to-end tests of the question-answering pipeline on real PostgreSQL.

Every number returned by the API is checked against SQL computed independently by the test,
so a passing test means the answer is correct, not merely that something came back.
"""

import json

import pytest
from sqlalchemy import select, text

from app.api.routes.query import get_planner_factory
from app.db.models import AuditEvent
from app.execution.runner import QueryTimeout, run_read_only
from app.llm.client import ModelUnavailable
from app.llm.planner import Planner
from app.main import app
from tests.integration.conftest import BOOTSTRAP_ADMIN

pytestmark = pytest.mark.postgres


class FakeClient:
    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)

    def complete(self, messages):
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def use_model(*replies):
    planner = Planner(FakeClient(*replies))
    app.dependency_overrides[get_planner_factory] = lambda: (lambda: planner)


@pytest.fixture
def workspace(client, auth, unique):
    """A workspace with an analyst and a viewer; returns ids and subjects."""

    created = client.post(
        "/api/v1/workspaces",
        json={"slug": unique("ws"), "name": "查询测试"},
        headers=auth(BOOTSTRAP_ADMIN),
    )
    assert created.status_code == 201, created.text
    ws_id = created.json()["id"]
    analyst, viewer = unique("analyst"), unique("viewer")
    for subject, role in ((analyst, "analyst"), (viewer, "viewer")):
        response = client.put(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"subject": subject, "role": role},
            headers=auth(BOOTSTRAP_ADMIN),
        )
        assert response.status_code == 200
    return {"id": ws_id, "analyst": analyst, "viewer": viewer, "admin": BOOTSTRAP_ADMIN}


@pytest.fixture
def truth(admin_engine, demo_schema):
    """Run SQL straight against the demo table, bypassing the application entirely."""

    def query(sql: str):
        with admin_engine.connect() as connection:
            return connection.execute(
                text(sql.replace("{t}", f'"{demo_schema}"."demo_sales"'))
            ).all()

    return query


def ask(client, auth, ws, who="analyst", **body):
    return client.post(
        f"/api/v1/workspaces/{ws['id']}/ask", json=body, headers=auth(ws[who])
    )


def structured(**query):
    return {"query": {"dataset": "sales", **query}}


# ------------------------------------------------------------------ correctness against ground truth


def test_total_revenue_matches_the_database(client, auth, workspace, truth):
    response = ask(client, auth, workspace, **structured(metrics=[{"name": "revenue"}]))

    assert response.status_code == 200, response.text
    body = response.json()
    expected = float(truth("SELECT SUM(amount) FROM {t}")[0][0])
    assert body["rows"][0][0] == pytest.approx(expected)
    assert body["chart"]["kind"] == "stat"
    assert f"{expected:,.2f}" in body["summary"]
    assert body["evidence"]["row_count"] == 1
    assert body["evidence"]["semantic_version"] == "2026.11.1"
    assert body["evidence"]["source"] == "structured"


def test_revenue_by_region_matches_group_by_and_is_sorted(client, auth, workspace, truth):
    response = ask(
        client,
        auth,
        workspace,
        **structured(metrics=[{"name": "revenue"}, {"name": "orders"}], dimensions=[{"name": "region"}]),
    )

    body = response.json()
    expected = {
        region: (float(revenue), orders)
        for region, revenue, orders in truth(
            "SELECT region, SUM(amount), COUNT(*) FROM {t} GROUP BY region"
        )
    }
    actual = {row[0]: (row[1], row[2]) for row in body["rows"]}
    assert actual.keys() == expected.keys()
    for region, (revenue, orders) in expected.items():
        assert actual[region][0] == pytest.approx(revenue)
        assert actual[region][1] == orders
    revenues = [row[1] for row in body["rows"]]
    assert revenues == sorted(revenues, reverse=True), "default order is highest first"
    assert body["chart"]["kind"] == "bar"
    assert [c["label"] for c in body["columns"]] == ["区域", "销售额", "订单数"]


def test_distinct_customers_and_average_use_the_right_aggregation(client, auth, workspace, truth):
    body = ask(
        client,
        auth,
        workspace,
        **structured(metrics=[{"name": "customers"}, {"name": "avg_order_value"}]),
    ).json()

    customers, average = truth("SELECT COUNT(DISTINCT customer_id), AVG(amount) FROM {t}")[0]
    assert body["rows"][0][0] == customers
    assert body["rows"][0][1] == pytest.approx(float(average))


def test_monthly_trend_with_filter(client, auth, workspace, truth):
    body = ask(
        client,
        auth,
        workspace,
        **structured(
            metrics=[{"name": "revenue"}],
            dimensions=[{"name": "month"}],
            filters=[
                {"field": "region", "operator": "eq", "values": ["华东"]},
                {"field": "month", "operator": "gte", "values": ["2026-01"]},
            ],
        ),
    ).json()

    expected = [
        (month, float(revenue))
        for month, revenue in truth(
            "SELECT order_month, SUM(amount) FROM {t} "
            "WHERE region = '华东' AND order_month >= '2026-01' "
            "GROUP BY order_month ORDER BY order_month"
        )
    ]
    assert [(r[0], pytest.approx(r[1])) for r in body["rows"]] == expected
    assert body["chart"]["kind"] == "line"
    assert body["evidence"]["filters"] == ["区域 = 华东", "月份 ≥ 2026-01"]
    assert "峰值出现在" in body["summary"]


def test_month_by_region_gives_multi_line_matching_ground_truth(client, auth, workspace, truth):
    body = ask(
        client,
        auth,
        workspace,
        **structured(
            metrics=[{"name": "revenue"}],
            dimensions=[{"name": "month"}, {"name": "region"}],
            filters=[
                {"field": "region", "operator": "in", "values": ["华东", "华南"]},
                {"field": "month", "operator": "gte", "values": ["2026-06"]},
            ],
            order_by=[{"field": "month"}, {"field": "region"}],
        ),
    ).json()

    expected = {
        (month, region): float(revenue)
        for month, region, revenue in truth(
            "SELECT order_month, region, SUM(amount) FROM {t} "
            "WHERE region IN ('华东','华南') AND order_month >= '2026-06' "
            "GROUP BY order_month, region"
        )
    }
    assert {(r[0], r[1]): r[2] for r in body["rows"]} == pytest.approx(expected)
    assert body["chart"]["kind"] == "line"
    assert body["chart"]["series_dimension"] == "region"


def test_top_n_respects_limit(client, auth, workspace, truth):
    body = ask(
        client,
        auth,
        workspace,
        **structured(
            metrics=[{"name": "revenue"}],
            dimensions=[{"name": "product"}],
            order_by=[{"field": "revenue", "direction": "desc"}],
            limit=3,
        ),
    ).json()

    top3 = truth("SELECT product FROM {t} GROUP BY product ORDER BY SUM(amount) DESC LIMIT 3")
    assert [row[0] for row in body["rows"]] == [row[0] for row in top3]


def products_query(limit):
    return structured(
        metrics=[{"name": "revenue"}],
        dimensions=[{"name": "product"}],
        order_by=[{"field": "revenue", "direction": "desc"}],
        limit=limit,
    )


def test_truncation_is_detected_from_the_database_not_guessed(client, auth, workspace, truth):
    total = int(truth("SELECT COUNT(DISTINCT product) FROM {t}")[0][0])
    assert total == 7

    clipped = ask(client, auth, workspace, **products_query(3)).json()
    exact = ask(client, auth, workspace, **products_query(total)).json()
    roomy = ask(client, auth, workspace, **products_query(100)).json()

    assert clipped["evidence"]["truncated"] is True
    assert len(clipped["rows"]) == 3, "the probe row must never leak into the result"
    assert "显示前 3 个产品，还有更多未显示" in clipped["summary"]
    assert "最低" not in clipped["summary"]
    assert "不完整" not in clipped["summary"], "a top-N ranking is not an error"

    # Exactly as many rows as the limit is NOT truncation: nothing is hidden.
    assert exact["evidence"]["truncated"] is False
    assert len(exact["rows"]) == total
    assert f"共 {total} 个产品" in exact["summary"]
    assert "最低的是" in exact["summary"]

    assert roomy["evidence"]["truncated"] is False
    assert len(roomy["rows"]) == total


def test_the_displayed_sql_is_the_query_asked_for_not_the_probe(client, auth, workspace):
    body = ask(client, auth, workspace, **products_query(3)).json()

    assert body["evidence"]["sql"].rstrip().endswith("LIMIT 3")


def test_hostile_filter_values_are_data_not_sql(client, auth, workspace, truth):
    """Quotes, '%', ':name' and SQL fragments inside values must never be interpreted."""

    total = int(truth("SELECT COUNT(*) FROM {t}")[0][0])
    for value in ("100%:x", "a'b", "'; DROP TABLE x; --", ":region", "%s", "{0}"):
        body = ask(
            client,
            auth,
            workspace,
            **structured(
                metrics=[{"name": "orders"}],
                filters=[{"field": "region", "operator": "ne", "values": [value]}],
            ),
        )
        assert body.status_code == 200, (value, body.text)
        assert body.json()["rows"][0][0] == total, value


# ------------------------------------------------------------------ authorization


def test_viewer_cannot_ask_and_denial_is_audited(client, auth, workspace, db):
    response = ask(
        client, auth, workspace, who="viewer", **structured(metrics=[{"name": "orders"}])
    )

    assert response.status_code == 403
    denial = db.execute(
        select(AuditEvent).where(
            AuditEvent.actor_subject == workspace["viewer"],
            AuditEvent.action == "authz.query:run",
        )
    ).scalar_one()
    assert denial.outcome == "denied"


def test_outsider_gets_404_not_a_hint_the_workspace_exists(client, auth, workspace, unique):
    outsider = unique("outsider")

    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/ask",
        json=structured(metrics=[{"name": "orders"}]),
        headers=auth(outsider),
    )

    assert response.status_code == 404


def test_org_admin_without_membership_cannot_query_workspace_data(client, auth, unique):
    other = client.post(
        "/api/v1/workspaces",
        json={"slug": unique("ws"), "name": "他人的", "admin_subject": unique("owner")},
        headers=auth(BOOTSTRAP_ADMIN),
    ).json()

    response = client.post(
        f"/api/v1/workspaces/{other['id']}/ask",
        json=structured(metrics=[{"name": "orders"}]),
        headers=auth(BOOTSTRAP_ADMIN),
    )

    assert response.status_code == 403


def test_unauthenticated_request_is_rejected(client, workspace):
    response = client.post(
        f"/api/v1/workspaces/{workspace['id']}/ask", json=structured(metrics=[{"name": "orders"}])
    )

    assert response.status_code == 401


# ------------------------------------------------------------------ input validation


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"question": "x", **structured(metrics=[{"name": "orders"}])},
        {"question": ""},
        {"question": "x" * 501},
        structured(metrics=[{"name": "orders"}], limit=501),
        structured(metrics=[{"name": "orders", "expression": "1; DROP TABLE x"}]),
    ],
)
def test_malformed_requests_are_rejected_before_any_work(client, auth, workspace, body):
    assert ask(client, auth, workspace, **body).status_code == 422


def test_unknown_metric_is_a_clear_422(client, auth, workspace):
    response = ask(client, auth, workspace, **structured(metrics=[{"name": "profit"}]))

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_query"
    assert "profit" in response.json()["detail"]["message"]


def test_unknown_dataset_is_404(client, auth, workspace):
    response = ask(
        client,
        auth,
        workspace,
        dataset="payroll",
        query={"dataset": "payroll", "metrics": [{"name": "orders"}]},
    )

    assert response.status_code == 404


# ------------------------------------------------------------------ natural language path


VALID_PLAN = {
    "status": "ok",
    "assumptions": ["「各区域」按区域维度汇总"],
    "query": {
        "dataset": "sales",
        "metrics": [{"name": "revenue"}],
        "dimensions": [{"name": "region"}],
    },
}


def test_question_without_a_configured_model_explains_and_points_to_manual(
    client, auth, workspace, db
):
    response = ask(client, auth, workspace, question="各区域销售额")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "model_not_configured"
    assert "手动构建" in detail["message"]
    failure = db.execute(
        select(AuditEvent).where(
            AuditEvent.actor_subject == workspace["analyst"], AuditEvent.outcome == "failure"
        )
    ).scalar_one()
    assert failure.details["error"] == "model_not_configured"


def test_question_is_planned_executed_and_answered_from_real_data(client, auth, workspace, truth):
    use_model(json.dumps(VALID_PLAN))

    response = ask(client, auth, workspace, question="各区域销售额是多少")

    assert response.status_code == 200, response.text
    body = response.json()
    expected = {r: float(v) for r, v in truth("SELECT region, SUM(amount) FROM {t} GROUP BY region")}
    assert {row[0]: row[1] for row in body["rows"]} == pytest.approx(expected)
    assert body["assumptions"] == ["「各区域」按区域维度汇总"]
    assert body["evidence"]["source"] == "natural_language"


def test_question_text_is_audited_but_results_are_not(client, auth, workspace, db):
    use_model(json.dumps(VALID_PLAN))
    ask(client, auth, workspace, question="审计用问题")

    event = db.execute(
        select(AuditEvent).where(
            AuditEvent.actor_subject == workspace["analyst"], AuditEvent.action == "query.run"
        )
    ).scalar_one()
    assert event.outcome == "success"
    assert event.details["question"] == "审计用问题"
    assert event.details["source"] == "natural_language"
    assert event.details["query"]["metrics"] == [{"name": "revenue"}]
    assert isinstance(event.details["rows"], int)
    assert "华东" not in json.dumps(event.details, ensure_ascii=False), "no result data in audit"


def test_model_asking_for_clarification_runs_nothing(client, auth, workspace):
    use_model(json.dumps({"status": "clarify", "message": "请问是哪个时间范围？"}))

    body = ask(client, auth, workspace, question="最近怎么样").json()

    assert body["status"] == "clarify"
    assert body["message"] == "请问是哪个时间范围？"
    assert body["rows"] == [] and body["evidence"] is None


def test_unsupported_question_is_explained(client, auth, workspace):
    use_model(json.dumps({"status": "unsupported", "message": "暂不支持同比分析"}))

    body = ask(client, auth, workspace, question="销售额同比增长多少").json()

    assert body["status"] == "unsupported"
    assert body["message"] == "暂不支持同比分析"


def test_invalid_plan_is_repaired_once_then_answered(client, auth, workspace):
    bad = {**VALID_PLAN, "query": {**VALID_PLAN["query"], "metrics": [{"name": "profit"}]}}
    use_model(json.dumps(bad), json.dumps(VALID_PLAN))

    response = ask(client, auth, workspace, question="各区域销售额")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_unrecoverable_model_output_is_a_clear_error_not_a_guess(client, auth, workspace):
    use_model("我不知道", "还是不知道")

    response = ask(client, auth, workspace, question="各区域销售额")

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "plan_failed"


def test_model_outage_is_reported_as_bad_gateway(client, auth, workspace):
    use_model(ModelUnavailable("无法连接模型服务"))

    response = ask(client, auth, workspace, question="各区域销售额")

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "model_unavailable"


def test_model_cannot_reach_beyond_the_catalog(client, auth, workspace):
    """A hallucinated column is rejected by the compiler, never sent to the database."""

    hallucinated = {
        **VALID_PLAN,
        "query": {**VALID_PLAN["query"], "dimensions": [{"name": "salary"}]},
    }
    use_model(json.dumps(hallucinated), json.dumps(hallucinated))

    response = ask(client, auth, workspace, question="按薪资看销售额")

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "plan_failed"


# ------------------------------------------------------------------ catalog & values


def test_catalog_lists_business_labels(client, auth, workspace):
    response = client.get(f"/api/v1/workspaces/{workspace['id']}/datasets", headers=auth(workspace["analyst"]))

    assert response.status_code == 200
    (dataset,) = response.json()
    assert dataset["label"] == "销售订单"
    assert {m["name"]: m["label"] for m in dataset["metrics"]}["revenue"] == "销售额"
    month = next(d for d in dataset["dimensions"] if d["name"] == "month")
    assert month["is_time"] is True and month["label"] == "月份"


def test_catalog_is_hidden_from_viewers(client, auth, workspace):
    response = client.get(f"/api/v1/workspaces/{workspace['id']}/datasets", headers=auth(workspace["viewer"]))

    assert response.status_code == 403


def test_dimension_values_match_the_data(client, auth, workspace, truth):
    response = client.get(
        f"/api/v1/workspaces/{workspace['id']}/datasets/sales/dimensions/region/values",
        headers=auth(workspace["analyst"]),
    )

    assert response.status_code == 200
    assert response.json()["values"] == sorted(r[0] for r in truth("SELECT DISTINCT region FROM {t}"))
    assert response.json()["truncated"] is False


def test_unknown_dimension_values_is_404(client, auth, workspace):
    response = client.get(
        f"/api/v1/workspaces/{workspace['id']}/datasets/sales/dimensions/salary/values",
        headers=auth(workspace["analyst"]),
    )

    assert response.status_code == 404


# ------------------------------------------------------------------ execution safety


def test_runaway_query_is_cancelled_and_the_pool_stays_healthy(engine, demo_schema):
    table = f'"{demo_schema}"."demo_sales"'
    runaway = f"SELECT COUNT(*) FROM {table} a, {table} b, {table} c LIMIT 1"

    with pytest.raises(QueryTimeout):
        run_read_only(engine, runaway, max_rows=1, timeout_ms=300)

    healthy = run_read_only(engine, f"SELECT COUNT(*) FROM {table} LIMIT 1", max_rows=1)
    assert healthy.rows[0][0] > 0


def test_execution_layer_refuses_unvalidated_sql(engine, demo_schema):
    from app.execution.sql_guard import SQLSafetyError

    with pytest.raises(SQLSafetyError):
        run_read_only(engine, f'DELETE FROM "{demo_schema}"."demo_sales"')
