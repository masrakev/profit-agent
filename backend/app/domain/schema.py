"""SQLAlchemy Core table definitions used for query building.

The migrations in `backend/migrations` are the source of truth for constraints, row-level security
and grants. A test checks that tables, columns, types and nullability here match the migrated
database.
"""

from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    Column,
    Computed,
    Date,
    DateTime,
    Identity,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    SmallInteger,
    Table,
    Text,
    Time,
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
    Column("synthetic", Boolean, nullable=False),
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
    Column("baseline_start", DateTime(timezone=True), nullable=True),
    Column("baseline_end", DateTime(timezone=True), nullable=True),
    Column("status", Text, nullable=False),
    Column("value", Numeric, nullable=True),
    Column("p10", Numeric, nullable=True),
    Column("p50", Numeric, nullable=True),
    Column("p90", Numeric, nullable=True),
    Column("method", Text, nullable=True),
    Column("significant", Boolean, nullable=True),
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

store_settings = Table(
    "store_settings",
    metadata,
    Column("store_id", Uuid, primary_key=True),
    Column("timezone", Text, nullable=False),
    _currency(),
    Column("daily_brief_enabled", Boolean, nullable=False),
    Column("daily_brief_at", Time, nullable=False),
    Column("daily_brief_weekdays", ARRAY(SmallInteger), nullable=False),
    Column("weekly_report_enabled", Boolean, nullable=False),
    Column("weekly_report_weekday", SmallInteger, nullable=False),
    Column("weekly_report_at", Time, nullable=False),
    Column("monthly_review_enabled", Boolean, nullable=False),
    Column("monthly_review_day", SmallInteger, nullable=False),
    Column("monthly_review_at", Time, nullable=False),
    Column("alert_channels", ARRAY(Text), nullable=False),
    Column("quiet_hours_start", Time, nullable=False),
    Column("quiet_hours_end", Time, nullable=False),
    Column("alert_budget_per_day", Integer, nullable=False),
    _money("materiality_absolute"),
    Column("materiality_relative", Numeric(9, 6), nullable=False),
    Column("detail_level", Text, nullable=False),
    Column("autonomy", JSONB, nullable=False),
    Column("max_budget_change_ratio", Numeric(9, 6), nullable=False),
    Column("max_budget_changes_per_day", Integer, nullable=False),
    Column("language", Text, nullable=False),
    _ts("updated_at"),
    Column("notification_email", Text, nullable=True),
)

incidents = Table(
    "incidents",
    metadata,
    _store_id(),
    Column("incident_id", Text, primary_key=True),
    Column("as_of", Date, nullable=False),
    Column("thresholds_version", Integer, nullable=False),
    Column("category", Text, nullable=False),
    Column("alert", Text, nullable=False),
    Column("first_seen", Date, nullable=False),
    Column("last_seen", Date, nullable=False),
    Column("payload", JSONB, nullable=False),
    _ts("updated_at"),
)

