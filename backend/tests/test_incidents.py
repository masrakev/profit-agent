"""Incident grouping and root-cause ranking on hand-built symptoms."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from app.causes.drivers import Driver
from app.causes.profit import Contribution, ProfitAttribution
from app.detection.config import default_config
from app.detection.incidents import (
    EntityGraph,
    build_incidents,
    group_symptoms,
    rank_candidates,
    severity_score,
)
from app.detection.models import (
    EntityRef,
    FaultFamily,
    Severity,
    Symptom,
    SymptomCategory,
)
from app.facts.model import Period, Scope

CFG = default_config()
P1, P2, P3 = UUID(int=1), UUID(int=2), UUID(int=3)
C1, C2 = UUID(int=11), UUID(int=12)
GRAPH = EntityGraph({C1: frozenset({P1, P2}), C2: frozenset({P3})})
DAY0 = date(2026, 8, 1)
F = FaultFamily


def sym(
    detector: str,
    entity: EntityRef,
    day: int,
    *,
    last: int | None = None,
    score: float = 2.0,
    category: SymptomCategory = SymptomCategory.PROFITABILITY,
) -> Symptom:
    return Symptom(
        detector_id=detector,
        entity=entity,
        metric="m",
        category=category,
        severity=Severity.MEDIUM,
        score=score,
        first_seen=DAY0 + timedelta(days=day),
        last_seen=DAY0 + timedelta(days=last if last is not None else day + 3),
        baseline_fact_ids=(1,),
        current_fact_ids=(2,),
    )


def attribution(driver: Driver, top: Scope | None, value: str = "-100") -> ProfitAttribution:
    period = Period(start=datetime(2026, 9, 1, tzinfo=UTC), end=datetime(2026, 9, 29, tzinfo=UTC))
    base = Period(start=datetime(2026, 7, 1, tzinfo=UTC), end=datetime(2026, 7, 29, tzinfo=UTC))
    level1 = {d: Contribution(Scope.store(), Decimal(0), i) for i, d in enumerate(Driver)}
    level1[driver] = Contribution(Scope.store(), Decimal(value), 99)
    level2 = {d: [] for d in Driver}
    if top is not None:
        level2[driver] = [Contribution(top, Decimal(value), 100)]
    return ProfitAttribution(base, period, Decimal(value), 98, level1, level2)


def test_entity_graph_neighbourhoods() -> None:
    assert GRAPH.promoters(P1) == [C1]
    assert EntityRef.product(P2) in GRAPH.neighbours(EntityRef.product(P1))
    assert EntityRef.product(P3) not in GRAPH.neighbours(EntityRef.campaign(C1))
    assert GRAPH.neighbours(EntityRef.store()) == set()


def test_grouping_by_graph_time_and_category() -> None:
    a = sym("campaign_cpa_z", EntityRef.campaign(C1), 0)
    b = sym("product_units_z", EntityRef.product(P2), 2)  # promoted by C1, overlapping
    far = sym("product_units_z", EntityRef.product(P1), 40)  # same graph, much later
    other = sym("product_units_z", EntityRef.product(P3), 1)  # unrelated campaign
    dq = sym(
        "campaign_attribution_collapse",
        EntityRef.campaign(C1),
        1,
        category=SymptomCategory.DATA_QUALITY,
    )
    store_hit = sym("store_gross_margin_rate_z", EntityRef.store(), 3, score=0.5)
    lonely_store = sym("store_payment_fee_rate_z", EntityRef.store(), 80)
    groups = group_symptoms([a, b, far, other, dq, store_hit, lonely_store], GRAPH, CFG)
    as_sets = sorted(sorted(s.detector_id + str(s.first_seen) for s in g) for g in groups)
    assert len(groups) == 5
    together = next(g for g in groups if a in g)
    assert b in together
    assert dq not in together
    assert store_hit in together or store_hit in next(g for g in groups if other in g)
    assert [lonely_store] in groups
    assert as_sets  # deterministic ordering is exercised


def test_ranking_votes_and_explaining_away() -> None:
    stockout = sym("product_cover_below_lead_time", EntityRef.product(P1), 0, score=2.5)
    cpa = sym("campaign_cpa_cusum", EntityRef.campaign(C1), 1, score=3.0)
    ranked = rank_candidates([stockout, cpa], GRAPH, CFG, None)
    assert (ranked[0].family, ranked[0].entity) == (F.STOCKOUT_ON_PROMOTED, EntityRef.product(P1))
    assert all(c.family is not F.CPA_DRIFT for c in ranked)  # explained by the stockout
    alone = rank_candidates([cpa], GRAPH, CFG, None)
    assert alone[0].family is F.CPA_DRIFT
    units = rank_candidates([sym("product_units_z", EntityRef.product(P1), 0)], GRAPH, CFG, None)
    assert {c.family for c in units} == {F.STOCKOUT_ON_PROMOTED, F.CPA_DRIFT}


def test_data_quality_symptoms_vote_for_tracking_break_only() -> None:
    dq = SymptomCategory.DATA_QUALITY
    symptoms = [
        sym("campaign_attribution_collapse", EntityRef.campaign(C1), 0, category=dq),
        sym("campaign_cpa_z", EntityRef.campaign(C1), 0, category=dq),
    ]
    ranked = rank_candidates(symptoms, GRAPH, CFG, attribution(Driver.VOLUME, Scope.product(P1)))
    assert [c.family for c in ranked] == [F.TRACKING_BREAK]  # no attribution bonus for DQ


def test_attribution_bonus_by_driver() -> None:
    base = [sym("store_gross_margin_rate_z", EntityRef.store(), 0, score=1.0)]

    def top(driver: Driver, scope: Scope | None) -> tuple[FaultFamily, EntityRef]:
        ranked = rank_candidates(base, GRAPH, CFG, attribution(driver, scope))
        best = next(c for c in ranked if any(e.startswith("attribution:") for e in c.evidence))
        return best.family, best.entity

    assert top(Driver.UNIT_COST, Scope.product(P2)) == (
        F.SUPPLIER_COST_INCREASE,
        EntityRef.product(P2),
    )
    assert top(Driver.REFUNDS, Scope.product(P3)) == (F.REFUND_SPIKE, EntityRef.product(P3))
    assert top(Driver.AD_SPEND, Scope.campaign(C2)) == (F.CANNIBALIZATION, EntityRef.campaign(C2))
    assert top(Driver.FEES, Scope.product(P1)) == (F.FEE_INCREASE, EntityRef.product(P1))
    assert top(Driver.MIX, None) == (F.MIX_SHIFT, EntityRef.store())
    volume = rank_candidates(base, GRAPH, CFG, attribution(Driver.VOLUME, Scope.product(P1)))
    assert {c.family for c in volume} >= {F.STOCKOUT_ON_PROMOTED, F.CPA_DRIFT}
    # Price and fixed costs imply no fault family; a small driver share gives no bonus.
    for driver in (Driver.PRICE, Driver.FIXED_COSTS):
        assert (
            rank_candidates(base, GRAPH, CFG, attribution(driver, Scope.product(P1)))[0].family
            is F.MIX_SHIFT
        )
    positive = attribution(Driver.UNIT_COST, Scope.product(P1), value="100")
    assert len(rank_candidates(base, GRAPH, CFG, positive)) == 1
    no_level2 = attribution(Driver.UNIT_COST, None)
    assert len(rank_candidates(base, GRAPH, CFG, no_level2)) == 1


def test_build_incidents_orders_by_severity_and_attributes_the_primary_only() -> None:
    calls: list[int] = []

    def attribute(group: list[Symptom]) -> ProfitAttribution:
        calls.append(len(group))
        return attribution(Driver.UNIT_COST, Scope.product(P1))

    weak = sym("product_units_z", EntityRef.product(P3), 0, score=1.0)
    strong = sym("product_unit_cost_z", EntityRef.product(P1), 0, score=3.0)
    dq = sym(
        "campaign_attribution_collapse",
        EntityRef.campaign(C2),
        50,
        category=SymptomCategory.DATA_QUALITY,
    )
    incidents = build_incidents([weak, strong, dq], GRAPH, CFG, attribute)
    assert calls == [1]
    assert incidents[0].symptoms == (strong,)
    assert incidents[0].attribution_fact_ids[0] == 98
    assert incidents[0].candidates[0].family is F.SUPPLIER_COST_INCREASE
    assert {i.category for i in incidents} == {
        SymptomCategory.PROFITABILITY,
        SymptomCategory.DATA_QUALITY,
    }
    assert all(i.incident_id.startswith("inc-") for i in incidents)
    assert severity_score([], CFG) == 0.0
    assert build_incidents([], GRAPH, CFG, attribute) == []
