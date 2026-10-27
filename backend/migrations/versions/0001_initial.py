"""Initial schema: tenant tables, facts, lineage, hash-chained audit log, row-level security.

Revision ID: 0001
Revises:
Create Date: 2026-10-27
"""

from collections.abc import Sequence

from alembic import op

from app.config import get_settings

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables protected by row-level security, in creation order.
TENANT_TABLES = (
    "stores",
    "products",
    "orders",
    "order_lines",
    "refunds",
    "inventory_snapshots",
    "ad_campaigns",
    "ad_campaign_products",
    "ad_metrics_daily",
    "cost_items",
    "facts",
    "fact_lineage",
    "audit_log",
)

# Privileges of the application role. Facts, lineage and the audit log are append-only.
APP_GRANTS = {
    "stores": "SELECT, INSERT, UPDATE",
    "products": "SELECT, INSERT, UPDATE, DELETE",
    "orders": "SELECT, INSERT, UPDATE, DELETE",
    "order_lines": "SELECT, INSERT, UPDATE, DELETE",
    "refunds": "SELECT, INSERT, UPDATE, DELETE",
    "inventory_snapshots": "SELECT, INSERT, UPDATE, DELETE",
    "ad_campaigns": "SELECT, INSERT, UPDATE, DELETE",
    "ad_campaign_products": "SELECT, INSERT, UPDATE, DELETE",
    "ad_metrics_daily": "SELECT, INSERT, UPDATE, DELETE",
    "cost_items": "SELECT, INSERT, UPDATE, DELETE",
    "facts": "SELECT, INSERT",
    "fact_lineage": "SELECT, INSERT",
    "audit_log": "SELECT, INSERT",
}

