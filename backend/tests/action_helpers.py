"""Shared setup for decision, executor and red-team tests: simulator stores and decisions."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text

from app.agent.contracts import ActionFamily
from app.db import tenant_transaction
from app.decisions.options import Option, OptionKind, OptionSet, Reversibility
from app.decisions.store import Channel, DecisionView, Verdict, decide, propose
from app.executor.adapters import Adapter
from app.executor.simulator import SimulatorAdapter
from app.executor.worker import Executor
from app.facts.engine import FactEngine
from app.twin import Action, ActionKind, fit_twin
from bench.scenarios.manifest import load_suite
from bench.simulator import register


@dataclass
class Clock:
    """Real time plus what the test advanced: never behind a row stamped a moment ago."""

    offset: timedelta = field(default_factory=timedelta)

    def __call__(self) -> datetime:
        return datetime.now(UTC) + self.offset

    @property
    def now(self) -> datetime:
        return self()

    def advance(self, **kwargs: float) -> None:
        self.offset += timedelta(**kwargs)


def simulator_store(engine: Engine, scenario_id: str, today: int = 106) -> dict[str, Any]:
    manifest = next(m for m in load_suite("dev") if m.scenario_id == scenario_id)
    store = register(engine, manifest, today)
    data = manifest.generate()
    label = manifest.labels[0]
    return {
        "id": store,
        "manifest": manifest,
        "campaigns": [c.id for c in data.campaigns],
        "product": next((e.id for e in label.entities if e.kind.value == "product"), None),
        "campaign": next((e.id for e in label.entities if e.kind.value == "campaign"), None),
    }


def option_set(campaign: UUID, *, change: str | None = None, label: str = "x") -> OptionSet:
    """One executable option on a campaign: a budget change, or a pause."""
    action = (
        Action(kind=ActionKind.PAUSE_CAMPAIGN, entity=campaign)
        if change is None
        else Action(kind=ActionKind.CHANGE_BUDGET, entity=campaign, change=Decimal(change))
    )
    kind = OptionKind.PAUSE_CAMPAIGN if change is None else OptionKind.REDUCE_BUDGET
    option = Option(
        f"test:{label}:{campaign}",
        kind,
        ActionFamily.PAUSE_OR_REDUCE_CAMPAIGN,
        f"campaign:{campaign}",
        (action,),
        Reversibility.REVERSIBLE,
        (),
        (),
    )
    return OptionSet(
        cause="cpa_drift",
        entity=f"campaign:{campaign}",
        options=(option,),
        recommended=option.option_id,
        reason="test",
        floor=Decimal("46.67"),
    )


def approved(
    engine: Engine,
    store: UUID,
    options: OptionSet,
    *,
    now: datetime | None = None,
    meta_links: dict[str, str] | None = None,
) -> DecisionView:
    with tenant_transaction(engine, store) as conn:
        model = fit_twin(conn, store)
        d = propose(conn, FactEngine(conn, store), model, options, source="owner", now=now)
        return decide(
            conn,
            store,
            d.decision_id,
            d.recommended_option_id,
            Verdict.APPROVED,
            channel=Channel.API,
            actor="owner",
            now=now,
            meta_links=meta_links,
        )


@dataclass
class Rig:
    engine: Engine
    clock: Clock = field(default_factory=Clock)
    extra: dict[str, Adapter] = field(default_factory=dict)
    meta_links: dict[str, str] = field(default_factory=dict)
    after_apply: Callable[[UUID], None] | None = None

    def executor(self) -> Executor:
        return Executor(
            self.engine,
            {"simulator": SimulatorAdapter(self.engine), **self.extra},
            meta_links=self.meta_links,
            clock=self.clock,
            after_apply=self.after_apply,
        )


def actions(engine: Engine, store: UUID, decision: UUID) -> list[Any]:
    with tenant_transaction(engine, store) as conn:
        return list(
            conn.execute(
                text(
                    "SELECT a.*, o.status AS outbox_status, o.attempts AS outbox_attempts "
                    "FROM actions a JOIN outbox o ON o.action_id = a.action_id "
                    "WHERE a.store_id = :s AND a.decision_id = :d ORDER BY a.created_at"
                ),
                {"s": store, "d": decision},
            )
        )


def audit_actions(engine: Engine, store: UUID, prefix: str) -> list[Any]:
    with tenant_transaction(engine, store) as conn:
        return list(
            conn.execute(
                text(
                    "SELECT action, payload FROM audit_log WHERE store_id = :s "
                    "AND action LIKE :p ORDER BY seq"
                ),
                {"s": store, "p": f"{prefix}%"},
            )
        )


def campaign_row(engine: Engine, store: UUID, campaign: UUID) -> Any:
    with tenant_transaction(engine, store) as conn:
        return conn.execute(
            text("SELECT status, daily_budget FROM ad_campaigns WHERE store_id = :s AND id = :c"),
            {"s": store, "c": campaign},
        ).one()
