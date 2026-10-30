"""Decisions, approvals and email approval links (Task 4 B1, ADR 0016).

A decision holds a cause's options (app.decisions.options) with their simulated impact facts.
The database enforces the state machine (migration 0007) and a single approval per decision;
this module is the only writer. Approving a decision creates its actions and their outbox rows
in the same transaction, so an approved decision always has work queued and nothing is queued
without an approval.

Email approval links are HMAC-SHA256 signed, name one decision, option and verdict, expire after
24 hours and work once (the link row is consumed atomically). A link whose option goes beyond
the spending caps only returns a confirmation: approving it takes the web (API) channel.
"""

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from app.decisions.options import OptionSet
from app.domain.audit import append_audit
from app.facts.engine import FactEngine
from app.twin import ActionKind, TwinModel
from app.twin.facts import input_facts, simulation_facts

DECISION_TTL = timedelta(hours=72)
LINK_TTL = timedelta(hours=24)


class DecisionStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"
    MEASURED = "measured"


TRANSITIONS: frozenset[tuple[DecisionStatus, DecisionStatus]] = frozenset(
    {
        (DecisionStatus.PROPOSED, DecisionStatus.APPROVED),
        (DecisionStatus.PROPOSED, DecisionStatus.REJECTED),
        (DecisionStatus.PROPOSED, DecisionStatus.EXPIRED),
        (DecisionStatus.APPROVED, DecisionStatus.EXECUTING),
        (DecisionStatus.EXECUTING, DecisionStatus.EXECUTED),
        (DecisionStatus.EXECUTING, DecisionStatus.FAILED),
        (DecisionStatus.EXECUTED, DecisionStatus.MEASURED),
    }
)


class Channel(StrEnum):
    API = "api"
    EMAIL = "email"