SCHEMA = """
CREATE TABLE stores (
    store_id    uuid PRIMARY KEY,
    name        text NOT NULL,
    currency    char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    timezone    text NOT NULL DEFAULT 'UTC',
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE products (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id                 uuid NOT NULL REFERENCES stores (store_id),
    sku                      text NOT NULL,
    name                     text NOT NULL,
    price                    numeric(18, 4) NOT NULL CHECK (price >= 0),
    unit_cost                numeric(18, 4) NOT NULL CHECK (unit_cost >= 0),
    unit_fee                 numeric(18, 4) NOT NULL CHECK (unit_fee >= 0),
    currency                 char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    supplier_lead_time_days  integer CHECK (supplier_lead_time_days >= 0),
    created_at               timestamptz NOT NULL DEFAULT now(),
    UNIQUE (store_id, id),
    UNIQUE (store_id, sku)
);

CREATE TABLE orders (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id            uuid NOT NULL REFERENCES stores (store_id),
    external_id         text NOT NULL,
    ordered_at          timestamptz NOT NULL,
    status              text NOT NULL CHECK (status IN ('paid', 'cancelled')),
    currency            char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    shipping_amount     numeric(18, 4) NOT NULL DEFAULT 0 CHECK (shipping_amount >= 0),
    payment_fee_amount  numeric(18, 4) NOT NULL DEFAULT 0 CHECK (payment_fee_amount >= 0),
    UNIQUE (store_id, id),
    UNIQUE (store_id, external_id)
);
CREATE INDEX ix_orders_store_ordered_at ON orders (store_id, ordered_at);

CREATE TABLE order_lines (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id           uuid NOT NULL,
    order_id           uuid NOT NULL,
    product_id         uuid NOT NULL,
    quantity           integer NOT NULL CHECK (quantity > 0),
    unit_price         numeric(18, 4) NOT NULL CHECK (unit_price >= 0),
    discount_amount    numeric(18, 4) NOT NULL DEFAULT 0 CHECK (discount_amount >= 0),
    tax_amount         numeric(18, 4) NOT NULL DEFAULT 0 CHECK (tax_amount >= 0),
    net_amount         numeric(18, 4)
                       GENERATED ALWAYS AS (unit_price * quantity - discount_amount) STORED,
    unit_cost_at_sale  numeric(18, 4) NOT NULL CHECK (unit_cost_at_sale >= 0),
    unit_fee_at_sale   numeric(18, 4) NOT NULL CHECK (unit_fee_at_sale >= 0),
    payment_fee_alloc  numeric(18, 4) NOT NULL DEFAULT 0 CHECK (payment_fee_alloc >= 0),
    currency           char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    CHECK (discount_amount <= unit_price * quantity),
    UNIQUE (store_id, id),
    UNIQUE (store_id, order_id, id),
    FOREIGN KEY (store_id, order_id) REFERENCES orders (store_id, id),
    FOREIGN KEY (store_id, product_id) REFERENCES products (store_id, id)
);
CREATE INDEX ix_order_lines_store_order ON order_lines (store_id, order_id);
CREATE INDEX ix_order_lines_store_product ON order_lines (store_id, product_id);

CREATE TABLE refunds (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id       uuid NOT NULL,
    order_id       uuid NOT NULL,
    order_line_id  uuid NOT NULL,
    refunded_at    timestamptz NOT NULL,
    amount         numeric(18, 4) NOT NULL CHECK (amount > 0),
    quantity       integer NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    currency       char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    reason         text,
    UNIQUE (store_id, id),
    FOREIGN KEY (store_id, order_id, order_line_id)
        REFERENCES order_lines (store_id, order_id, id)
);
CREATE INDEX ix_refunds_store_refunded_at ON refunds (store_id, refunded_at);

CREATE TABLE inventory_snapshots (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id       uuid NOT NULL,
    product_id     uuid NOT NULL,
    snapshot_date  date NOT NULL,
    units_on_hand  integer NOT NULL CHECK (units_on_hand >= 0),
    UNIQUE (store_id, id),
    UNIQUE (store_id, product_id, snapshot_date),
    FOREIGN KEY (store_id, product_id) REFERENCES products (store_id, id)
);

CREATE TABLE ad_campaigns (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id      uuid NOT NULL REFERENCES stores (store_id),
    external_id   text NOT NULL,
    name          text NOT NULL,
    platform      text NOT NULL,
    status        text NOT NULL CHECK (status IN ('active', 'paused', 'archived')),
    currency      char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    daily_budget  numeric(18, 4) NOT NULL CHECK (daily_budget >= 0),
    UNIQUE (store_id, id),
    UNIQUE (store_id, external_id)
);

CREATE TABLE ad_campaign_products (
    store_id     uuid NOT NULL,
    campaign_id  uuid NOT NULL,
    product_id   uuid NOT NULL,
    PRIMARY KEY (store_id, campaign_id, product_id),
    FOREIGN KEY (store_id, campaign_id) REFERENCES ad_campaigns (store_id, id),
    FOREIGN KEY (store_id, product_id) REFERENCES products (store_id, id)
);

CREATE TABLE ad_metrics_daily (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id              uuid NOT NULL,
    campaign_id           uuid NOT NULL,
    metric_date           date NOT NULL,
    spend                 numeric(18, 4) NOT NULL CHECK (spend >= 0),
    currency              char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    impressions           bigint NOT NULL DEFAULT 0 CHECK (impressions >= 0),
    clicks                bigint NOT NULL DEFAULT 0 CHECK (clicks >= 0),
    attributed_purchases  integer NOT NULL DEFAULT 0 CHECK (attributed_purchases >= 0),
    attributed_revenue    numeric(18, 4) NOT NULL DEFAULT 0 CHECK (attributed_revenue >= 0),
    UNIQUE (store_id, id),
    UNIQUE (store_id, campaign_id, metric_date),
    FOREIGN KEY (store_id, campaign_id) REFERENCES ad_campaigns (store_id, id)
);

CREATE TABLE cost_items (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id      uuid NOT NULL REFERENCES stores (store_id),
    name          text NOT NULL,
    category      text NOT NULL,
    kind          text NOT NULL CHECK (kind IN ('fixed')),
    amount        numeric(18, 4) NOT NULL CHECK (amount >= 0),
    currency      char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    period_start  date NOT NULL,
    period_end    date NOT NULL,
    CHECK (period_end > period_start),
    UNIQUE (store_id, id)
);

CREATE TABLE facts (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    store_id          uuid NOT NULL REFERENCES stores (store_id),
    formula_id        text NOT NULL,
    formula_version   integer NOT NULL CHECK (formula_version >= 1),
    kind              text NOT NULL CHECK (kind IN ('exact', 'estimate')),
    scope_kind        text NOT NULL CHECK (scope_kind IN ('store', 'product', 'campaign')),
    scope_id          uuid,
    period_start      timestamptz NOT NULL,
    period_end        timestamptz NOT NULL,
    status            text NOT NULL CHECK (status IN ('defined', 'undefined')),
    value             numeric,
    p10               numeric,
    p50               numeric,
    p90               numeric,
    method            text,
    unit              text NOT NULL CHECK (unit IN ('money', 'count', 'ratio', 'days')),
    currency          char(3) CHECK (currency ~ '^[A-Z]{3}$'),
    undefined_reason  text,
    inputs_hash       char(64) NOT NULL CHECK (inputs_hash ~ '^[0-9a-f]{64}$'),
    fact_hash         char(64) NOT NULL CHECK (fact_hash ~ '^[0-9a-f]{64}$'),
    computed_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (period_end > period_start),
    CHECK ((scope_kind = 'store') = (scope_id IS NULL)),
    CHECK ((unit = 'money') = (currency IS NOT NULL)),
    CHECK (
        (status = 'defined' AND value IS NOT NULL AND undefined_reason IS NULL)
        OR (status = 'undefined' AND value IS NULL AND undefined_reason IS NOT NULL)
    ),
    CHECK (
        kind = 'exact' OR status = 'undefined'
        OR (p10 IS NOT NULL AND p50 IS NOT NULL AND p90 IS NOT NULL AND method IS NOT NULL)
    ),
    UNIQUE (store_id, id),
    UNIQUE (store_id, fact_hash)
);
CREATE INDEX ix_facts_lookup ON facts (store_id, formula_id, scope_kind, scope_id, period_start);

-- One row per parent fact, or one row per source table holding every contributing row id.
CREATE TABLE fact_lineage (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    store_id        uuid NOT NULL,
    fact_id         bigint NOT NULL,
    role            text NOT NULL,
    source_table    text,
    source_ids      uuid[],
    parent_fact_id  bigint,
    CHECK (
        (source_table IS NOT NULL AND source_ids IS NOT NULL AND parent_fact_id IS NULL)
        OR (source_table IS NULL AND source_ids IS NULL AND parent_fact_id IS NOT NULL)
    ),
    FOREIGN KEY (store_id, fact_id) REFERENCES facts (store_id, id),
    FOREIGN KEY (store_id, parent_fact_id) REFERENCES facts (store_id, id)
);
CREATE INDEX ix_fact_lineage_fact ON fact_lineage (store_id, fact_id);

CREATE TABLE audit_log (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    store_id     uuid NOT NULL REFERENCES stores (store_id),
    seq          bigint NOT NULL CHECK (seq >= 1),
    occurred_at  timestamptz NOT NULL,
    actor        text NOT NULL,
    action       text NOT NULL,
    payload      jsonb NOT NULL,
    prev_hash    char(64) NOT NULL CHECK (prev_hash ~ '^[0-9a-f]{64}$'),
    entry_hash   char(64) NOT NULL CHECK (entry_hash ~ '^[0-9a-f]{64}$'),
    UNIQUE (store_id, seq),
    UNIQUE (store_id, entry_hash)
);
"""

