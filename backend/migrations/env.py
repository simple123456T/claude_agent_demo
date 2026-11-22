import re
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, create_engine, text

import app.db.models  # noqa: F401  (registers tables on Base.metadata)
from app.core.config import SQL_IDENTIFIER_PATTERN, get_settings
from app.db.base import Base

config = context.config
if config.config_file_name is not None and not config.attributes.get("skip_logging_config"):
    fileConfig(config.config_file_name)

settings = get_settings()
schema = (
    config.attributes.get("schema")
    or context.get_x_argument(as_dictionary=True).get("schema")
    or settings.control_plane_schema
)
if not re.fullmatch(SQL_IDENTIFIER_PATTERN, schema):
    raise ValueError(f"Invalid control-plane schema name: {schema!r}")


def _run(connection: Connection) -> None:
    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    connection.execute(text(f'SET search_path TO "{schema}"'))
    connection.commit()
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        version_table_schema=schema,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(
        settings.sqlalchemy_database_url,
        connect_args={"connect_timeout": settings.db_connect_timeout},
    )
    try:
        with engine.connect() as connection:
            _run(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline SQL generation is not supported; run migrations online.")
run_migrations_online()