class Verdict(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class DecisionError(RuntimeError):
    """A request the decision cannot take (already decided, expired, unknown option)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class OptionRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    option_id: str
    rank: int
    kind: str
    action_family: str
    entity: str
    actions: list[dict[str, Any]]
    executable: bool
    reversibility: str
    impact_fact_id: int | None
    p10: Decimal | None
    p50: Decimal | None
    p90: Decimal | None
    risks: list[str]
    invalidated_if: list[str]
    flags: list[str]


class DecisionView(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: UUID
    store_id: UUID
    source: str
    incident_id: str | None
    cause: str
    entity: str
    status: DecisionStatus
    recommended_option_id: str
    approved_option_id: str | None
    horizon_days: int
    floor: Decimal
    currency: str
    as_of: str
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
    options: list[OptionRow]

    def option(self, option_id: str) -> OptionRow:
        found = next((o for o in self.options if o.option_id == option_id), None)
        if found is None:
            raise DecisionError("unknown_option", f"decision has no option {option_id!r}")
        return found


EXECUTABLE_KINDS = {
    ActionKind.PAUSE_CAMPAIGN: "pause_campaign",
    ActionKind.CHANGE_BUDGET: "change_budget",
}


def propose(
    conn: Connection,
    engine: FactEngine,
    model: TwinModel,
    options: OptionSet,
    *,
    source: str,
    incident_id: str | None = None,
    now: datetime | None = None,
) -> DecisionView:
    """Persist a decision with its options and their simulated impact facts."""
    now = now or datetime.now(UTC)
    decision_id = uuid4()
    conn.execute(
        text(
            "INSERT INTO decisions (decision_id, store_id, source, incident_id, cause, entity, "
            "status, recommended_option_id, horizon_days, floor, currency, as_of, expires_at, "
            "payload, created_at, updated_at) VALUES (:d, :s, :source, :incident, :cause, "
            ":entity, 'proposed', :rec, :h, :floor, :cur, :as_of, :exp, CAST(:payload AS jsonb), "
            ":now, :now)"
        ),
        {
            "d": decision_id,
            "s": model.store_id,
            "source": source,
            "incident": incident_id,
            "cause": options.cause,
            "entity": options.entity,
            "rec": options.recommended,
            "h": options.horizon_days,
            "floor": options.floor,
            "cur": model.currency,
            "as_of": model.as_of,
            "exp": now + DECISION_TTL,
            "payload": json.dumps({"reason": options.reason, "twin": model.fingerprint}),
            "now": now,
        },
    )
    for rank, option in enumerate(options.options):
        fact_id = None
        impact = option.impact
        sim = option.simulation
        if sim is not None and impact is not None:
            facts = simulation_facts(engine, model, sim, input_facts(engine, model, sim))
            fact = facts["twin.change.net_profit"]
            fact_id = fact.id
            p10, p50, p90 = fact.p10, fact.p50, fact.p90
        else:
            p10 = p50 = p90 = None
        conn.execute(
            text(
                "INSERT INTO decision_options (store_id, decision_id, option_id, rank, kind, "
                "action_family, entity, actions, executable, reversibility, impact_fact_id, p10, "
                "p50, p90, risks, invalidated_if, flags) VALUES (:s, :d, :o, :rank, :kind, "
                ":family, :entity, CAST(:actions AS jsonb), :exe, :rev, :fact, :p10, :p50, :p90, "
                "CAST(:risks AS jsonb), CAST(:invalid AS jsonb), CAST(:flags AS jsonb))"
            ),
            {
                "s": model.store_id,
                "d": decision_id,
                "o": option.option_id,
                "rank": rank,
                "kind": option.kind.value,
                "family": option.action_family.value,
                "entity": option.entity,
                "actions": json.dumps([a.model_dump(mode="json") for a in option.actions]),
                "exe": option.executable,
                "rev": option.reversibility.value,
                "fact": fact_id,
                "p10": p10,
                "p50": p50,
                "p90": p90,
                "risks": json.dumps(list(option.risks)),
                "invalid": json.dumps(list(option.invalidated_if)),
                "flags": json.dumps(list(option.flags)),
            },
        )
    append_audit(
        conn,
        model.store_id,
        actor="system:decisions",
        action="decision.proposed",
        payload={
            "decision_id": str(decision_id),
            "cause": options.cause,
            "entity": options.entity,
            "recommended": options.recommended,
            "options": [o.option_id for o in options.options],
        },
        occurred_at=now,
    )
    return get(conn, model.store_id, decision_id)


def get(conn: Connection, store_id: UUID, decision_id: UUID, *, lock: bool = False) -> DecisionView:
    row = conn.execute(
        text(
            "SELECT * FROM decisions WHERE store_id = :s AND decision_id = :d"
            + (" FOR UPDATE" if lock else "")
        ),
        {"s": store_id, "d": decision_id},
    ).first()
    if row is None:
        raise LookupError(f"decision {decision_id} does not exist or is not visible")
    options = [
        OptionRow(
            option_id=o.option_id,
            rank=o.rank,
            kind=o.kind,
            action_family=o.action_family,
            entity=o.entity,
            actions=list(o.actions),
            executable=o.executable,
            reversibility=o.reversibility,
            impact_fact_id=o.impact_fact_id,
            p10=o.p10,
            p50=o.p50,
            p90=o.p90,
            risks=list(o.risks),
            invalidated_if=list(o.invalidated_if),
            flags=list(o.flags),
        )
        for o in conn.execute(
            text(
                "SELECT * FROM decision_options WHERE store_id = :s AND decision_id = :d "
                "ORDER BY rank"
            ),
            {"s": store_id, "d": decision_id},
        )
    ]
    return DecisionView(
        decision_id=row.decision_id,
        store_id=row.store_id,
        source=row.source,
        incident_id=row.incident_id,
        cause=row.cause,
        entity=row.entity,
        status=DecisionStatus(row.status),
        recommended_option_id=row.recommended_option_id,
        approved_option_id=row.approved_option_id,
        horizon_days=row.horizon_days,
        floor=row.floor,
        currency=row.currency.strip(),
        as_of=row.as_of.isoformat(),
        expires_at=row.expires_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        options=options,
    )


def list_decisions(conn: Connection, store_id: UUID) -> list[DecisionView]:
    ids = conn.execute(
        text("SELECT decision_id FROM decisions WHERE store_id = :s ORDER BY created_at DESC"),
        {"s": store_id},
    ).scalars()
    return [get(conn, store_id, d) for d in ids]


def transition(
    conn: Connection,
    store_id: UUID,
    decision_id: UUID,
    to: DecisionStatus,
    *,
    approved_option_id: str | None = None,
) -> None:
    """One state change; the database refuses any transition the machine does not allow."""
    conn.execute(
        text(
            "UPDATE decisions SET status = :to, approved_option_id = "
            "COALESCE(:opt, approved_option_id) WHERE store_id = :s AND decision_id = :d"
        ),
        {"to": to.value, "opt": approved_option_id, "s": store_id, "d": decision_id},
    )


def _expire_if_due(conn: Connection, decision: DecisionView, now: datetime) -> bool:
    if decision.status is DecisionStatus.PROPOSED and decision.expires_at <= now:
        transition(conn, decision.store_id, decision.decision_id, DecisionStatus.EXPIRED)
        append_audit(
            conn,
            decision.store_id,
            actor="system:decisions",
            action="decision.expired",
            payload={"decision_id": str(decision.decision_id)},
            occurred_at=now,
        )
        return True
    return False


def expire_due(conn: Connection, store_id: UUID, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    due = conn.execute(
        text(
            "SELECT decision_id FROM decisions WHERE store_id = :s AND status = 'proposed' "
            "AND expires_at <= :now FOR UPDATE"
        ),
        {"s": store_id, "now": now},
    ).scalars()
    count = 0
    for decision_id in list(due):
        count += _expire_if_due(conn, get(conn, store_id, decision_id), now)
    return count


def _provider(
    conn: Connection, store_id: UUID, campaign_id: UUID, meta_links: dict[str, str]
) -> str:
    synthetic = conn.execute(
        text("SELECT synthetic FROM stores WHERE store_id = :s"), {"s": store_id}
    ).scalar_one()
    return "meta" if not synthetic or str(campaign_id) in meta_links else "simulator"


def decide(
    conn: Connection,
    store_id: UUID,
    decision_id: UUID,
    option_id: str | None,
    verdict: Verdict,
    *,
    channel: Channel,
    actor: str,
    now: datetime | None = None,
    meta_links: dict[str, str] | None = None,
) -> DecisionView:
    """Approve an option, or reject the decision, exactly once. Approval queues the option's
    actions (actions and outbox rows) in the same transaction."""
    now = now or datetime.now(UTC)
    decision = get(conn, store_id, decision_id, lock=True)
    if _expire_if_due(conn, decision, now):
        raise DecisionError("expired", "the decision expired before it was decided")
    if decision.status is not DecisionStatus.PROPOSED:
        raise DecisionError("already_decided", f"the decision is already {decision.status.value}")
    option = decision.option(option_id) if option_id is not None else None
    if verdict is Verdict.APPROVED and (option is None or not option.executable):
        raise DecisionError("not_executable", "only an executable option can be approved")
    try:
        with conn.begin_nested():
            conn.execute(
                text(
                    "INSERT INTO approvals (approval_id, store_id, decision_id, option_id, "
                    "verdict, channel, actor, created_at) VALUES (:a, :s, :d, :o, :v, :c, :actor, "
                    ":now)"
                ),
                {
                    "a": uuid4(),
                    "s": store_id,
                    "d": decision_id,
                    "o": option_id,
                    "v": verdict.value,
                    "c": channel.value,
                    "actor": actor,
                    "now": now,
                },
            )
    except IntegrityError as exc:  # another channel decided first
        raise DecisionError("already_decided", "the decision was already decided") from exc
    if verdict is Verdict.REJECTED:
        transition(conn, store_id, decision_id, DecisionStatus.REJECTED)
    else:
        assert option is not None
        transition(
            conn, store_id, decision_id, DecisionStatus.APPROVED, approved_option_id=option_id
        )
        for seq, action in enumerate(option.actions):
            kind = EXECUTABLE_KINDS.get(ActionKind(action["kind"]))
            if kind is None:
                continue
            campaign = UUID(str(action["entity"]))
            enqueue(
                conn,
                store_id,
                decision_id,
                option.option_id,
                seq,
                kind,
                campaign,
                {"change": action.get("change"), "days": action.get("days")},
                provider=_provider(conn, store_id, campaign, meta_links or {}),
                key=f"{decision_id}:{option.option_id}:{seq}",
                now=now,
            )
    append_audit(
        conn,
        store_id,
        actor=actor,
        action=f"decision.{verdict.value}",
        payload={
            "decision_id": str(decision_id),
            "option_id": option_id,
            "channel": channel.value,
        },
        occurred_at=now,
    )
    return get(conn, store_id, decision_id)


def enqueue(
    conn: Connection,
    store_id: UUID,
    decision_id: UUID,
    option_id: str,
    seq: int,
    kind: str,
    campaign_id: UUID,
    params: dict[str, Any],
    *,
    provider: str,
    key: str,
    now: datetime,
    rollback_of: UUID | None = None,
) -> UUID:
    """An action and its outbox row (the caller's transaction), ready from `now`."""
    action_id = uuid4()
    conn.execute(
        text(
            "INSERT INTO actions (action_id, store_id, decision_id, option_id, seq, kind, "
            "campaign_id, provider, params, idempotency_key, status, rollback_of) VALUES (:a, :s, "
            ":d, :o, :seq, :kind, :c, :p, CAST(:params AS jsonb), :key, 'pending', :rb)"
        ),
        {
            "a": action_id,
            "s": store_id,
            "d": decision_id,
            "o": option_id,
            "seq": seq,
            "kind": kind,
            "c": campaign_id,
            "p": provider,
            "params": json.dumps(params),
            "key": key,
            "rb": rollback_of,
        },
    )
    conn.execute(
        text(
            "INSERT INTO outbox (store_id, action_id, status, available_at) "
            "VALUES (:s, :a, 'pending', :now)"
        ),
        {"s": store_id, "a": action_id, "now": now},
    )
    return action_id


# --- email approval links ------------------------------------------------------------------


@dataclass(frozen=True)
class LinkClaims:
    link_id: UUID
    store_id: UUID
    decision_id: UUID
    option_id: str
    verdict: Verdict
    expires_at: datetime


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text_: str) -> bytes:
    return base64.urlsafe_b64decode(text_ + "=" * (-len(text_) % 4))


def _sign(payload: bytes, secret: str) -> str:
    return _b64(hmac.new(secret.encode(), payload, hashlib.sha256).digest())


def create_link(
    conn: Connection,
    store_id: UUID,
    decision_id: UUID,
    option_id: str,
    verdict: Verdict,
    *,
    secret: str,
    now: datetime | None = None,
) -> str:
    """A signed, single-use approval link token for one decision, option and verdict."""
    now = now or datetime.now(UTC)
    get(conn, store_id, decision_id).option(option_id)
    link_id = uuid4()
    expires = now + LINK_TTL
    conn.execute(
        text(
            "INSERT INTO approval_links (link_id, store_id, decision_id, option_id, verdict, "
            "expires_at, created_at) VALUES (:l, :s, :d, :o, :v, :exp, :now)"
        ),
        {
            "l": link_id,
            "s": store_id,
            "d": decision_id,
            "o": option_id,
            "v": verdict.value,
            "exp": expires,
            "now": now,
        },
    )
    payload = json.dumps(
        {
            "l": str(link_id),
            "s": str(store_id),
            "d": str(decision_id),
            "o": option_id,
            "v": verdict.value,
            "e": int(expires.timestamp()),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"{_b64(payload)}.{_sign(payload, secret)}"


def read_link(token: str, *, secret: str, now: datetime | None = None) -> LinkClaims:
    """Verify the signature and the expiry (no database access)."""
    now = now or datetime.now(UTC)
    try:
        body, signature = token.split(".", 1)
        payload = _unb64(body)
    except ValueError as exc:
        raise DecisionError("invalid_link", "the link is malformed") from exc
    if not hmac.compare_digest(_sign(payload, secret), signature):
        raise DecisionError("invalid_link", "the link signature does not match")
    claims = json.loads(payload)
    expires = datetime.fromtimestamp(int(claims["e"]), tz=UTC)
    if expires <= now:
        raise DecisionError("expired_link", "the link has expired")
    return LinkClaims(
        link_id=UUID(claims["l"]),
        store_id=UUID(claims["s"]),
        decision_id=UUID(claims["d"]),
        option_id=str(claims["o"]),
        verdict=Verdict(claims["v"]),
        expires_at=expires,
    )


def consume_link(conn: Connection, claims: LinkClaims, now: datetime | None = None) -> None:
    """Mark the link used, once: a replayed link is refused."""
    now = now or datetime.now(UTC)
    used = conn.execute(
        text(
            "UPDATE approval_links SET used_at = :now WHERE store_id = :s AND link_id = :l "
            "AND used_at IS NULL AND expires_at > :now RETURNING link_id"
        ),
        {"now": now, "s": claims.store_id, "l": claims.link_id},
    ).first()
    if used is None:
        raise DecisionError("used_link", "the link was already used or has expired")
