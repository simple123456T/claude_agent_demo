"""Seed the local demo: sales data plus a demo workspace with three dev identities.

Run with ``python -m app.demo.seed``. Safe to re-run: the demo table is rebuilt from scratch
and workspace membership is upserted. Only touches the demo schema and the demo workspace.
"""

import random
import re
from datetime import date
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.audit.service import record_event
from app.core.config import SQL_IDENTIFIER_PATTERN, get_settings
from app.db.models import User, Workspace, WorkspaceMember
from app.db.session import get_engine
from app.demo.dataset import DEMO_SCHEMA, DEMO_TABLE
from app.identity.dev import DEV_IDENTITIES, DEV_ISSUER
from app.identity.service import ensure_user
from app.workspaces.permissions import WorkspaceRole

DEMO_WORKSPACE_SLUG = "demo"
FIRST_MONTH = (2025, 1)

REGIONS = [("华东", 30), ("华南", 22), ("华北", 20), ("西南", 15), ("东北", 8)]
# (product, category, unit price, popularity weight)
PRODUCTS = [
    ("笔记本电脑", "电脑整机", 5800, 8),
    ("台式主机", "电脑整机", 4200, 5),
    ("显示器", "外设", 1600, 14),
    ("机械键盘", "外设", 420, 18),
    ("无线鼠标", "外设", 160, 25),
    ("路由器", "网络设备", 380, 16),
    ("交换机", "网络设备", 1500, 6),
]
DEMO_MEMBERS = {
    "dev-admin": WorkspaceRole.WORKSPACE_ADMIN,
    "dev-analyst": WorkspaceRole.ANALYST,
    "dev-viewer": WorkspaceRole.VIEWER,
}


def months_until(today: date) -> list[tuple[int, int]]:
    """Every month from 2025-01 up to (and including) the last complete month."""

    year, month = FIRST_MONTH
    last_year, last_month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    months = []
    while (year, month) <= (last_year, last_month):
        months.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def generate_rows(today: date | None = None, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    months = months_until(today or date.today())
    region_names = [name for name, _ in REGIONS]
    region_weights = [weight for _, weight in REGIONS]
    product_weights = [item[3] for item in PRODUCTS]
    rows: list[dict] = []
    order_id = 100000
    for index, (year, month) in enumerate(months):
        growth = 1 + 0.025 * index
        seasonality = 1.25 if month in (3, 9, 11, 12) else 1.0
        for _ in range(int(210 * growth * seasonality)):
            region = rng.choices(region_names, region_weights)[0]
            product, category, price, _ = rng.choices(PRODUCTS, product_weights)[0]
            quantity = rng.choices([1, 2, 3, 4, 5], [55, 22, 12, 7, 4])[0]
            amount = Decimal(str(round(price * quantity * rng.uniform(0.88, 1.08), 2)))
            order_id += 1
            rows.append(
                {
                    "order_id": order_id,
                    "order_month": f"{year:04d}-{month:02d}",
                    "region": region,
                    "product": product,
                    "category": category,
                    "customer_id": f"C{rng.randint(1, 420):04d}",
                    "amount": amount,
                    "quantity": quantity,
                }
            )
    return rows


def seed_demo_data(engine: Engine, schema: str = DEMO_SCHEMA, today: date | None = None) -> int:
    """Rebuild the demo table in ``schema`` and return the number of rows inserted."""

    if not re.fullmatch(SQL_IDENTIFIER_PATTERN, schema):
        raise ValueError("Invalid schema name")
    rows = generate_rows(today)
    table = f'"{schema}"."{DEMO_TABLE}"'
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        connection.execute(text(f"DROP TABLE IF EXISTS {table}"))
        connection.execute(
            text(
                f"""
                CREATE TABLE {table} (
                    order_id    bigint PRIMARY KEY,
                    order_month text NOT NULL,
                    region      text NOT NULL,
                    product     text NOT NULL,
                    category    text NOT NULL,
                    customer_id text NOT NULL,
                    amount      numeric(14, 2) NOT NULL,
                    quantity    integer NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                f"""
                INSERT INTO {table}
                    (order_id, order_month, region, product, category, customer_id, amount, quantity)
                VALUES
                    (:order_id, :order_month, :region, :product, :category, :customer_id,
                     :amount, :quantity)
                """
            ),
            rows,
        )
    return len(rows)


def seed_demo_workspace(db: Session) -> Workspace:
    """Create the demo workspace and the dev identities' memberships (idempotent)."""

    labels = {subject: label for subject, label, _ in DEV_IDENTITIES}
    users: dict[str, User] = {}
    for subject in DEMO_MEMBERS:
        user, _ = ensure_user(db, DEV_ISSUER, subject)
        user.display_name = user.display_name or f"开发{labels[subject]}"
        users[subject] = user
    users["dev-admin"].is_org_admin = True

    workspace = db.execute(
        select(Workspace).where(Workspace.slug == DEMO_WORKSPACE_SLUG)
    ).scalar_one_or_none()
    if workspace is None:
        workspace = Workspace(
            slug=DEMO_WORKSPACE_SLUG, name="演示工作区", created_by=users["dev-admin"].id
        )
        db.add(workspace)
        db.flush()

    for subject, role in DEMO_MEMBERS.items():
        member = db.get(WorkspaceMember, (workspace.id, users[subject].id))
        if member is None:
            db.add(
                WorkspaceMember(
                    workspace_id=workspace.id, user_id=users[subject].id, role=role.value
                )
            )
        else:
            member.role = role.value

    record_event(
        db,
        action="demo.seed",
        actor_user_id=users["dev-admin"].id,
        actor_subject="dev-admin",
        workspace_id=workspace.id,
        target_type="workspace",
        target_id=str(workspace.id),
    )
    db.commit()
    return workspace


def main() -> None:
    settings = get_settings()
    if settings.is_production:
        raise SystemExit("Refusing to seed demo data when APP_ENV=production")
    engine = get_engine()
    count = seed_demo_data(engine, settings.demo_schema)
    with Session(engine, expire_on_commit=False) as db:
        workspace = seed_demo_workspace(db)
    print(f"Seeded {count} demo orders into schema '{settings.demo_schema}'.")
    print(f"Demo workspace '{workspace.slug}' ready; dev identities: {', '.join(DEMO_MEMBERS)}.")


if __name__ == "__main__":
    main()
