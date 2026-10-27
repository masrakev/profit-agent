"""Attribute a net profit change between two equal-length periods to drivers, as facts.

Inputs are exact facts (per product, per campaign, store fixed costs and net profit) for the
baseline and the current period. Contributions are exact facts too (`method = shapley_v1`):

- `profit_delta` (store): current net_profit - baseline net_profit;
- `profit_driver.<driver>` at store scope (level 1), whose parents are its level-2 facts;
- `profit_driver.<driver>` at product scope (volume, mix, price, unit_cost, fees, refunds) and
  campaign scope (ad_spend) (level 2), whose parents are the input facts of both periods.

All carry the current period as `period` and the baseline as `baseline`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from app.causes.drivers import (
    LEVEL1_DRIVERS,
    Decomposition,
    Driver,
    PeriodFigures,
    ProductFigures,
    decompose,
)
from app.causes.shapley import round_to_grid
from app.domain.hashing import canonical_json, sha256_hex
from app.facts import sql
from app.facts.arith import exact_sub
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

METHOD = "shapley_v1"
VERSION = 1
PRODUCT_FIGURES = ("revenue", "units", "cogs", "fees", "refunds")
MIN_EXPONENT = -10


class AttributionUnavailableError(ValueError):
    """An input fact is undefined (e.g. rows in a foreign currency)."""


@dataclass(frozen=True)
class Contribution:
    scope: Scope
    value: Decimal
    fact_id: int


@dataclass(frozen=True)
class ProfitAttribution:
    baseline: Period
    current: Period
    delta: Decimal
    delta_fact_id: int
    level1: dict[Driver, Contribution]
    level2: dict[Driver, list[Contribution]]  # sorted by value, most negative first

    def largest_negative(self) -> Driver | None:
        driver, contribution = min(self.level1.items(), key=lambda kv: (kv[1].value, kv[0]))
        return driver if contribution.value < 0 else None


def _figures(engine: FactEngine, period: Period) -> tuple[PeriodFigures, dict[str, Fact]]:
    """Exact input figures of a period and the facts they come from (keyed by role)."""
    conn, store = engine.conn, engine.store_id
    facts: dict[str, Fact] = {}

    def value(role: str, formula_id: str, scope: Scope) -> Decimal:
        fact = engine.fact(formula_id, scope, period)
        if fact.value is None:
            raise AttributionUnavailableError(f"{formula_id} is undefined: {fact.undefined_reason}")
        facts[role] = fact
        return fact.value

    products = {}
    for pid in sql.product_ids(conn, store):
        scope = Scope.product(pid)
        amounts = {name: value(f"{name}:{pid}", name, scope) for name in PRODUCT_FIGURES}
        products[pid] = ProductFigures(**amounts)
    spend = {
        cid: value(f"ad_spend:{cid}", "ad_spend", Scope.campaign(cid))
        for cid in sql.campaign_ids(conn, store)
    }
    fixed = value("fixed_costs", "fixed_costs", Scope.store())
    value("net_profit", "net_profit", Scope.store())
    value("units", "units", Scope.store())
    return PeriodFigures(products, spend, fixed), facts


def _comparison_fact(
    engine: FactEngine,
    formula_id: str,
    scope: Scope,
    baseline: Period,
    current: Period,
    value: Decimal,
    parents: Sequence[tuple[str, Fact]],
    method: str | None,
) -> Fact:
    inputs_hash = sha256_hex(canonical_json(sorted([role, f.fact_hash] for role, f in parents)))
    fact = Fact(
        store_id=engine.store_id,
        formula_id=formula_id,
        formula_version=VERSION,
        kind=FactKind.EXACT,
        scope=scope,
        period=current,
        baseline=baseline,
        status=FactStatus.DEFINED,
        value=value,
        unit=Unit.MONEY,
        currency=engine.currency,
        method=method,
        inputs_hash=inputs_hash,
        lineage=Lineage(
            parents=tuple(ParentRef(role=role, fact_hash=f.fact_hash) for role, f in parents)
        ),
    )
    return engine.persist(engine.adopt(fact))


def _quantum(delta: Decimal) -> Decimal:
    exponent = delta.as_tuple().exponent
    assert isinstance(exponent, int)
    return Decimal(1).scaleb(min(MIN_EXPONENT, exponent))


def attribute_profit_change(
    engine: FactEngine, baseline: Period, current: Period
) -> ProfitAttribution:
    """Decompose net_profit(current) - net_profit(baseline) and persist every contribution."""
    if baseline.end > current.start:
        raise ValueError("the baseline must precede the current period")
    base_figures, base_facts = _figures(engine, baseline)
    cur_figures, cur_facts = _figures(engine, current)
    for figures, facts in ((base_figures, base_facts), (cur_figures, cur_facts)):
        net = facts["net_profit"].value
        if net is None or figures.net_profit() != Fraction(net):  # pragma: no cover
            raise ArithmeticError("driver figures do not reconcile with the net_profit fact")
    decomposition: Decomposition = decompose(base_figures, cur_figures)
    delta = exact_sub(
        cur_facts["net_profit"].value or Decimal(0), base_facts["net_profit"].value or Decimal(0)
    )
    quantum = _quantum(delta)

    def both(*roles: str) -> list[tuple[str, Fact]]:
        return [(f"current.{r}", cur_facts[r]) for r in roles] + [
            (f"baseline.{r}", base_facts[r]) for r in roles
        ]

    delta_fact = _comparison_fact(
        engine, "profit_delta", Scope.store(), baseline, current, delta, both("net_profit"), None
    )
    rounded_l1 = dict(
        zip(
            LEVEL1_DRIVERS,
            round_to_grid([decomposition.level1[d] for d in LEVEL1_DRIVERS], delta, quantum),
            strict=True,
        )
    )
    level1: dict[Driver, Contribution] = {}
    level2: dict[Driver, list[Contribution]] = {}
    for driver in LEVEL1_DRIVERS:
        items = sorted(decomposition.level2[driver].items(), key=lambda kv: str(kv[0][1]))
        parts = round_to_grid([v for _, v in items], rounded_l1[driver], quantum) if items else []
        children: list[tuple[str, Fact]] = []
        contributions: list[Contribution] = []
        for ((kind, entity_id), _), value in zip(items, parts, strict=True):
            scope = Scope(kind=ScopeKind(kind), id=entity_id)
            if kind == "campaign":
                parents = both(f"ad_spend:{entity_id}")
            elif driver is Driver.REFUNDS:
                parents = both(f"refunds:{entity_id}")
            else:
                parents = both(*(f"{n}:{entity_id}" for n in PRODUCT_FIGURES[:4]), "units")
            fact = _comparison_fact(
                engine, f"profit_driver.{driver}", scope, baseline, current, value, parents, METHOD
            )
            children.append((f"{kind}:{entity_id}", fact))
            contributions.append(Contribution(scope, value, fact.id or 0))
        top = _comparison_fact(
            engine,
            f"profit_driver.{driver}",
            Scope.store(),
            baseline,
            current,
            rounded_l1[driver],
            children or both("fixed_costs"),
            METHOD,
        )
        level1[driver] = Contribution(Scope.store(), rounded_l1[driver], top.id or 0)
        level2[driver] = sorted(contributions, key=lambda c: (c.value, str(c.scope.id)))
    return ProfitAttribution(
        baseline=baseline,
        current=current,
        delta=delta,
        delta_fact_id=delta_fact.id or 0,
        level1=level1,
        level2=level2,
    )
