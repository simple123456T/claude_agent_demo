"""Development sign-in: what makes it usable, and what keeps it from becoming a backdoor."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes.query import get_query_engine, get_registry
from app.core.config import Settings, get_settings
from app.db.models import AuditEvent, Workspace
from app.db.session import get_db
from app.demo.dataset import build_demo_dataset
from app.demo.seed import DEMO_WORKSPACE_SLUG, seed_demo_workspace
from app.main import app
from app.semantic.registry import SemanticRegistry

pytestmark = pytest.mark.postgres


def make_client(engine, demo_schema, *, host: str, **setting_overrides) -> Iterator[TestClient]:
    factory = sessionmaker(engine, expire_on_commit=False)

    def override_db() -> Iterator[Session]:
        with factory() as session:
            yield session

    registry = SemanticRegistry()
    registry.register(build_demo_dataset(demo_schema))
    settings = get_settings().model_copy(
        update={"oidc_issuer": None, "oidc_audience": None, "oidc_client_id": None,
                "model_base_url": None, "model_name": None, **setting_overrides}
    )
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[get_query_engine] = lambda: engine
    try:
        # Note: no get_verifier override - the real dev identity provider is exercised.
        with TestClient(app, client=(host, 50000)) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def dev_client(engine: Engine, demo_schema: str) -> Iterator[TestClient]:
    yield from make_client(engine, demo_schema, host="127.0.0.1", dev_auth_enabled=True)


@pytest.fixture
def remote_client(engine: Engine, demo_schema: str) -> Iterator[TestClient]:
    yield from make_client(engine, demo_schema, host="10.1.2.3", dev_auth_enabled=True)


@pytest.fixture
def prod_like_client(engine: Engine, demo_schema: str) -> Iterator[TestClient]:
    yield from make_client(engine, demo_schema, host="127.0.0.1", dev_auth_enabled=False)


def login(client, subject):
    response = client.post("/api/v1/auth/dev-login", json={"subject": subject})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_config_advertises_dev_mode_with_the_three_identities(dev_client):
    body = dev_client.get("/api/v1/auth/config").json()

    assert body["mode"] == "dev"
    assert [i["subject"] for i in body["dev_identities"]] == [
        "dev-admin", "dev-analyst", "dev-viewer"
    ]


def test_config_reports_whether_a_model_is_available(dev_client):
    assert dev_client.get("/api/v1/auth/config").json()["model_configured"] is False


def test_seeded_demo_workspace_supports_the_real_login_to_answer_flow(dev_client, db):
    seed_demo_workspace(db)
    seed_demo_workspace(db)  # idempotent: second run must not duplicate or fail
    assert db.execute(
        select(Workspace).where(Workspace.slug == DEMO_WORKSPACE_SLUG)
    ).scalars().all().__len__() == 1

    analyst = login(dev_client, "dev-analyst")
    me = dev_client.get("/api/v1/me", headers=analyst).json()
    demo = next(w for w in me["workspaces"] if w["slug"] == DEMO_WORKSPACE_SLUG)
    assert demo["role"] == "analyst"

    answer = dev_client.post(
        f"/api/v1/workspaces/{demo['id']}/ask",
        json={"query": {"dataset": "sales", "metrics": [{"name": "orders"}]}},
        headers=analyst,
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["rows"][0][0] > 1000


def test_seeded_roles_enforce_who_may_ask(dev_client, db):
    workspace = seed_demo_workspace(db)
    body = {"query": {"dataset": "sales", "metrics": [{"name": "orders"}]}}
    url = f"/api/v1/workspaces/{workspace.id}/ask"

    assert dev_client.post(url, json=body, headers=login(dev_client, "dev-admin")).status_code == 200
    assert dev_client.post(url, json=body, headers=login(dev_client, "dev-analyst")).status_code == 200
    assert dev_client.post(url, json=body, headers=login(dev_client, "dev-viewer")).status_code == 403

    me = dev_client.get("/api/v1/me", headers=login(dev_client, "dev-admin")).json()
    assert me["is_org_admin"] is True


def test_login_is_audited(dev_client, db):
    login(dev_client, "dev-analyst")

    event = db.execute(
        select(AuditEvent)
        .where(AuditEvent.action == "auth.dev_login", AuditEvent.actor_subject == "dev-analyst")
        .order_by(AuditEvent.id.desc())
    ).scalars().first()
    assert event is not None


def test_only_the_preset_identities_can_sign_in(dev_client):
    response = dev_client.post("/api/v1/auth/dev-login", json={"subject": "root"})

    assert response.status_code == 403


def test_dev_login_refuses_non_loopback_clients(remote_client):
    response = remote_client.post("/api/v1/auth/dev-login", json={"subject": "dev-admin"})

    assert response.status_code == 403


def test_dev_login_does_not_exist_unless_enabled(prod_like_client):
    response = prod_like_client.post("/api/v1/auth/dev-login", json={"subject": "dev-admin"})

    assert response.status_code == 404
    assert prod_like_client.get("/api/v1/auth/config").json() == {
        "mode": "unconfigured", "dev_identities": [], "model_configured": False
    }


def test_tokens_from_another_signer_are_not_accepted(dev_client, signing_key):
    from tests.tokens import make_token

    forged = make_token(signing_key, "dev-admin", issuer="datagent-dev-local", audience="datagent-dev")

    response = dev_client.get("/api/v1/me", headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 401


# ---------------------------------------------------------------- settings-level guarantees


def settings(**overrides) -> Settings:
    return Settings(
        _env_file=None, database_url="postgresql://x/y", redis_url="redis://x/0", **overrides
    )


def test_dev_auth_is_inactive_by_default():
    assert settings().dev_auth_active is False


def test_dev_auth_is_never_active_in_production():
    assert settings(dev_auth_enabled=True, app_env="production").dev_auth_active is False


def test_dev_auth_switches_off_once_real_oidc_is_configured():
    configured = settings(
        dev_auth_enabled=True, oidc_issuer="https://sso.corp/realms/x", oidc_client_id="app"
    )

    assert configured.dev_auth_active is False
    assert configured.oidc_configured is True


def test_dev_auth_is_active_only_when_deliberately_enabled_in_development():
    assert settings(dev_auth_enabled=True, app_env="development").dev_auth_active is True


def test_app_refuses_to_start_with_dev_auth_in_production(monkeypatch):
    import importlib

    import app.main as main_module

    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="DEV_AUTH_ENABLED"):
            importlib.reload(main_module)
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        importlib.reload(main_module)
