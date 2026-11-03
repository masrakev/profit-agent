"""Decisions, approvals and email approval links (Task 4 B1, ADR 0016).

A decision holds a cause's options (app.decisions.options) with their simulated impact facts.
The database enforces the state machine (migration 0007) and a single approval per decision;
this module is the only writer. Approving a decision creates its actions and their outbox rows
in the same transaction, so an approved decision always has work queued and nothing is queued
without an approval.

An owner never sees two pending decisions acting on the same campaign or product: when a
decision is proposed and another pending one acts on an entity it acts on, the one resting on
the most recent evidence (its data's last day; at equal evidence, the later proposal) stands,
and the other is `superseded`, a terminal state, linked to the one that stood, with the reason.
A superseded goal step makes its plan propose a revision (`app.goals.service`).

Every decision and option reads as a label naming what it acts on (`app.decisions.labels`), and
every decision shows "do nothing" next to its options: an exact zero fact, whose parent is the
twin's do-nothing outcome. It is not an option row: it is never approved nor executed.

Email approval links are HMAC-SHA256 signed, name one decision, option and verdict, expire after
24 hours and work once (the link row is consumed atomically). A link whose option goes beyond
the spending caps only returns a confirmation: approving it takes the web (API) channel.
"""

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from app.causal.verdict import Consistency, consistency, verdict_text
from app.channels.render import load_entity_names
from app.decisions.labels import DO_NOTHING, decision_label, entity_refs, option_label
from app.decisions.options import OptionSet
from app.delivery.queue import Subject, notify
from app.domain.audit import Origin, append_audit
from app.domain.hashing import canonical_json, sha256_hex
from app.facts.engine import FactEngine
from app.facts.model import Fact, FactKind, FactStatus, Lineage, ParentRef, Scope, Unit
from app.twin import ActionKind, TwinModel
from app.twin.facts import input_facts, simulation_facts

DECISION_TTL = timedelta(hours=72)
DO_NOTHING_FORMULA = "decision.do_nothing.net_profit"
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
    SUPERSEDED = "superseded"  # another pending decision on the same entity stood


TRANSITIONS: frozenset[tuple[DecisionStatus, DecisionStatus]] = frozenset(
    {
        (DecisionStatus.PROPOSED, DecisionStatus.APPROVED),
        (DecisionStatus.PROPOSED, DecisionStatus.REJECTED),
        (DecisionStatus.PROPOSED, DecisionStatus.EXPIRED),
        (DecisionStatus.APPROVED, DecisionStatus.EXECUTING),
        (DecisionStatus.EXECUTING, DecisionStatus.EXECUTED),
        (DecisionStatus.EXECUTING, DecisionStatus.FAILED),
        (DecisionStatus.EXECUTED, DecisionStatus.MEASURED),
        (DecisionStatus.PROPOSED, DecisionStatus.SUPERSEDED),
    }
)


class Channel(StrEnum):
    API = "api"
    EMAIL = "email"
    WHATSAPP = "whatsapp"  # a reply button carrying a signed approval link (app.whatsapp.buttons)


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
    label: str  # what it does, naming what it acts on
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
    superseded_by: UUID | None = None  # the decision that stood
    superseded_reason: str | None = None
    label: str  # the question it asks: its recommended option
    do_nothing: "DoNothing"
    outcomes: list["OutcomeView"] = []  # what its actions were measured to do, once measured

    def option(self, option_id: str) -> OptionRow:
        found = next((o for o in self.options if o.option_id == option_id), None)
        if found is None:
            raise DecisionError("unknown_option", f"decision has no option {option_id!r}")
        return found


class DoNothing(BaseModel):
    """The baseline the options are compared with: never approved, never executed."""

    model_config = ConfigDict(frozen=True)

    label: str = DO_NOTHING
    impact_fact_id: int | None  # an exact zero; None on decisions proposed before it existed


class OutcomeView(BaseModel):
    """What an executed action was measured to do: its effect against what was predicted, and
    whether the prediction held (`verdict`: inside, above or below the predicted range)."""

    model_config = ConfigDict(frozen=True)

    outcome_id: UUID
    action_id: UUID
    status: str  # measured | abstained
    method: str | None
    window_start: date
    window_end: date
    effect_fact_id: int | None  # the measured effect, an estimate
    predicted_fact_id: int | None  # what was predicted for the same window, an estimate
    verdict: Consistency | None
    verdict_text: str | None
    reason: str | None  # why it was measured, or why not


DecisionView.model_rebuild()


def outcomes_of(conn: Connection, store_id: UUID, decision_id: UUID) -> list[OutcomeView]:
    rows = conn.execute(
        text(
            "SELECT outcome_id, action_id, status, method, window_start, window_end, "
            "effect_fact_id, payload FROM outcomes WHERE store_id = :s AND decision_id = :d "
            "ORDER BY created_at"
        ),
        {"s": store_id, "d": decision_id},
    ).all()
    out = []
    for r in rows:
        found = consistency(r.payload)
        predicted = r.payload.get("predicted_fact_id")
        out.append(
            OutcomeView(
                outcome_id=r.outcome_id,
                action_id=r.action_id,
                status=r.status,
                method=r.method,
                window_start=r.window_start,
                window_end=r.window_end,
                effect_fact_id=r.effect_fact_id,
                predicted_fact_id=int(predicted) if predicted is not None else None,
                verdict=found,
                verdict_text=verdict_text(found),
                reason=r.payload.get("reason"),
            )
        )
    return out


