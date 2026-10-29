"""Simulated outcomes as `estimate` facts (P10/P50/P90), with their inputs as parents.

Per simulated scenario, over the horizon after the data end (store scope):

- `twin.<metric>`: the scenario;
- `twin.do_nothing.<metric>`: the same draws without any action;
- `twin.change.<metric>`: the scenario minus "do nothing".

Metrics: contribution_margin, net_profit, units, ad_spend. The value is the P50. The parents are
the exact facts of the fit window the simulation rests on.
"""

from collections.abc import Sequence
from datetime import timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from app.domain.hashing import canonical_json, sha256_hex
from app.facts.engine import FactEngine
from app.facts.model import (
    Fact,
    FactKind,
    FactStatus,
    Lineage,
    ParentRef,
    Period,
    Scope,
    ScopeKind,
    Unit,
)
from app.twin.model import METRICS, MONEY_METRICS, ActionKind, Range, Simulation, TwinModel

TWIN_METHOD = "twin_monte_carlo_v1"
FORMULA_VERSION = 1
GROUPS = ("", "do_nothing.", "change.")
CENT = Decimal("0.01")
TENTH = Decimal("0.1")


def _decimal(x: float, metric: str) -> Decimal:
    step = CENT if metric in MONEY_METRICS else TENTH
    return Decimal(repr(x)).quantize(step, rounding=ROUND_HALF_EVEN)


def input_facts(engine: FactEngine, model: TwinModel, sim: Simulation) -> list[tuple[str, Fact]]:
    """The exact facts of the fit window behind a simulation: store totals, and the facts of
    each entity the scenario acts on."""
    window = Period.days(model.as_of - timedelta(days=model.window_days), model.as_of)
    out = [
        (f"store:{m}", engine.fact(m, Scope.store(), window))
        for m in ("contribution_margin", "ad_spend", "units", "fixed_costs")
    ]
    for action in sim.scenario.actions:
        if action.entity is None:
            continue
        if action.kind in (ActionKind.CHANGE_BUDGET, ActionKind.PAUSE_CAMPAIGN):
            scope = Scope(kind=ScopeKind.CAMPAIGN, id=action.entity)
            metrics: tuple[str, ...] = ("ad_spend", "attributed_purchases")
        else:
            scope = Scope(kind=ScopeKind.PRODUCT, id=action.entity)
            metrics = ("units", "contribution_margin", "units_on_hand")
        out += [(f"{scope.kind.value}:{m}", engine.fact(m, scope, window)) for m in metrics]
    return out


def simulation_facts(
    engine: FactEngine,
    model: TwinModel,
    sim: Simulation,
    inputs: Sequence[tuple[str, Fact]],
) -> dict[str, Fact]:
    """Persist the simulation's facts; keys are their formula ids (`twin.change.net_profit`)."""
    period = Period.days(model.as_of, model.as_of + timedelta(days=sim.scenario.horizon_days))
    method = f"{TWIN_METHOD};calibration v{sim.calibration_version}"
    for _, parent in inputs:
        engine.adopt(parent)
    lineage = Lineage(parents=tuple(ParentRef(role=r, fact_hash=f.fact_hash) for r, f in inputs))
    ranges = {"": sim.totals, "do_nothing.": sim.do_nothing, "change.": sim.change}
    out: dict[str, Fact] = {}
    for group in GROUPS:
        for metric in METRICS:
            formula = f"twin.{group}{metric}"
            r: Range | None = ranges[group].get(metric)
            money = metric in MONEY_METRICS
            inputs_hash = sha256_hex(
                canonical_json(
                    {
                        "formula": formula,
                        "scenario": sim.scenario.model_dump(mode="json"),
                        "model": model.fingerprint,
                        "method": method,
                        "parents": [f.fact_hash for _, f in inputs],
                    }
                )
            )
            defined = r is not None
            fact = Fact(
                store_id=model.store_id,
                formula_id=formula,
                formula_version=FORMULA_VERSION,
                kind=FactKind.ESTIMATE,
                scope=Scope.store(),
                period=period,
                status=FactStatus.DEFINED if defined else FactStatus.UNDEFINED,
                value=_decimal(r.p50, metric) if r else None,
                p10=_decimal(r.p10, metric) if r else None,
                p50=_decimal(r.p50, metric) if r else None,
                p90=_decimal(r.p90, metric) if r else None,
                method=method if defined else None,
                undefined_reason=None if defined else (sim.undefined_reason or "not simulated"),
                unit=Unit.MONEY if money else Unit.COUNT,
                currency=model.currency if money else None,
                inputs_hash=inputs_hash,
                lineage=lineage,
            )
            out[formula] = engine.persist(engine.adopt(fact))
    return out
