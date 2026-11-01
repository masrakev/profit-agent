"""Retention (ADR 0021, launch readiness section 3): model traces are kept 30 days.

Daily, for each store in its own tenant transaction: the agent's step traces older than the
retention period are deleted (the verified investigations they led to stay, like facts,
decisions and the audit log). Expired sign-in links and sessions are deleted too, and inbound
WhatsApp message ids past the same period (their content is cleared once processed; the id is
kept only to recognise a message Meta delivers again, which it does within 36 hours).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Engine, text

from app.db import tenant_transaction
from app.scheduler.jobs import store_ids


@dataclass(frozen=True)
class Purged:
    traces: int
    login_links: int
    sessions: int
    inbound: int = 0


def purge(engine: Engine, now: datetime, *, days: int = 30) -> Purged:
    cutoff = now - timedelta(days=days)
    traces = 0
    for store_id in store_ids(engine):
        with tenant_transaction(engine, store_id) as conn:
            traces += conn.execute(
                text("DELETE FROM investigation_steps WHERE store_id = :s AND created_at < :cut"),
                {"s": store_id, "cut": cutoff},
            ).rowcount
    with engine.begin() as conn:
        links = conn.execute(
            text("DELETE FROM auth.login_links WHERE expires_at < :day"),
            {"day": now - timedelta(days=1)},
        ).rowcount
        sessions = conn.execute(
            text("DELETE FROM auth.sessions WHERE expires_at < :now OR revoked_at < :day"),
            {"now": now, "day": now - timedelta(days=1)},
        ).rowcount
        inbound = conn.execute(
            text("DELETE FROM whatsapp.inbound WHERE received_at < :cut AND status <> 'pending'"),
            {"cut": cutoff},
        ).rowcount
    return Purged(traces, links, sessions, inbound)