# What each action acts on, to find decisions acting on the same entity.
ENTITY_KINDS = {
    ActionKind.CHANGE_BUDGET: "campaign",
    ActionKind.PAUSE_CAMPAIGN: "campaign",
    ActionKind.CHANGE_PRICE: "product",
    ActionKind.LAUNCH_CAMPAIGN: "product",
    ActionKind.RESTOCK_PRODUCT: "product",
}
EVERY_CAMPAIGN = "campaign:*"

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
    """Persist a decision with its options and their simulated impact facts, and the zero fact
    of doing nothing (the decision row cannot change once inserted, so it comes first)."""
    now = now or datetime.now(UTC)
    decision_id = uuid4()
    impacts: list[Fact | None] = []
    baseline: Fact | None = None
    for option in options.options:
        fact = None
        if option.simulation is not None and option.impact is not None:
            sim = option.simulation
            facts = simulation_facts(engine, model, sim, input_facts(engine, model, sim))
            fact = facts["twin.change.net_profit"]
            baseline = baseline or facts["twin.do_nothing.net_profit"]
        impacts.append(fact)
    zero = do_nothing_fact(engine, baseline) if baseline and baseline.is_defined else None
    conn.execute(
        text(
            "INSERT INTO decisions (decision_id, store_id, source, incident_id, cause, entity, "
            "status, recommended_option_id, horizon_days, floor, currency, as_of, expires_at, "
            "payload, created_at, updated_at, do_nothing_fact_id) VALUES (:d, :s, :source, "
            ":incident, :cause, :entity, 'proposed', :rec, :h, :floor, :cur, :as_of, :exp, "
            "CAST(:payload AS jsonb), :now, :now, :zero)"
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
            "zero": zero.id if zero else None,
        },
    )
    for rank, (option, fact) in enumerate(zip(options.options, impacts, strict=True)):
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
                "fact": fact.id if fact else None,
                "p10": fact.p10 if fact else None,
                "p50": fact.p50 if fact else None,
                "p90": fact.p90 if fact else None,
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
    lost = resolve_conflicts(conn, get(conn, model.store_id, decision_id), now)
    for loser in lost:
        if loser.source == "goal":
            # goals build on decisions; imported here, where a goal step's decision is involved
            from app.goals.service import step_superseded

            step_superseded(conn, loser, now=now)
    stands = all(d.decision_id != decision_id for d in lost)
    if stands and source != "incident":  # an alert's message carries its incident's decision
        notify(
            conn,
            model.store_id,
            Subject.DECISION,
            str(decision_id),
            available_at=now,
            now=now,
        )
    return get(conn, model.store_id, decision_id)


def do_nothing_fact(engine: FactEngine, outcome: Fact) -> Fact:
    """Doing nothing compared with itself: an exact zero over the options' horizon, with the
    twin's do-nothing outcome as its parent, so its proof shows what "nothing" leads to."""
    fact = Fact(
        store_id=outcome.store_id,
        formula_id=DO_NOTHING_FORMULA,
        formula_version=1,
        kind=FactKind.EXACT,
        scope=Scope.store(),
        period=outcome.period,
        status=FactStatus.DEFINED,
        value=Decimal(0),
        unit=Unit.MONEY,
        currency=outcome.currency,
        inputs_hash=sha256_hex(
            canonical_json({"formula": DO_NOTHING_FORMULA, "do_nothing": outcome.fact_hash})
        ),
        lineage=Lineage(parents=(ParentRef(role="do_nothing", fact_hash=outcome.fact_hash),)),
    )
    return engine.persist(engine.adopt(fact))


def targets(decision: DecisionView) -> frozenset[str]:
    """The campaigns and products a decision acts on (any of its options), and its own
    entity; a store-wide budget change acts on every campaign."""
    out = {decision.entity} if ":" in decision.entity else set()
    for option in decision.options:
        for action in option.actions:
            kind = ActionKind(action["kind"])
            if kind is ActionKind.CHANGE_ALL_AD_SPEND:
                out.add(EVERY_CAMPAIGN)
            elif action.get("entity") and kind in ENTITY_KINDS:
                out.add(f"{ENTITY_KINDS[kind]}:{action['entity']}")
    return frozenset(out)


def shared_targets(a: frozenset[str], b: frozenset[str]) -> set[str]:
    shared = set(a & b) - {EVERY_CAMPAIGN}
    for one, other in ((a, b), (b, a)):
        if EVERY_CAMPAIGN in one:
            shared |= {t for t in other if t.startswith("campaign:")} or {EVERY_CAMPAIGN}
    return shared


