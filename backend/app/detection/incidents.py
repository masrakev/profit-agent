"""Group symptoms into incidents and rank candidate root causes.

Grouping: two product/campaign symptoms belong together when their entities are linked in the
entity graph (same entity, or campaign <-> promoted product, at most one campaign hop apart) and
their active intervals overlap within `gap_days`. A store-level symptom joins the most severe
time-overlapping group that contains a symptom explaining it (see STORE_EXPLAINED_BY); otherwise
store symptoms group together into a store incident.

Ranking: every symptom votes for (fault family, entity) candidates with a fixed weight times its
capped score. The profit attribution adds a bonus to the candidate implied by the largest
negative driver. Symptoms re-classified as data quality vote for `tracking_break` only.
"""

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.causes.drivers import Driver
from app.causes.profit import ProfitAttribution
from app.detection.config import DetectionConfig
from app.detection.models import (
    ALERT_RANK,
    AlertLevel,
    Candidate,
    EntityRef,
    FaultFamily,
    Incident,
    Symptom,
    SymptomCategory,
)
from app.domain.hashing import canonical_json, sha256_hex
from app.facts.model import ScopeKind

F = FaultFamily
SELF, STORE, PROMOTERS = "self", "store", "promoters"

# detector id -> (family, which entity, weight)
VOTES: dict[str, tuple[tuple[FaultFamily, str, float], ...]] = {
    "campaign_cpa_z": ((F.CPA_DRIFT, SELF, 1.0),),
    "campaign_cpa_cusum": ((F.CPA_DRIFT, SELF, 1.0),),
    "campaign_profit_negative": ((F.CPA_DRIFT, SELF, 0.5), (F.CANNIBALIZATION, SELF, 0.3)),
    "campaign_incrementality": ((F.CANNIBALIZATION, SELF, 1.5),),
    "campaign_attribution_collapse": ((F.TRACKING_BREAK, SELF, 2.0),),
    "product_cover_below_lead_time": ((F.STOCKOUT_ON_PROMOTED, SELF, 2.0),),
    "product_units_z": ((F.STOCKOUT_ON_PROMOTED, SELF, 0.5), (F.CPA_DRIFT, PROMOTERS, 0.3)),
    "product_unit_cost_z": ((F.SUPPLIER_COST_INCREASE, SELF, 1.5),),
    "product_unit_fee_z": ((F.FEE_INCREASE, SELF, 1.5),),
    "store_payment_fee_rate_z": ((F.FEE_INCREASE, STORE, 1.5),),
    "product_refund_rate_band": ((F.REFUND_SPIKE, SELF, 1.5),),
    "store_gross_margin_rate_z": ((F.MIX_SHIFT, STORE, 0.6),),
    "store_gross_margin_rate_cusum": ((F.MIX_SHIFT, STORE, 0.6),),
}
DATA_QUALITY_VOTE = 1.0
# A store-level symptom joins a product/campaign incident only if that incident has a symptom
# that explains it (a unit cost increase lowers the store's gross margin rate). Otherwise store
# symptoms form their own incident: grouping by time alone attached them to unrelated problems.
STORE_EXPLAINED_BY: dict[str, frozenset[str]] = {
    "store_gross_margin_rate_z": frozenset({"product_unit_cost_z"}),
    "store_gross_margin_rate_cusum": frozenset({"product_unit_cost_z"}),
}
# Campaign and product-sales symptoms that a stockout on a promoted product explains away.
STOCKOUT_EXPLAINS = frozenset(
    {"campaign_cpa_z", "campaign_cpa_cusum", "campaign_profit_negative", "product_units_z"}
)
STOCKOUT_EXPLAINED_VOTE = 0.5


@dataclass(frozen=True)
class EntityGraph:
    """Campaign -> promoted products."""

    promoted: Mapping[UUID, frozenset[UUID]]

    def promoters(self, product_id: UUID) -> list[UUID]:
        return sorted((c for c, ps in self.promoted.items() if product_id in ps), key=str)

    def neighbours(self, entity: EntityRef) -> set[EntityRef]:
        """Entities at most one campaign hop away (excluding the store)."""
        if entity.id is None:
            return set()
        if entity.kind is ScopeKind.CAMPAIGN:
            products = self.promoted.get(entity.id, frozenset())
            out = {EntityRef.product(p) for p in products}
            out |= {EntityRef.campaign(c) for p in products for c in self.promoters(p)}
            return out | {entity}
        campaigns = self.promoters(entity.id)
        out = {EntityRef.campaign(c) for c in campaigns}
        out |= {EntityRef.product(p) for c in campaigns for p in self.promoted[c]}
        return out | {entity}


def _overlap(a: Symptom, b: Symptom, gap: int) -> bool:
    return (a.first_seen - b.last_seen).days <= gap and (b.first_seen - a.last_seen).days <= gap


def _capped(symptom: Symptom, cfg: DetectionConfig) -> float:
    return min(symptom.score, cfg.severity.score_cap)


