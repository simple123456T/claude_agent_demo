from fastapi.testclient import TestClient

from app.api.routes import health
from app.main import app

client = TestClient(app)


def test_liveness_does_not_depend_on_infrastructure():
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_all_services(monkeypatch):
    monkeypatch.setattr(health, "probe_postgres", lambda: None)
    monkeypatch.setattr(health, "probe_redis", lambda: None)
    monkeypatch.setattr(health, "probe_milvus", lambda: None)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert set(response.json()["services"]) == {"postgresql", "redis", "milvus"}


def test_required_service_failure_returns_503(monkeypatch):
    monkeypatch.setattr(health, "probe_postgres", lambda: (_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setattr(health, "probe_redis", lambda: None)
    monkeypatch.setattr(health, "probe_milvus", lambda: None)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["services"]["postgresql"]["error"] == "TimeoutError"


def test_optional_milvus_failure_degrades_but_does_not_block_readiness(monkeypatch):
    monkeypatch.setattr(health, "probe_postgres", lambda: None)
    monkeypatch.setattr(health, "probe_redis", lambda: None)
    monkeypatch.setattr(health, "probe_milvus", lambda: (_ for _ in ()).throw(ConnectionError()))

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
