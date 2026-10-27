"""SQL aggregations for exact base facts.

Each query returns, from one snapshot: the NUMERIC aggregate, the ids of the contributing rows
(lineage), a SHA-256 digest of those rows' relevant columns (inputs hash) and the set of currencies
seen. Values are summed by PostgreSQL on NUMERIC columns; Python never touches a float.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from app.domain.hashing import canonical_json, sha256_hex
from app.facts.model import Period, Scope, ScopeKind

PROMOTED_PRODUCTS = (
    "SELECT acp.product_id FROM ad_campaign_products acp "
    "WHERE acp.store_id = :sid AND acp.campaign_id = :scope_id"
)


@dataclass(frozen=True)
class Aggregate:
    value: Decimal
    table: str
    ids: tuple[UUID, ...]
    digest: str
    currencies: frozenset[str]

    @property
    def inputs_hash(self) -> str:
        return sha256_hex(canonical_json({"table": self.table, "digest": self.digest}))


def _utc_text(column: str) -> str:
    """Timestamp text independent of the session's TimeZone and DateStyle settings."""
    # No colons in the format: `text()` would parse `:MI` as a bind parameter.
    return f"to_char({column} AT TIME ZONE 'UTC', 'YYYYMMDD\"T\"HH24MISS.US')"


def _date_text(column: str) -> str:
    return f"to_char({column}, 'YYYY-MM-DD')"


def _product_filter(scope: Scope, column: str) -> str:
    if scope.kind is ScopeKind.PRODUCT:
        return f" AND {column} = :scope_id"
    if scope.kind is ScopeKind.CAMPAIGN:
        return f" AND {column} IN ({PROMOTED_PRODUCTS})"
    return ""


def _run(
    conn: Connection,
    *,
    table: str,
    alias: str,
    value_expr: str,
    repr_expr: str,
    from_where: str,
    params: dict[str, Any],
) -> Aggregate:
    sql = f"""
        SELECT COALESCE(SUM({value_expr}), 0) AS value,
               array_agg({alias}.id ORDER BY {alias}.id) AS ids,
               encode(sha256(convert_to(
                   COALESCE(string_agg({repr_expr}, ';' ORDER BY {alias}.id), ''), 'UTF8'
               )), 'hex') AS digest,
               array_agg(DISTINCT {alias}.currency) AS currencies
        {from_where}
    """
    row = conn.execute(text(sql), params).one()
    return Aggregate(
        value=Decimal(row.value),
        table=table,
        ids=tuple(row.ids or ()),
        digest=str(row.digest),
        currencies=frozenset(c.strip() for c in (row.currencies or ())),
    )


def _params(store_id: UUID, scope: Scope, period: Period) -> dict[str, Any]:
    return {"sid": store_id, "scope_id": scope.id, "start": period.start, "end": period.end}


def line_aggregate(
    conn: Connection,
    store_id: UUID,
    scope: Scope,
    period: Period,
    *,
    value_expr: str,
    repr_columns: tuple[str, ...],
) -> Aggregate:
    """Aggregate over order lines of non-cancelled orders placed in the period (by order date).

    Product scope keeps the product's lines; campaign scope keeps lines of the products the
    campaign promotes (all sales of those products, not only ad-attributed ones).
    """
    from_where = (
        "FROM order_lines ol "
        "JOIN orders o ON o.store_id = ol.store_id AND o.id = ol.order_id "
        "WHERE ol.store_id = :sid AND o.status <> 'cancelled' "
        "AND o.ordered_at >= :start AND o.ordered_at < :end"
        + _product_filter(scope, "ol.product_id")
    )
    return _run(
        conn,
        table="order_lines",
        alias="ol",
        value_expr=value_expr,
        repr_expr="concat_ws(':', ol.id, " + ", ".join(repr_columns) + ")",
        from_where=from_where,
        params=_params(store_id, scope, period),
    )


