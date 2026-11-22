"""PostgreSQL integration fixtures.

Each test session migrates a fresh, uniquely named schema and drops it afterwards, so the
real control-plane schema (``datagent``) is never read or modified by tests.
"""

import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.session import build_engine, get_db
from app.identity.dependencies import get_verifier
from app.identity.oidc import OIDCVerifier, StaticKeyProvider
from app.main import app
from tests.tokens import AUDIENCE, ISSUER, generate_rsa_key, make_token

BACKEND_DIR = Path(__file__).resolve().parents[2]
BOOTSTRAP_ADMIN = "bootstrap-admin"


def alembic_config(schema: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["schema"] = schema
    config.attributes["skip_logging_config"] = True
    return config


@pytest.fixture(scope="session")
def admin_engine() -> Iterator[Engine]:
    engine = build_engine(get_settings(), "public")
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        engine.dispose()
        pytest.skip(f"PostgreSQL unavailable ({type(exc).__name__}); integration tests not run")
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def make_schema(admin_engine: Engine) -> Iterator[Callable[[], str]]:
    created: list[str] = []

    def factory() -> str:
        schema = f"datagent_test_{uuid.uuid4().hex[:12]}"
        created.append(schema)
        return schema

    yield factory
    with admin_engine.begin() as connection:
        for schema in created:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


@pytest.fixture(scope="session")
def engine(make_schema: Callable[[], str]) -> Iterator[Engine]:
    schema = make_schema()
    command.upgrade(alembic_config(schema), "head")
    engine = build_engine(get_settings(), schema)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


@pytest.fixture(scope="session")
def signing_key():
    return generate_rsa_key()


@pytest.fixture
def client(engine: Engine, signing_key) -> Iterator[TestClient]:
    factory = sessionmaker(engine, expire_on_commit=False)

    def override_db() -> Iterator[Session]:
        with factory() as session:
            yield session

    verifier = OIDCVerifier(
        issuer=ISSUER, audience=AUDIENCE, key_provider=StaticKeyProvider(signing_key.public_key())
    )
    settings = get_settings().model_copy(
        update={
            "oidc_issuer": ISSUER,
            "oidc_audience": AUDIENCE,
            "oidc_bootstrap_admin_subjects": BOOTSTRAP_ADMIN,
        }
    )
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_verifier] = lambda: verifier
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def auth(signing_key) -> Callable[..., dict[str, str]]:
    def headers(subject: str, **claims) -> dict[str, str]:
        return {"Authorization": f"Bearer {make_token(signing_key, subject, **claims)}"}

    return headers


@pytest.fixture
def unique() -> Callable[[str], str]:
    return lambda prefix: f"{prefix}-{uuid.uuid4().hex[:10]}"
