"""Alert and decision messages, assembled from facts like briefings (SPEC sections 6 and 7).

An alert always has the six parts of SPEC section 6: what was detected, why it matters (the
monthly loss, a range), the evidence (the symptoms' facts, current against before), what is
still uncertain, the options with their simulated impact, and the recommended next step. A
data-quality alert says it is not a profit problem and recommends no budget action.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Connection

from app.briefings import wording
from app.briefings.content import (
    Context,
    context,
    decision_for,
    entity_ref,
    impact_of,
    incident_entity,
    top_family,
)
from app.briefings.models import Button, ButtonKind, Document, Item, Section
from app.decisions.store import DecisionView
from app.detection.models import AlertLevel, Incident
from app.detection.series import load_series

MAX_SYMPTOMS = 3
METRICS = {
    "cpa": "cost per purchase",
    "units": "units sold",
    "unit_cost": "unit cost",
    "unit_fee": "fees per unit",
    "refund_rate": "refund rate",
    "attribution_ratio": "attribution ratio",
    "inventory_cover_days": "stock cover",
    "campaign_profit": "campaign profit",
    "gross_margin_rate": "gross margin rate",
    "payment_fee_rate": "payment fee rate",
}
UNCERTAIN = (
    "The monthly loss is an estimate from the store's own history, a range rather than a "
    "forecast; the cause is ranked by code from the symptoms."
)
DATA_UNCERTAIN = (
    "Which measurement broke, and since when exactly, is not certain yet; the store's real "
    "orders are the reference."
)


def notice_context(conn: Connection, store_id: UUID, now: datetime) -> Context:
    """A context on the store's latest data (alerts and decisions are about now)."""
    end = load_series(conn, store_id)
    return context(conn, store_id, local_today=end.day(end.days), now=now)


def _evidence(ctx: Context, incident: Incident) -> list[Item]:
    items: list[Item] = []
    shown: set[tuple[str, str]] = set()  # two detectors may watch the same metric
    for symptom in incident.symptoms:
        key = (symptom.metric, str(symptom.entity))
        if not symptom.current_fact_ids or key in shown or len(items) == MAX_SYMPTOMS:
            continue
        shown.add(key)
        ids = [symptom.current_fact_ids[0], *symptom.baseline_fact_ids[:1]]
        facts = ctx.cited.load(ids)
        current = facts.get(ids[0])
        if current is None:
            continue
        label = METRICS.get(symptom.metric, symptom.metric.replace("_", " "))
        entity = entity_ref(ctx, str(symptom.entity) if symptom.entity.id else "store")
        line = f"{label.capitalize()} for {entity}: {ctx.cited.ref(current)}"
        before = facts.get(ids[1]) if len(ids) > 1 else None
        if before is not None:
            line += f", against {ctx.cited.ref(before)} before"
        items.append(Item(text=line + "."))
    return items


def _options(ctx: Context, decision: DecisionView) -> list[Item]:
    items = []
    for option in sorted(decision.options, key=lambda o: o.rank):
        line = wording.option(option.kind).capitalize()
        if option.impact_fact_id is not None:
            impact = ctx.cited.load([option.impact_fact_id]).get(option.impact_fact_id)
            if impact is not None:
                line += f": expected net-profit change {ctx.cited.ref(impact)}"
        if option.option_id == decision.recommended_option_id:
            line += " (recommended)"
        items.append(
            Item(
                text=line + ".",
                decision_id=str(decision.decision_id),
                buttons=(
                    Button(
                        kind=ButtonKind.APPROVE,
                        label="Approve",
                        decision_id=str(decision.decision_id),
                        option_id=option.option_id,
                    ),
                ),
            )
        )
    return items


def _finish(ctx: Context, headline: str, sections: list[Section]) -> Document:
    return Document(
        headline=headline,
        sections=tuple(s for s in sections if s.items or s.empty),
        fact_ids=tuple(sorted(ctx.cited.facts)),
        entities=tuple(sorted(ctx.cited.entities)),
    )