def refund_aggregate(conn: Connection, store_id: UUID, scope: Scope, period: Period) -> Aggregate:
    """Sum of refund amounts by refund date; scoped through the refunded line's product."""
    from_where = (
        "FROM refunds r "
        "JOIN order_lines ol ON ol.store_id = r.store_id AND ol.id = r.order_line_id "
        "WHERE r.store_id = :sid AND r.refunded_at >= :start AND r.refunded_at < :end"
        + _product_filter(scope, "ol.product_id")
    )
    return _run(
        conn,
        table="refunds",
        alias="r",
        value_expr="r.amount",
        repr_expr=f"concat_ws(':', r.id, r.amount, {_utc_text('r.refunded_at')})",
        from_where=from_where,
        params=_params(store_id, scope, period),
    )


def ad_metric_aggregate(
    conn: Connection, store_id: UUID, scope: Scope, period: Period, *, column: str
) -> Aggregate:
    """Sum of a daily ad metric. Day `d` belongs to the period when its UTC midnight does."""
    campaign_filter = " AND m.campaign_id = :scope_id" if scope.kind is ScopeKind.CAMPAIGN else ""
    from_where = (
        "FROM ad_metrics_daily m "
        "WHERE m.store_id = :sid "
        "AND (m.metric_date::timestamp AT TIME ZONE 'UTC') >= :start "
        "AND (m.metric_date::timestamp AT TIME ZONE 'UTC') < :end" + campaign_filter
    )
    return _run(
        conn,
        table="ad_metrics_daily",
        alias="m",
        value_expr=f"m.{column}",
        repr_expr=f"concat_ws(':', m.id, m.{column})",
        from_where=from_where,
        params=_params(store_id, scope, period),
    )


def fixed_cost_aggregate(conn: Connection, store_id: UUID, period: Period) -> Aggregate:
    """Fixed cost items prorated by the share of each item's span that overlaps the period."""
    from_where = """
        FROM (
            SELECT id, amount, currency, period_start, period_end,
                   (period_start::timestamp AT TIME ZONE 'UTC') AS cs,
                   (period_end::timestamp AT TIME ZONE 'UTC') AS ce
            FROM cost_items
            WHERE store_id = :sid AND kind = 'fixed'
        ) c
        WHERE c.cs < :end AND c.ce > :start
    """
    value_expr = (
        "c.amount * EXTRACT(EPOCH FROM (LEAST(c.ce, :end) - GREATEST(c.cs, :start))) "
        "/ EXTRACT(EPOCH FROM (c.ce - c.cs))"
    )
    return _run(
        conn,
        table="cost_items",
        alias="c",
        value_expr=value_expr,
        repr_expr=(
            "concat_ws(':', c.id, c.amount, "
            f"{_date_text('c.period_start')}, {_date_text('c.period_end')})"
        ),
        from_where=from_where,
        params={"sid": store_id, "start": period.start, "end": period.end},
    )


def latest_inventory(
    conn: Connection, store_id: UUID, product_id: UUID, as_of: Period
) -> Aggregate | None:
    """Most recent end-of-day snapshot whose day ended at or before the period end."""
    row = conn.execute(
        text(
            "SELECT s.id, s.units_on_hand, s.snapshot_date FROM inventory_snapshots s "
            "WHERE s.store_id = :sid AND s.product_id = :pid "
            "AND ((s.snapshot_date + 1)::timestamp AT TIME ZONE 'UTC') <= :end "
            "ORDER BY s.snapshot_date DESC LIMIT 1"
        ),
        {"sid": store_id, "pid": product_id, "end": as_of.end},
    ).first()
    if row is None:
        return None
    digest = sha256_hex(f"{row.id}:{row.units_on_hand}:{row.snapshot_date.isoformat()}")
    return Aggregate(
        value=Decimal(row.units_on_hand),
        table="inventory_snapshots",
        ids=(row.id,),
        digest=digest,
        currencies=frozenset(),
    )


def campaign_ids(conn: Connection, store_id: UUID) -> list[UUID]:
    rows = conn.execute(
        text("SELECT id FROM ad_campaigns WHERE store_id = :sid ORDER BY id"), {"sid": store_id}
    )
    return [r.id for r in rows]


def product_ids(conn: Connection, store_id: UUID) -> list[UUID]:
    rows = conn.execute(
        text("SELECT id FROM products WHERE store_id = :sid ORDER BY id"), {"sid": store_id}
    )
    return [r.id for r in rows]