def severity_score(symptoms: list[Symptom], cfg: DetectionConfig) -> float:
    scores = sorted((_capped(s, cfg) for s in symptoms), reverse=True)
    return scores[0] + 0.25 * sum(scores[1:]) if scores else 0.0


def group_symptoms(
    symptoms: list[Symptom], graph: EntityGraph, cfg: DetectionConfig
) -> list[list[Symptom]]:
    gap = cfg.incidents.gap_days
    local = [s for s in symptoms if s.entity.kind is not ScopeKind.STORE]
    parent = list(range(len(local)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(local):
        related = graph.neighbours(a.entity)
        for j in range(i):
            b = local[j]
            # Data-quality and profitability problems never share an incident.
            if b.category is a.category and b.entity in related and _overlap(a, b, gap):
                parent[find(i)] = find(j)
    groups: dict[int, list[Symptom]] = defaultdict(list)
    for i, s in enumerate(local):
        groups[find(i)].append(s)
    result = list(groups.values())
    orphans: list[Symptom] = []
    for s in (s for s in symptoms if s.entity.kind is ScopeKind.STORE):
        explainers = STORE_EXPLAINED_BY.get(s.detector_id, frozenset())
        overlapping = [
            g
            for g in result
            if g[0].category is s.category
            and any(other.detector_id in explainers for other in g)
            and any(_overlap(s, other, gap) for other in g)
        ]
        if overlapping:
            max(overlapping, key=lambda g: severity_score(g, cfg)).append(s)
        else:
            orphans.append(s)
    # Store symptoms without a local group: one incident per time-overlapping cluster.
    clusters: list[list[Symptom]] = []
    for s in sorted(orphans, key=lambda s: s.first_seen):
        if clusters and any(_overlap(s, o, gap) for o in clusters[-1]):
            clusters[-1].append(s)
        else:
            clusters.append([s])
    return result + clusters


def _vote_entities(symptom: Symptom, mode: str, graph: EntityGraph) -> list[EntityRef]:
    if mode == STORE:
        return [EntityRef.store()]
    if mode == PROMOTERS and symptom.entity.id is not None:
        return [EntityRef.campaign(c) for c in graph.promoters(symptom.entity.id)]
    return [symptom.entity]


def _driver_candidates(
    attribution: ProfitAttribution, graph: EntityGraph, cfg: DetectionConfig
) -> list[tuple[FaultFamily, EntityRef, float, str]]:
    """Candidates implied by the largest negative level-1 driver, weighted by its share."""
    negatives = {d: c.value for d, c in attribution.level1.items() if c.value < 0}
    driver = attribution.largest_negative()
    total = -sum(negatives.values())
    if driver is None or total == 0:
        return []
    share = float(-negatives[driver] / total)
    if share < cfg.attribution.min_driver_share:
        return []
    bonus = cfg.attribution.bonus * share
    evidence = f"attribution:{driver}"
    worst = attribution.level2[driver][0] if attribution.level2[driver] else None
    top = None if worst is None or worst.value >= 0 else worst.scope
    store = EntityRef.store()
    if driver is Driver.MIX:
        return [(F.MIX_SHIFT, store, bonus, evidence)]
    if top is None or top.id is None:
        return []
    entity = EntityRef(kind=top.kind, id=top.id)
    if driver is Driver.UNIT_COST:
        return [(F.SUPPLIER_COST_INCREASE, entity, bonus, evidence)]
    if driver is Driver.REFUNDS:
        return [(F.REFUND_SPIKE, entity, bonus, evidence)]
    if driver is Driver.AD_SPEND:
        return [(F.CANNIBALIZATION, entity, bonus, evidence)]
    if driver is Driver.FEES:
        fees_total = -sum(c.value for c in attribution.level2[driver] if c.value < 0)
        concentrated = worst is not None and fees_total and -worst.value / fees_total >= 0.5
        return [(F.FEE_INCREASE, entity if concentrated else store, bonus, evidence)]
    if driver is Driver.VOLUME:
        promoters = [EntityRef.campaign(c) for c in graph.promoters(top.id)]
        return [(F.STOCKOUT_ON_PROMOTED, entity, bonus / 2, evidence)] + [
            (F.CPA_DRIFT, c, bonus / 2, evidence) for c in promoters
        ]
    return []


def rank_candidates(
    symptoms: list[Symptom],
    graph: EntityGraph,
    cfg: DetectionConfig,
    attribution: ProfitAttribution | None,
) -> list[Candidate]:
    scores: dict[tuple[FaultFamily, EntityRef], float] = defaultdict(float)
    evidence: dict[tuple[FaultFamily, EntityRef], set[str]] = defaultdict(set)
    stocked_out = {
        s.entity.id
        for s in symptoms
        if s.detector_id == "product_cover_below_lead_time" and s.entity.id is not None
    }
    for s in symptoms:
        weight = _capped(s, cfg)
        votes = VOTES.get(s.detector_id, ())
        targets: list[EntityRef] | None = None
        if s.category is SymptomCategory.DATA_QUALITY and all(
            family is not F.TRACKING_BREAK for family, _, _ in votes
        ):
            # A symptom explained by an attribution collapse supports the tracking break only.
            votes = ((F.TRACKING_BREAK, SELF, DATA_QUALITY_VOTE),)
        elif s.detector_id in STOCKOUT_EXPLAINS and s.entity.id is not None:
            # A campaign losing purchases because a promoted product is out of stock (or that
            # product's own sales drop) is explained by the stockout.
            explained = sorted(
                (
                    p
                    for p in stocked_out
                    if p == s.entity.id or p in graph.promoted.get(s.entity.id, ())
                ),
                key=str,
            )
            if explained:
                votes = ((F.STOCKOUT_ON_PROMOTED, SELF, STOCKOUT_EXPLAINED_VOTE),)
                targets = [EntityRef.product(p) for p in explained]
        for family, mode, vote in votes:
            for entity in targets or _vote_entities(s, mode, graph):
                scores[(family, entity)] += vote * weight
                evidence[(family, entity)].add(s.detector_id)
    if attribution is not None and any(
        s.category is SymptomCategory.PROFITABILITY for s in symptoms
    ):
        for family, entity, bonus, why in _driver_candidates(attribution, graph, cfg):
            scores[(family, entity)] += bonus
            evidence[(family, entity)].add(why)
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0][0].value, str(kv[0][1])))
    return [
        Candidate(
            family=f, entity=e, score=round(score, 6), evidence=tuple(sorted(evidence[(f, e)]))
        )
        for (f, e), score in ranked
    ]


