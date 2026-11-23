import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
from sqlalchemy.engine import Engine

from app.execution.sql_guard import validate_read_only


class QueryTimeout(Exception):
    """The statement exceeded its time budget and was cancelled by the database."""


class QueryExecutionError(Exception):
    """The database rejected or failed the statement."""


@dataclass(frozen=True)
class RawResult:
    rows: list[list[Any]]
    elapsed_ms: int


def run_read_only(
    engine: Engine,
    sql: str,
    *,
    dialect: str = "postgres",
    max_rows: int = 500,
    timeout_ms: int = 15000,
) -> RawResult:
    """Execute one already-compiled query inside a read-only, time-limited transaction.

    The independent AST check runs again here so no caller can reach the database with
    SQL that skipped validation.

    Executes through the raw DBAPI cursor *without parameters*: compiled SQL carries its
    literals inline, and going through SQLAlchemy's ``text()`` would misread ``:name`` and
    ``%`` inside user-supplied filter values as placeholders.
    """

    validate_read_only(sql, dialect, max_rows=max_rows)
    started = time.perf_counter()
    connection = engine.raw_connection()
    try:
        cursor = connection.cursor()
        try:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
            cursor.execute(sql)
            rows = [list(row) for row in cursor.fetchall()]
        finally:
            cursor.close()
    except psycopg.errors.QueryCanceled as exc:
        raise QueryTimeout() from exc
    except psycopg.Error as exc:
        raise QueryExecutionError(type(exc).__name__) from exc
    finally:
        connection.close()  # returns to the pool, which rolls the transaction back
    return RawResult(rows=rows, elapsed_ms=round((time.perf_counter() - started) * 1000))


def to_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, float):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)
