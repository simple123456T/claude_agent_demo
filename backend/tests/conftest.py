import pytest

from app.core.config import Settings
from app.policy.models import AccessPolicy
from app.semantic.registry import (
    Aggregation,
    ColumnDefinition,
    DatasetDefinition,
    MetricDefinition,
)


@pytest.fixture
def sales_dataset() -> DatasetDefinition:
    columns = {
        name: ColumnDefinition(name=name)
        for name in ["region", "month", "product", "amount", "customer_id"]
    }
    return DatasetDefinition(
        name="sales",
        version="2026.11.1",
        table="fact_sales",
        schema_name="analytics",
        columns=columns,
        dimensions={"region": "region", "month": "month", "product": "product"},
        metrics={
            "revenue": MetricDefinition(
                name="revenue", aggregation=Aggregation.SUM, column="amount"
            ),
            "orders": MetricDefinition(name="orders", aggregation=Aggregation.COUNT),
            "customers": MetricDefinition(
                name="customers",
                aggregation=Aggregation.COUNT_DISTINCT,
                column="customer_id",
            ),
        },
    )


@pytest.fixture
def sales_policy() -> AccessPolicy:
    return AccessPolicy(
        workspace_id="default",
        allowed_columns=frozenset({"region", "month", "product", "amount", "customer_id"}),
        row_filters=[
            {"field": "region", "operator": "ne", "values": ["INTERNAL_TEST"]}
        ],
    )


@pytest.fixture(autouse=True)
def _hermetic_settings_env(monkeypatch):
    """Keep tests independent of whatever the developer put in their local .env.

    Importing pymilvus runs ``load_dotenv()``, which finds the project's .env (the virtualenv
    lives inside the repo) and copies every value into ``os.environ``. Without this, a test
    asserting a default - such as dev sign-in being off - would pass or fail depending on
    the developer's machine.
    """

    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