@dataclass(frozen=True)
class Assessment:
    """Economic assessment of an incident (see detection.impact)."""

    alert: AlertLevel
    material: bool
    loss: Decimal = Decimal(0)  # P50 monthly profit loss, for ordering
    fact_id: int | None = None  # `expected_monthly_impact` estimate fact


UNGATED = Assessment(AlertLevel.NORMAL, True)
DATA_QUALITY_ALERT = Assessment(AlertLevel.DATA_QUALITY, False)


def build_incidents(
    symptoms: list[Symptom],
    graph: EntityGraph,
    cfg: DetectionConfig,
    attribution_for: Callable[[list[Symptom]], ProfitAttribution | None],
    assess: Callable[[list[Symptom]], Assessment] | None = None,
) -> list[Incident]:
    """Incidents ordered as the owner sees them: alert level (critical, high, data quality,
    normal, watchlist), then monthly loss, then statistical severity.

    `assess(group)` gives each profitability group its impact and alert level (without it,
    every profitability group is an ungated `normal` alert). Only the first profitability group
    in that order gets a profit attribution (`attribution_for(group)`), the costly step.
    """
    groups = group_symptoms(symptoms, graph, cfg)
    for group in groups:
        group.sort(key=lambda s: (s.first_seen, s.detector_id, str(s.entity)))

    def is_profitability(group: list[Symptom]) -> bool:
        return any(s.category is SymptomCategory.PROFITABILITY for s in group)

    assessments = [
        (assess(g) if assess else UNGATED) if is_profitability(g) else DATA_QUALITY_ALERT
        for g in groups
    ]

    def order(i: int) -> tuple[int, Decimal, float, int]:
        a, g = assessments[i], groups[i]
        return (ALERT_RANK[a.alert], -a.loss, -severity_score(g, cfg), g[0].first_seen.toordinal())

    ranked = sorted(range(len(groups)), key=order)
    primary = next((i for i in ranked if is_profitability(groups[i])), None)
    primary_attribution = attribution_for(groups[primary]) if primary is not None else None
    incidents: list[Incident] = []
    for i in ranked:
        group, assessment = groups[i], assessments[i]
        attribution = primary_attribution if i == primary else None
        entities = tuple(sorted({s.entity for s in group}, key=str))
        first = min(s.first_seen for s in group)
        incident_id = (
            "inc-"
            + sha256_hex(
                canonical_json({"first_seen": first, "entities": [str(e) for e in entities]})
            )[:12]
        )
        incidents.append(
            Incident(
                incident_id=incident_id,
                category=(
                    SymptomCategory.PROFITABILITY
                    if is_profitability(group)
                    else SymptomCategory.DATA_QUALITY
                ),
                severity_score=round(severity_score(group, cfg), 6),
                first_seen=first,
                last_seen=max(s.last_seen for s in group),
                entities=entities,
                symptoms=tuple(group),
                candidates=tuple(rank_candidates(group, graph, cfg, attribution)),
                attribution_fact_ids=(
                    ()
                    if attribution is None
                    else (
                        attribution.delta_fact_id,
                        *(c.fact_id for c in attribution.level1.values()),
                    )
                ),
                alert=assessment.alert,
                material=assessment.material,
                monthly_impact_fact_id=assessment.fact_id,
            )
        )
    return incidents
