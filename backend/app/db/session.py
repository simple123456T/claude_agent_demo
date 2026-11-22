import re
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import SQL_IDENTIFIER_PATTERN, Settings, get_settings


def build_engine(settings: Settings, schema: str | None = None) -> Engine:
    """Create an engine whose sessions resolve control-plane tables in one schema only."""

    schema = schema or settings.control_plane_schema
    if not re.fullmatch(SQL_IDENTIFIER_PATTERN, schema):
        raise ValueError("Invalid control-plane schema name")
    return create_engine(
        settings.sqlalchemy_database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_timeout=10,
        connect_args={
            "connect_timeout": settings.db_connect_timeout,
            "options": f"-c search_path={schema}",
        },
    )


@lru_cache
def get_engine() -> Engine:
    return build_engine(get_settings())


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with get_session_factory()() as session:
        yield session