def _reason(shared: set[str], winner: DecisionView, loser: DecisionView) -> str:
    on = ", ".join(
        "every campaign" if t == EVERY_CAMPAIGN else "{{E:" + t + "}}" for t in sorted(shared)
    )
    if winner.as_of > loser.as_of:
        return (
            f"another pending decision acts on {on} and rests on more recent data "
            f"(through {winner.as_of}, against {loser.as_of})"
        )
    return f"a later pending decision acts on {on}, on data as recent (through {winner.as_of})"


def resolve_conflicts(
    conn: Connection, decision: DecisionView, now: datetime
) -> list[DecisionView]:
    """Supersede what conflicts with a newly proposed decision: the other pending decisions
    acting on an entity it acts on, unless one of them rests on more recent data, in which case
    the new decision is the one superseded. Returns the decisions superseded."""
    mine = targets(decision)
    rivals = []
    for other_id in conn.execute(
        text(
            "SELECT decision_id FROM decisions WHERE store_id = :s AND status = 'proposed' "
            "AND decision_id <> :d ORDER BY created_at FOR UPDATE"
        ),
        {"s": decision.store_id, "d": decision.decision_id},
    ).scalars():
        other = get(conn, decision.store_id, other_id)
        shared = shared_targets(mine, targets(other))
        if shared:
            rivals.append((other, shared))
    newer = [(o, shared) for o, shared in rivals if o.as_of > decision.as_of]
    if newer:
        winner, shared = max(newer, key=lambda r: (r[0].as_of, r[0].created_at))
        return [supersede(conn, decision, winner, _reason(shared, winner, decision), now)]
    return [supersede(conn, o, decision, _reason(shared, decision, o), now) for o, shared in rivals]


def supersede(
    conn: Connection, loser: DecisionView, winner: DecisionView, reason: str, now: datetime
) -> DecisionView:
    """`loser` leaves the pending decisions for good, linked to `winner`."""
    conn.execute(
        text(
            "UPDATE decisions SET status = 'superseded', superseded_by = :w, "
            "superseded_reason = :r WHERE store_id = :s AND decision_id = :d"
        ),
        {"w": winner.decision_id, "r": reason, "s": loser.store_id, "d": loser.decision_id},
    )
    append_audit(
        conn,
        loser.store_id,
        actor="system:decisions",
        action="decision.superseded",
        payload={
            "decision_id": str(loser.decision_id),
            "superseded_by": str(winner.decision_id),
            "reason": reason,
        },
        occurred_at=now,
    )
    return get(conn, loser.store_id, loser.decision_id)


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
    rows = list(
        conn.execute(
            text(
                "SELECT * FROM decision_options WHERE store_id = :s AND decision_id = :d "
                "ORDER BY rank"
            ),
            {"s": store_id, "d": decision_id},
        )
    )
    currency = row.currency.strip()
    refs = set().union(*(entity_refs(o.entity, o.actions) for o in rows))
    names = load_entity_names(conn, store_id, refs)
    options = [
        OptionRow(
            option_id=o.option_id,
            label=option_label(o.kind, o.entity, o.actions, names, currency),
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
        for o in rows
    ]
    recommended = next(o for o in options if o.option_id == row.recommended_option_id)
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
        currency=currency,
        as_of=row.as_of.isoformat(),
        expires_at=row.expires_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        options=options,
        superseded_by=row.superseded_by,
        superseded_reason=row.superseded_reason,
        label=decision_label(recommended.label),
        do_nothing=DoNothing(impact_fact_id=row.do_nothing_fact_id),
        outcomes=outcomes_of(conn, store_id, decision_id),
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
    origin: Origin | None = None,
    now: datetime | None = None,
    meta_links: dict[str, str] | None = None,
) -> DecisionView:
    """Approve an option, or reject the decision, exactly once. Approval queues the option's
    actions (actions and outbox rows) in the same transaction. The audit entry records who, by
    which channel and from where (`origin`: session or token, request, user agent, link)."""
    now = now or datetime.now(UTC)
    decision = get(conn, store_id, decision_id, lock=True)
    if _expire_if_due(conn, decision, now):
        raise DecisionError("expired", "the decision expired before it was decided")
    if decision.status is DecisionStatus.SUPERSEDED:
        raise DecisionError(
            "superseded",
            f"the decision was superseded by {decision.superseded_by}: "
            f"{decision.superseded_reason}",
        )
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
            "origin": (origin or Origin()).payload(),
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


def link_available(conn: Connection, claims: LinkClaims, now: datetime | None = None) -> bool:
    """The link exists, is unused and has not expired (reading it changes nothing)."""
    now = now or datetime.now(UTC)
    return bool(
        conn.execute(
            text(
                "SELECT 1 FROM approval_links WHERE store_id = :s AND link_id = :l "
                "AND used_at IS NULL AND expires_at > :now"
            ),
            {"now": now, "s": claims.store_id, "l": claims.link_id},
        ).scalar()
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
