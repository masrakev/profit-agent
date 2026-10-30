"""Golden scenarios with a recorded decision (questions q25-q26, Task 4 B4).

Each recipe takes its base golden store, puts it in the simulator 14 days before its data end,
proposes the options of the labelled cause, approves one of a given kind, executes it on the
simulator, lets the store live for some days, and measures the outcome: with 7 days the effect
is measured; with 2 days the measurement abstains (too little post-decision history).
"""

from dataclasses import dataclass, replace
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Engine, text

from app.causal.outcome import measure
from app.db import tenant_transaction
from app.decisions.options import UNDERFUNDED_CAMPAIGN, build_options
from app.decisions.store import Channel, Verdict, decide, propose
from app.executor.simulator import SimulatorAdapter
from app.executor.worker import Executor
from app.facts.engine import FactEngine
from app.twin import fit_twin
from bench.scenarios.manifest import ScenarioManifest
from bench.simulator import advance, register


@dataclass(frozen=True)
class DecisionRecipe:
    cause: str
    option_kind: str  # the approved option's kind
    observe_days: int
    days_before_end: int = 14


RECIPES = {
    "golden-cpa_drift-with-decision": DecisionRecipe("cpa_drift", "reduce_budget", 7),
    "golden-short-history-decision": DecisionRecipe(UNDERFUNDED_CAMPAIGN, "increase_budget", 2),
}


def _campaign(manifest: ScenarioManifest) -> UUID:
    for label in manifest.labels:
        for entity in label.entities:
            if entity.kind.value == "campaign" and entity.id is not None:
                return entity.id
    for condition in manifest.condition_labels:
        for entity in condition.entities:
            if entity.kind.value == "campaign" and entity.id is not None:
                return entity.id
    raise ValueError(f"{manifest.scenario_id}: no labelled campaign")


def set_up(engine: Engine, manifest: ScenarioManifest) -> UUID:
    """Load the store and record its decision; returns the store id."""
    recipe = RECIPES[manifest.scenario_id]
    store = register(engine, manifest, manifest.config.days - recipe.days_before_end)
    entity = f"campaign:{_campaign(manifest)}"
    with tenant_transaction(engine, store) as conn:
        model = fit_twin(conn, store)
        options = build_options(model, recipe.cause, entity, floor_monthly=Decimal(100))
        chosen = next(o for o in options.options if o.kind.value == recipe.option_kind)
        options = replace(options, recommended=chosen.option_id)
        decision = propose(conn, FactEngine(conn, store), model, options, source="owner")
        decide(
            conn,
            store,
            decision.decision_id,
            chosen.option_id,
            Verdict.APPROVED,
            channel=Channel.API,
            actor="owner:golden",
        )
    Executor(engine, {"simulator": SimulatorAdapter(engine)}).run_once()
    advance(engine, store, recipe.observe_days)
    with tenant_transaction(engine, store) as conn:
        action = conn.execute(
            text(
                "SELECT action_id FROM actions WHERE store_id = :s AND decision_id = :d "
                "AND status = 'executed'"
            ),
            {"s": store, "d": decision.decision_id},
        ).scalar_one()
        measure(conn, store, action)
    return store
