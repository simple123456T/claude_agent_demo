import pytest
from alembic import command
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.db.models import AuditEvent
from app.db.session import build_engine
from tests.integration.conftest import BOOTSTRAP_ADMIN, alembic_config

pytestmark = pytest.mark.postgres


# ---------------------------------------------------------------- migrations & audit storage


def test_migration_roundtrip(make_schema):
    schema = make_schema()
    config = alembic_config(schema)
    engine = build_engine(get_settings(), schema)
    expected = {"users", "workspaces", "workspace_members", "audit_events"}
    try:
        command.upgrade(config, "head")
        assert expected <= set(inspect(engine).get_table_names(schema=schema))

        command.downgrade(config, "base")
        assert not expected & set(inspect(engine).get_table_names(schema=schema))

        command.upgrade(config, "head")
        assert expected <= set(inspect(engine).get_table_names(schema=schema))
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_events SET action = 'tampered'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
    ],
)
def test_audit_events_are_append_only(db, statement):
    db.add(AuditEvent(action="test.event", outcome="success"))
    db.commit()

    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text(statement))
    db.rollback()


# ---------------------------------------------------------------- authentication


def test_protected_endpoint_requires_bearer_token(client):
    response = client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Bearer")


def test_invalid_token_is_rejected_without_detail_leak(client):
    response = client.get("/api/v1/me", headers={"Authorization": "Bearer forged.token.value"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or expired token"}


def test_first_request_provisions_user(client, auth, unique, db):
    subject = unique("user")

    response = client.get("/api/v1/me", headers=auth(subject, email="a@corp.internal", name="张三"))

    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == subject
    assert body["email"] == "a@corp.internal"
    assert body["display_name"] == "张三"
    assert body["is_org_admin"] is False
    assert body["workspaces"] == []
    actions = db.execute(
        select(AuditEvent.action).where(AuditEvent.actor_subject == subject)
    ).scalars()
    assert "user.provisioned" in list(actions)


def test_bootstrap_subject_becomes_org_admin(client, auth):
    response = client.get("/api/v1/me", headers=auth(BOOTSTRAP_ADMIN))

    assert response.status_code == 200
    assert response.json()["is_org_admin"] is True


# ---------------------------------------------------------------- workspaces & RBAC


def _create_workspace(client, auth, slug, admin_subject=None):
    body = {"slug": slug, "name": f"测试 {slug}"}
    if admin_subject:
        body["admin_subject"] = admin_subject
    response = client.post("/api/v1/workspaces", json=body, headers=auth(BOOTSTRAP_ADMIN))
    assert response.status_code == 201, response.text
    return response.json()


def test_non_admin_cannot_create_workspace_and_denial_is_audited(client, auth, unique, db):
    subject = unique("user")
    slug = unique("ws")

    response = client.post(
        "/api/v1/workspaces", json={"slug": slug, "name": "x"}, headers=auth(subject)
    )

    assert response.status_code == 403
    denial = db.execute(
        select(AuditEvent).where(
            AuditEvent.actor_subject == subject, AuditEvent.action == "workspace.create"
        )
    ).scalar_one()
    assert denial.outcome == "denied"
    assert denial.details["slug"] == slug


def test_duplicate_slug_conflicts(client, auth, unique):
    slug = unique("ws")
    _create_workspace(client, auth, slug)

    response = client.post(
        "/api/v1/workspaces", json={"slug": slug, "name": "again"}, headers=auth(BOOTSTRAP_ADMIN)
    )

    assert response.status_code == 409


def test_membership_lifecycle_and_role_enforcement(client, auth, unique):
    workspace = _create_workspace(client, auth, unique("ws"))
    assert workspace["role"] == "workspace_admin"
    ws_id = workspace["id"]
    analyst = unique("analyst")
    outsider = unique("outsider")

    added = client.put(
        f"/api/v1/workspaces/{ws_id}/members",
        json={"subject": analyst, "role": "analyst"},
        headers=auth(BOOTSTRAP_ADMIN),
    )
    assert added.status_code == 200
    assert added.json()["role"] == "analyst"

    me = client.get("/api/v1/me", headers=auth(analyst)).json()
    entry = next(item for item in me["workspaces"] if item["id"] == ws_id)
    assert entry["role"] == "analyst"
    assert "query:run" in entry["permissions"]
    assert "members:manage" not in entry["permissions"]

    escalation = client.put(
        f"/api/v1/workspaces/{ws_id}/members",
        json={"subject": analyst, "role": "workspace_admin"},
        headers=auth(analyst),
    )
    assert escalation.status_code == 403

    hidden = client.get(f"/api/v1/workspaces/{ws_id}/members", headers=auth(outsider))
    assert hidden.status_code == 404

    events = client.get(
        f"/api/v1/workspaces/{ws_id}/audit-events", headers=auth(BOOTSTRAP_ADMIN)
    ).json()["items"]
    by_action = {(event["action"], event["outcome"], event["actor_subject"]) for event in events}
    assert ("workspace.create", "success", BOOTSTRAP_ADMIN) in by_action
    assert ("workspace.member.upsert", "success", BOOTSTRAP_ADMIN) in by_action
    assert ("authz.members:manage", "denied", analyst) in by_action
    assert ("authz.workspace:read", "denied", outsider) in by_action


def test_analyst_cannot_read_audit_trail(client, auth, unique):
    ws_id = _create_workspace(client, auth, unique("ws"))["id"]
    analyst = unique("analyst")
    client.put(
        f"/api/v1/workspaces/{ws_id}/members",
        json={"subject": analyst, "role": "analyst"},
        headers=auth(BOOTSTRAP_ADMIN),
    )

    response = client.get(f"/api/v1/workspaces/{ws_id}/audit-events", headers=auth(analyst))

    assert response.status_code == 403


def test_last_workspace_admin_is_protected(client, auth, unique):
    ws_id = _create_workspace(client, auth, unique("ws"))["id"]
    admin_id = client.get("/api/v1/me", headers=auth(BOOTSTRAP_ADMIN)).json()["id"]

    demote = client.put(
        f"/api/v1/workspaces/{ws_id}/members",
        json={"subject": BOOTSTRAP_ADMIN, "role": "analyst"},
        headers=auth(BOOTSTRAP_ADMIN),
    )
    remove = client.delete(
        f"/api/v1/workspaces/{ws_id}/members/{admin_id}", headers=auth(BOOTSTRAP_ADMIN)
    )
    assert demote.status_code == 409
    assert remove.status_code == 409

    second_admin = unique("admin")
    client.put(
        f"/api/v1/workspaces/{ws_id}/members",
        json={"subject": second_admin, "role": "workspace_admin"},
        headers=auth(BOOTSTRAP_ADMIN),
    )
    demote_again = client.put(
        f"/api/v1/workspaces/{ws_id}/members",
        json={"subject": BOOTSTRAP_ADMIN, "role": "analyst"},
        headers=auth(BOOTSTRAP_ADMIN),
    )
    assert demote_again.status_code == 200


def test_org_admin_governs_workspace_without_data_access(client, auth, unique):
    owner = unique("owner")
    ws_id = _create_workspace(client, auth, unique("ws"), admin_subject=owner)["id"]

    listed = client.get("/api/v1/workspaces", headers=auth(BOOTSTRAP_ADMIN)).json()
    entry = next(item for item in listed if item["id"] == ws_id)
    assert entry["role"] is None
    assert set(entry["permissions"]) == {"workspace:read", "members:manage", "audit:read"}

    members = client.get(f"/api/v1/workspaces/{ws_id}/members", headers=auth(BOOTSTRAP_ADMIN))
    assert members.status_code == 200
    assert [item["subject"] for item in members.json()] == [owner]


def test_audit_trail_paginates_newest_first(client, auth, unique):
    ws_id = _create_workspace(client, auth, unique("ws"))["id"]
    for _ in range(4):
        client.put(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"subject": unique("viewer"), "role": "viewer"},
            headers=auth(BOOTSTRAP_ADMIN),
        )

    first = client.get(
        f"/api/v1/workspaces/{ws_id}/audit-events?limit=2", headers=auth(BOOTSTRAP_ADMIN)
    ).json()
    second = client.get(
        f"/api/v1/workspaces/{ws_id}/audit-events?limit=2&before_id={first['next_before_id']}",
        headers=auth(BOOTSTRAP_ADMIN),
    ).json()

    first_ids = [item["id"] for item in first["items"]]
    second_ids = [item["id"] for item in second["items"]]
    assert first_ids == sorted(first_ids, reverse=True)
    assert max(second_ids) < min(first_ids)


def test_request_id_is_echoed_and_recorded(client, auth, unique, db):
    slug = unique("ws")
    response = client.post(
        "/api/v1/workspaces",
        json={"slug": slug, "name": "trace"},
        headers={**auth(BOOTSTRAP_ADMIN), "X-Request-ID": "trace-123"},
    )

    assert response.headers["X-Request-ID"] == "trace-123"
    event = db.execute(
        select(AuditEvent).where(
            AuditEvent.action == "workspace.create", AuditEvent.request_id == "trace-123"
        )
    ).scalar_one()
    assert event.details["slug"] == slug
