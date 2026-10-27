"""Recompute and persist every fact for a store.

    uv run python -m app.facts.recompute --store <store_id> [--start YYYY-MM-DD --end YYYY-MM-DD]

Without dates, the period covers every UTC day that has an order. Recomputing over unchanged data
writes nothing new: identical inputs give identical fact hashes.
"""

import argparse
import json
import sys
from collections import Counter
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import Connection, Engine, text

from app.config import get_settings
from app.db import app_engine, tenant_transaction
from app.domain.audit import append_audit
from app.facts.engine import FactEngine
from app.facts.model import FactStatus, Period
from app.observability import configure_logging, get_logger


def default_period(conn: Connection, store_id: UUID) -> Period | None:
    row = conn.execute(
        text(
            "SELECT min(ordered_at AT TIME ZONE 'UTC')::date AS first, "
            "max(ordered_at AT TIME ZONE 'UTC')::date AS last "
            "FROM orders WHERE store_id = :sid"
        ),
        {"sid": store_id},
    ).one()
    if row.first is None:
        return None
    return Period.days(row.first, row.last + timedelta(days=1))


def recompute(engine: Engine, store_id: UUID, period: Period | None = None) -> dict[str, object]:
    log = get_logger(__name__, store_id=str(store_id))
    with tenant_transaction(engine, store_id) as conn:
        fact_engine = FactEngine(conn, store_id)
        period = period or default_period(conn, store_id)
        if period is None:
            raise ValueError(f"store {store_id} has no orders; pass --start and --end")
        facts = fact_engine.compute_all(period)
        saved, report = fact_engine.persist_all(facts)
        undefined = Counter(f.formula_id for f in saved if f.status is FactStatus.UNDEFINED)
        summary: dict[str, object] = {
            "store_id": str(store_id),
            "period": {"start": period.start.isoformat(), "end": period.end.isoformat()},
            "facts": len(saved),
            "inserted": report.inserted,
            "already_present": report.existing,
            "undefined_by_formula": dict(sorted(undefined.items())),
        }
        append_audit(
            conn, store_id, actor="system:recompute", action="facts.recomputed", payload=summary
        )
    log.info("facts.recomputed", **summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--store", required=True, type=UUID)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat, help="exclusive")
    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)
    if (args.start is None) != (args.end is None):
        parser.error("--start and --end go together")
    period = Period.days(args.start, args.end) if args.start else None
    engine = app_engine()
    try:
        summary = recompute(engine, args.store, period)
    finally:
        engine.dispose()
    sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