investigations = Table(
    "investigations",
    metadata,
    Column("investigation_id", Uuid, primary_key=True),
    _store_id(),
    Column("incident_id", Text, nullable=False),
    Column("cache_key", CHAR(64), nullable=False),
    Column("status", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("prompt_version", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    _ts("created_at"),
)

decisions = Table(
    "decisions",
    metadata,
    Column("decision_id", Uuid, primary_key=True),
    _store_id(),
    Column("source", Text, nullable=False),
    Column("incident_id", Text, nullable=True),
    Column("cause", Text, nullable=False),
    Column("entity", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("recommended_option_id", Text, nullable=False),
    Column("approved_option_id", Text, nullable=True),
    Column("horizon_days", Integer, nullable=False),
    _money("floor"),
    _currency(),
    Column("as_of", Date, nullable=False),
    _ts("expires_at"),
    Column("payload", JSONB, nullable=False),
    _ts("created_at"),
    _ts("updated_at"),
)

decision_options = Table(
    "decision_options",
    metadata,
    Column("store_id", Uuid, primary_key=True),
    Column("decision_id", Uuid, primary_key=True),
    Column("option_id", Text, primary_key=True),
    Column("rank", SmallInteger, nullable=False),
    Column("kind", Text, nullable=False),
    Column("action_family", Text, nullable=False),
    Column("entity", Text, nullable=False),
    Column("actions", JSONB, nullable=False),
    Column("executable", Boolean, nullable=False),
    Column("reversibility", Text, nullable=False),
    Column("impact_fact_id", BigInteger, nullable=True),
    _money("p10", nullable=True),
    _money("p50", nullable=True),
    _money("p90", nullable=True),
    Column("risks", JSONB, nullable=False),
    Column("invalidated_if", JSONB, nullable=False),
    Column("flags", JSONB, nullable=False),
)

approvals = Table(
    "approvals",
    metadata,
    Column("approval_id", Uuid, primary_key=True),
    _store_id(),
    Column("decision_id", Uuid, nullable=False),
    Column("option_id", Text, nullable=True),
    Column("verdict", Text, nullable=False),
    Column("channel", Text, nullable=False),
    Column("actor", Text, nullable=False),
    _ts("created_at"),
)

approval_links = Table(
    "approval_links",
    metadata,
    Column("link_id", Uuid, primary_key=True),
    _store_id(),
    Column("decision_id", Uuid, nullable=False),
    Column("option_id", Text, nullable=False),
    Column("verdict", Text, nullable=False),
    _ts("expires_at"),
    Column("used_at", DateTime(timezone=True), nullable=True),
    _ts("created_at"),
)

actions = Table(
    "actions",
    metadata,
    Column("action_id", Uuid, primary_key=True),
    _store_id(),
    Column("decision_id", Uuid, nullable=False),
    Column("option_id", Text, nullable=False),
    Column("seq", SmallInteger, nullable=False),
    Column("kind", Text, nullable=False),
    Column("campaign_id", Uuid, nullable=False),
    Column("provider", Text, nullable=False),
    Column("params", JSONB, nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("rollback_of", Uuid, nullable=True),
    Column("attempts", Integer, nullable=False),
    Column("last_error", Text, nullable=True),
    Column("before_state", JSONB, nullable=True),
    Column("after_state", JSONB, nullable=True),
    _ts("created_at"),
    Column("executed_at", DateTime(timezone=True), nullable=True),
)

outbox = Table(
    "outbox",
    metadata,
    Column("outbox_id", BigInteger, Identity(always=True), primary_key=True),
    _store_id(),
    Column("action_id", Uuid, nullable=False),
    Column("status", Text, nullable=False),
    Column("attempts", Integer, nullable=False),
    _ts("available_at"),
    Column("last_error", Text, nullable=True),
    _ts("created_at"),
    Column("processed_at", DateTime(timezone=True), nullable=True),
)

store_controls = Table(
    "store_controls",
    metadata,
    Column("store_id", Uuid, primary_key=True),
    Column("kill_switch", Boolean, nullable=False),
    Column("reason", Text, nullable=True),
    Column("updated_by", Text, nullable=False),
    _ts("updated_at"),
)

outcomes = Table(
    "outcomes",
    metadata,
    Column("outcome_id", Uuid, primary_key=True),
    _store_id(),
    Column("decision_id", Uuid, nullable=False),
    Column("action_id", Uuid, nullable=False),
    Column("status", Text, nullable=False),
    Column("method", Text, nullable=False),
    Column("window_start", Date, nullable=False),
    Column("window_end", Date, nullable=False),
    Column("effect_fact_id", BigInteger, nullable=True),
    Column("payload", JSONB, nullable=False),
    _ts("created_at"),
)

simulator_stores = Table(
    "simulator_stores",
    metadata,
    Column("store_id", Uuid, primary_key=True),
    Column("suite", Text, nullable=False),
    Column("scenario_id", Text, nullable=False),
    Column("current_day", Integer, nullable=False),
    Column("events", JSONB, nullable=False),
    _ts("updated_at"),
)

briefings = Table(
    "briefings",
    metadata,
    Column("briefing_id", Uuid, primary_key=True),
    _store_id(),
    Column("kind", Text, nullable=False),
    Column("local_date", Date, nullable=False),
    Column("period_start", Date, nullable=False),
    Column("period_end", Date, nullable=False),
    Column("status", Text, nullable=False),
    Column("content", JSONB, nullable=False),
    Column("narrative", Text, nullable=True),
    Column("fact_ids", ARRAY(BigInteger), nullable=False),
    Column("prompt_version", Text, nullable=True),
    Column("model", Text, nullable=True),
    Column("attempts", Integer, nullable=False),
    Column("fallback_reason", Text, nullable=True),
    Column("input_tokens", Integer, nullable=False),
    Column("output_tokens", Integer, nullable=False),
    Column("cost_usd", Numeric(12, 6), nullable=False),
    _ts("created_at"),
)

alerts = Table(
    "alerts",
    metadata,
    Column("alert_id", Uuid, primary_key=True),
    _store_id(),
    Column("incident_id", Text, nullable=False),
    Column("level", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("reason", Text, nullable=True),
    Column("decision_id", Uuid, nullable=True),
    Column("local_date", Date, nullable=False),
    _ts("deliver_at"),
    Column("briefing_id", Uuid, nullable=True),
    _ts("created_at"),
)

deliveries = Table(
    "deliveries",
    metadata,
    Column("delivery_id", Uuid, primary_key=True),
    _store_id(),
    Column("subject", Text, nullable=False),
    Column("subject_id", Text, nullable=False),
    Column("channel", Text, nullable=False),
    Column("recipient", Text, nullable=True),
    Column("status", Text, nullable=False),
    Column("attempts", Integer, nullable=False),
    _ts("available_at"),
    Column("provider", Text, nullable=True),
    Column("provider_message_id", Text, nullable=True),
    Column("last_error", Text, nullable=True),
    _ts("created_at"),
    Column("sent_at", DateTime(timezone=True), nullable=True),
)

investigation_steps = Table(
    "investigation_steps",
    metadata,
    Column("store_id", Uuid, primary_key=True),
    Column("investigation_id", Uuid, primary_key=True),
    Column("seq", Integer, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("name", Text, nullable=True),
    Column("detail", JSONB, nullable=False),
    _ts("created_at"),
)

store_connections = Table(
    "store_connections",
    metadata,
    Column("store_id", Uuid, primary_key=True),
    Column("provider", Text, primary_key=True),
    Column("account_id", Text, nullable=False),
    Column("key_id", Text, nullable=False),
    Column("wrapped_key", LargeBinary, nullable=False),
    Column("key_nonce", LargeBinary, nullable=False),
    Column("ciphertext", LargeBinary, nullable=False),
    Column("nonce", LargeBinary, nullable=False),
    _ts("created_at"),
    _ts("updated_at"),
)
