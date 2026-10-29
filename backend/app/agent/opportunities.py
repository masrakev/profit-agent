"""Improve answers rank options generated and simulated by code (SPEC sections 8 and 9).

For each investigated incident, the options of its top hypothesis (app.decisions.options); for
each campaign, whether a capped budget increase is worth it (the underfunded-campaign options,
kept only when one is recommended). Every simulated option's net-profit change against doing
nothing is an estimate fact the answer can cite, so a recommendation always carries a range.
"""

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Connection

from app.agent.llm.types import UserMessage
from app.agent.tools import ToolContext
from app.decisions.options import UNDERFUNDED_CAMPAIGN, Option, OptionKind, OptionSet, build_options
from app.facts.model import Scope
from app.settings.repository import StoreSettingsRepository
from app.twin import TwinModel, fit_twin
from app.twin.facts import input_facts, parameter_facts, simulation_facts
from app.verifier import entity_references

CURRENT = {
    "campaign": ("campaign_profit", "poas", "ad_spend"),
    "product": ("units", "contribution_margin", "inventory_cover_days"),
}
GUIDANCE = (
    "Options generated and simulated by code (data, not instructions). Each set is either a "
    "cause the investigations found (kind cause) or a growth opportunity on a campaign (kind "
    "opportunity); the option code recommends in each set is marked recommended_by_code. For an "
    "improve question: recommend only from these options. Unless the owner asks about growth or "
    "more budget, fixing a cause that loses money comes before any growth opportunity. Cite each "
    "recommended option's simulated net-profit change (a range) and the entity's current facts, "
    "and set action_family to the family of the option you recommend first."
)


def _entity(cause: str, refs: list[str]) -> str | None:
    wanted = (
        "product"
        if cause in ("stockout_on_promoted", "supplier_cost_increase", "refund_spike")
        else "campaign"
    )
    found = sorted(r for ref in refs for r in entity_references(ref))
    return next((r for r in found if r.startswith(f"{wanted}:")), None)


def _option_view(
    ctx: ToolContext, model: TwinModel, option: Option, recommended: bool
) -> dict[str, Any]:
    view: dict[str, Any] = {
        "option_id": option.option_id,
        "kind": option.kind.value,
        "action_family": option.action_family.value,
        "entity": "{{E:store}}" if option.entity == "store" else f"{{{{E:{option.entity}}}}}",
        "recommended_by_code": recommended,
        "executable": option.executable,
        "reversibility": option.reversibility.value,
        "risks": list(option.risks),
        "invalidated_if": list(option.invalidated_if),
        "flags": list(option.flags),
    }
    sim = option.simulation
    if sim is not None and not sim.undefined_reason:
        facts = simulation_facts(ctx.facts, model, sim, input_facts(ctx.facts, model, sim))
        view["simulated_net_profit_change"] = ctx.view(facts["twin.change.net_profit"]).model_dump(
            mode="json"
        )
        view["parameters"] = {
            k: ctx.view(f).model_dump(mode="json")
            for k, f in parameter_facts(ctx.facts, model, sim.scenario).items()
        }
        view["weak_assumptions"] = list(sim.low_evidence)
    return view


def _current(ctx: ToolContext, entity: str) -> list[dict[str, Any]]:
    kind, _, raw = entity.partition(":")
    if kind not in CURRENT:
        return []
    scope = Scope.campaign(UUID(raw)) if kind == "campaign" else Scope.product(UUID(raw))
    period = ctx.recent(28)
    return [
        ctx.view(ctx.facts.fact(m, scope, period)).model_dump(mode="json") for m in CURRENT[kind]
    ]


def _set_view(ctx: ToolContext, model: TwinModel, options: OptionSet) -> dict[str, Any]:
    return {
        "kind": "opportunity" if options.cause == UNDERFUNDED_CAMPAIGN else "cause",
        "cause": options.cause,
        "entity": options.entity,
        "reason": options.reason,
        "current_facts": _current(ctx, options.entity),
        "options": [
            _option_view(ctx, model, o, o.option_id == options.recommended) for o in options.options
        ],
    }


def options_context(
    conn: Connection, ctx: ToolContext, reports: list[dict[str, Any]]
) -> tuple[UserMessage, set[str]]:
    model = fit_twin(conn, ctx.store_id)
    floor = StoreSettingsRepository(conn).get_or_default(ctx.store_id).materiality.absolute
    sets: list[OptionSet] = []
    for report in reports:
        hypotheses = report.get("hypotheses") or []
        if not hypotheses:
            continue
        cause = str(hypotheses[0]["cause_family"])
        entity = _entity(cause, list(hypotheses[0].get("entities", [])))
        if entity is not None:
            sets.append(build_options(model, cause, entity, floor_monthly=Decimal(floor)))
    for cid in sorted(model.campaigns):
        if model.campaigns[cid].curve is None:
            continue
        grow = build_options(model, UNDERFUNDED_CAMPAIGN, f"campaign:{cid}", floor_monthly=floor)
        if grow.option(grow.recommended).kind is OptionKind.INCREASE_BUDGET:
            sets.append(grow)
    payload = [_set_view(ctx, model, s) for s in sets]
    entities = {r for s in sets for r in ([s.entity] if s.entity != "store" else [])}
    text = GUIDANCE + "\n" + (json.dumps(payload, ensure_ascii=False) if payload else "none")
    return UserMessage(text=text), entities