# Rows are visible and writable only when their store_id matches the transaction's tenant.
# NULLIF guards against an empty setting, which would otherwise fail the uuid cast.
TENANT_PREDICATE = "store_id = NULLIF(current_setting('app.store_id', true), '')::uuid"


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    settings = get_settings()
    role = settings.app_db_role
    if not role.isidentifier():
        raise ValueError(f"invalid role name {role!r}")
    password = _quote_literal(settings.app_db_password)

    op.execute(SCHEMA)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                CREATE ROLE {role} LOGIN PASSWORD {password}
                    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"ALTER ROLE {role} NOSUPERUSER NOBYPASSRLS")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
        )
        op.execute(f"GRANT {APP_GRANTS[table]} ON {table} TO {role}")

    # Planner statistics describe store_id's distribution. Right after a large store is loaded
    # they still say "no such store", the planner estimates one row and picks nested loops that
    # run for tens of seconds. ANALYZE needs the owner on PostgreSQL 16, so the app gets this one
    # narrow entry point to call after bulk loads. Hardening:
    # - no arguments: it analyzes a fixed, schema-qualified list of tables;
    # - search_path pins pg_catalog first and pg_temp explicitly last (an omitted pg_temp is
    #   searched first for relations, letting a caller shadow tables with temporary ones);
    # - EXECUTE is revoked from PUBLIC and granted to the application role only.
    analyzed = ", ".join(f"public.{t}" for t in TENANT_TABLES if t not in ("facts", "fact_lineage"))
    op.execute(
        f"""
        CREATE FUNCTION public.refresh_planner_statistics() RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp
        AS $$
        BEGIN
            ANALYZE {analyzed};
        END
        $$;
        REVOKE ALL ON FUNCTION public.refresh_planner_statistics() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.refresh_planner_statistics() TO {role};
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.refresh_planner_statistics()")
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