def alert_document(ctx: Context, incident: Incident) -> Document:
    entity = entity_ref(ctx, incident_entity(incident))
    cause = wording.cause(top_family(incident))
    evidence_button = Button(
        kind=ButtonKind.EVIDENCE, label="Evidence", incident_id=incident.incident_id
    )
    detected = Section(
        key="detected",
        title="What was detected",
        items=(Item(text=f"{entity}: {cause}.", level=incident.alert.value),),
    )
    evidence = Section(
        key="evidence",
        title="Evidence",
        items=(
            *_evidence(ctx, incident),
            Item(
                text="Every number links to its formula and source rows.",
                buttons=(evidence_button,),
            ),
        ),
    )
    if incident.alert is AlertLevel.DATA_QUALITY:
        return _finish(
            ctx,
            "Data issue, not a profit issue.",
            [
                detected,
                Section(
                    key="why",
                    title="Why it matters",
                    items=(
                        Item(
                            text=f"Reported figures for {entity} are unreliable until it is "
                            "fixed, so decisions based on them could be wrong."
                        ),
                    ),
                ),
                evidence,
                Section(
                    key="uncertain", title="Still uncertain", items=(Item(text=DATA_UNCERTAIN),)
                ),
                Section(
                    key="next_step",
                    title="Recommended next step",
                    items=(
                        Item(
                            text="Fix the tracking or the data source; no budget action is "
                            "recommended until it is restored.",
                            buttons=(evidence_button,),
                        ),
                    ),
                ),
            ],
        )
    level = wording.LEVELS[incident.alert]
    impact = impact_of(ctx, incident)
    loss = ctx.cited.loss(impact) if impact is not None else None
    why = (
        f"It costs about {ctx.cited.ref(loss)} a month."
        if loss is not None
        else "Its impact on profit could not be estimated yet."
    )
    uncertain = [Item(text=UNCERTAIN)]
    if len(incident.candidates) > 1:
        other = incident.candidates[1]
        other_entity = entity_ref(ctx, "store" if other.entity.id is None else str(other.entity))
        uncertain.append(
            Item(text=f"Another possible cause: {other_entity}: {wording.cause(other.family)}.")
        )
    decision = decision_for(ctx, incident.incident_id)
    if decision is not None:
        recommended = decision.option(decision.recommended_option_id)
        options = Section(key="options", title="Options", items=tuple(_options(ctx, decision)))
        step = Item(
            text=f"Recommended: {wording.option(recommended.kind)}. You approve; it is executed "
            "within the spending caps and can be undone.",
            decision_id=str(decision.decision_id),
            buttons=(
                Button(
                    kind=ButtonKind.APPROVE,
                    label="Approve",
                    decision_id=str(decision.decision_id),
                    option_id=recommended.option_id,
                ),
                Button(
                    kind=ButtonKind.REVIEW,
                    label="Review options",
                    decision_id=str(decision.decision_id),
                ),
            ),
        )
    else:
        options = Section(key="options", title="Options", empty="The options are being prepared.")
        step = Item(text="Review the evidence before acting.", buttons=(evidence_button,))
    return _finish(
        ctx,
        f"{level.capitalize()} alert: {entity}: {cause}.",
        [
            detected,
            Section(key="why", title="Why it matters", items=(Item(text=why),)),
            evidence,
            Section(key="uncertain", title="Still uncertain", items=tuple(uncertain)),
            options,
            Section(key="next_step", title="Recommended next step", items=(step,)),
        ],
    )


def decision_document(ctx: Context, decision: DecisionView) -> Document:
    recommended = decision.option(decision.recommended_option_id)
    entity = entity_ref(ctx, decision.entity)
    proposal = Item(
        text=f"For {entity}: {wording.option(recommended.kind)}. You approve; it is executed "
        "within the spending caps and can be undone.",
        decision_id=str(decision.decision_id),
        buttons=(
            Button(
                kind=ButtonKind.REVIEW,
                label="Review options",
                decision_id=str(decision.decision_id),
            ),
        ),
    )
    return _finish(
        ctx,
        "A decision is waiting for your approval.",
        [
            Section(key="proposal", title="Proposed", items=(proposal,)),
            Section(key="options", title="Options", items=tuple(_options(ctx, decision))),
            Section(
                key="expiry",
                title="Expiry",
                items=(
                    Item(text="If nobody approves it, the decision expires and nothing changes."),
                ),
            ),
        ],
    )
