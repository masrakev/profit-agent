"""SQLAlchemy Core table definitions used for query building.

The migrations in `backend/migrations` are the source of truth for constraints, row-level security
and grants. A test checks that tables, columns, types and nullability here match the migrated
database.
"""

from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Column,
    Computed,
    Date,
    DateTime,
    Identity,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

metadata = MetaData()


def _money(name: str, *, nullable: bool = False) -> Column[Any]:
    return Column(name, Numeric(18, 4), nullable=nullable)


def _currency(*, nullable: bool = False) -> Column[Any]:
    return Column("currency", CHAR(3), nullable=nullable)


def _ts(name: str) -> Column[Any]:
    return Column(name, DateTime(timezone=True), nullable=False)


def _store_id() -> Column[Any]:
    return Column("store_id", Uuid, nullable=False)


stores = Table(
    "stores",
    metadata,
    Column("store_id", Uuid, primary_key=True),
    Column("name", Text, nullable=False),
    _currency(),
    Column("timezone", Text, nullable=False),
    _ts("created_at"),
)

products = Table(
    "products",
    metadata,
    Column("id", Uuid, primary_key=True),
    _store_id(),
    Column("sku", Text, nullable=False),
    Column("name", Text, nullable=False),
    _money("price"),
    _money("unit_cost"),
    _money("unit_fee"),
    _currency(),
    Column("supplier_lead_time_days", Integer, nullable=True),
    _ts("created_at"),
)

orders = Table(
    "orders",
    metadata,
    Column("id", Uuid, primary_key=True),
    _store_id(),
    Column("external_id", Text, nullable=False),
    _ts("ordered_at"),
    Column("status", Text, nullable=False),
    _currency(),
    _money("shipping_amount"),
    _money("payment_fee_amount"),
)

order_lines = Table(
    "order_lines",
    metadata,
    Column("id", Uuid, primary_key=True),
    _store_id(),
    Column("order_id", Uuid, nullable=False),
    Column("product_id", Uuid, nullable=False),
    Column("quantity", Integer, nullable=False),
    _money("unit_price"),
    _money("discount_amount"),
    _money("tax_amount"),
    Column(
        "net_amount",
        Numeric(18, 4),
        Computed("unit_price * quantity - discount_amount", persisted=True),
    ),
    _money("unit_cost_at_sale"),
    _money("unit_fee_at_sale"),
    _money("payment_fee_alloc"),
    _currency(),
)

refunds = Table(
    "refunds",
    metadata,
    Column("id", Uuid, primary_key=True),
    _store_id(),
    Column("order_id", Uuid, nullable=False),
    Column("order_line_id", Uuid, nullable=False),
    _ts("refunded_at"),
    _money("amount"),
    Column("quantity", Integer, nullable=False),
    _currency(),
    Column("reason", Text, nullable=True),
)

inventory_snapshots = Table(
    "inventory_snapshots",
    metadata,
    Column("id", Uuid, primary_key=True),
    _store_id(),
    Column("product_id", Uuid, nullable=False),
    Column("snapshot_date", Date, nullable=False),
    Column("units_on_hand", Integer, nullable=False),
)

ad_campaigns = Table(
    "ad_campaigns",
    metadata,
    Column("id", Uuid, primary_key=True),
    _store_id(),
    Column("external_id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("platform", Text, nullable=False),
    Column("status", Text, nullable=False),
    _currency(),
    _money("daily_budget"),
)

ad_campaign_products = Table(
    "ad_campaign_products",
    metadata,
    Column("store_id", Uuid, primary_key=True),
    Column("campaign_id", Uuid, primary_key=True),
    Column("product_id", Uuid, primary_key=True),
)

ad_metrics_daily = Table(
    "ad_metrics_daily",
    metadata,
    Column("id", Uuid, primary_key=True),
    _store_id(),
    Column("campaign_id", Uuid, nullable=False),
    Column("metric_date", Date, nullable=False),
    _money("spend"),
    _currency(),
    Column("impressions", BigInteger, nullable=False),
    Column("clicks", BigInteger, nullable=False),
    Column("attributed_purchases", Integer, nullable=False),
    _money("attributed_revenue"),
)

cost_items = Table(
    "cost_items",
    metadata,
    Column("id", Uuid, primary_key=True),
    _store_id(),
    Column("name", Text, nullable=False),
    Column("category", Text, nullable=False),
    Column("kind", Text, nullable=False),
    _money("amount"),
    _currency(),
    Column("period_start", Date, nullable=False),
    Column("period_end", Date, nullable=False),
)

facts = Table(
    "facts",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    _store_id(),
    Column("formula_id", Text, nullable=False),
    Column("formula_version", Integer, nullable=False),
    Column("kind", Text, nullable=False),
    Column("scope_kind", Text, nullable=False),
    Column("scope_id", Uuid, nullable=True),
    _ts("period_start"),
    _ts("period_end"),
    Column("status", Text, nullable=False),
    Column("value", Numeric, nullable=True),
    Column("p10", Numeric, nullable=True),
    Column("p50", Numeric, nullable=True),
    Column("p90", Numeric, nullable=True),
    Column("method", Text, nullable=True),
    Column("unit", Text, nullable=False),
    _currency(nullable=True),
    Column("undefined_reason", Text, nullable=True),
    Column("inputs_hash", CHAR(64), nullable=False),
    Column("fact_hash", CHAR(64), nullable=False),
    _ts("computed_at"),
)

fact_lineage = Table(
    "fact_lineage",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    _store_id(),
    Column("fact_id", BigInteger, nullable=False),
    Column("role", Text, nullable=False),
    Column("source_table", Text, nullable=True),
    Column("source_ids", ARRAY(Uuid), nullable=True),
    Column("parent_fact_id", BigInteger, nullable=True),
)

audit_log = Table(
    "audit_log",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    _store_id(),
    Column("seq", BigInteger, nullable=False),
    _ts("occurred_at"),
    Column("actor", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("prev_hash", CHAR(64), nullable=False),
    Column("entry_hash", CHAR(64), nullable=False),
)
