import pytest

from app.execution.sql_guard import SQLSafetyError, validate_read_only


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM sales LIMIT 100",
        "WITH totals AS (SELECT region, sum(amount) AS amount FROM sales GROUP BY region) "
        "SELECT * FROM totals LIMIT 100",
        "SELECT region FROM sales UNION SELECT region FROM targets LIMIT 10",
    ],
)
def test_allows_single_read_only_query_with_limit(sql):
    validate_read_only(sql, "postgres")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM sales",
        "SELECT * FROM sales LIMIT 501",
        "DELETE FROM sales",
        "SELECT * FROM sales LIMIT 10; DROP TABLE sales",
        "SELECT * INTO backup FROM sales LIMIT 10",
        "SELECT * FROM sales LIMIT 10 FOR UPDATE",
        "SELECT * FROM pg_catalog.pg_tables LIMIT 10",
        "SELECT pg_read_file('/etc/passwd') LIMIT 1",
        "SELECT * FROM read_csv_auto('secret.csv') LIMIT 10",
    ],
)
def test_rejects_unsafe_or_unbounded_sql(sql):
    with pytest.raises(SQLSafetyError):
        validate_read_only(sql, "postgres")
