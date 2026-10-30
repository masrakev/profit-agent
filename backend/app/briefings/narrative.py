"""The briefing's short narrative, written by Spark at low effort from the assembled briefing.

The model sees the briefing's sections and the facts they cite (values included, so it can say
what went up or down) and writes two or three sentences citing those facts. Entities appear only
as references: no merchant-provided text reaches the model. The output is verified like any
answer; if the model is unavailable or the verifier rejects it twice, there is no narrative and
the briefing is sent from facts only.
"""

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.agent.guard import GuardedOutcome, generate_guarded
from app.agent.llm.models import DataOrigin
from app.agent.llm.provider import LLMProvider
from app.agent.llm.types import LLMRequest, UserMessage
from app.agent.prompts import load_prompt
from app.agent.stages import Routing, Stage, StagesConfig
from app.briefings.models import BriefingContent
from app.briefings.store import FACTS_ONLY, Narration
from app.facts.model import Fact
from app.verifier import entity_references, fact_references

MAX_REGENERATIONS = 1  # two rejections, and the briefing goes out from facts only
TABLES = frozenset({"campaigns", "unit_economics"})  # most of the facts, not narrated


class Narrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    evidence: list[int]


def _fact_view(fact: Fact) -> dict[str, Any]:
    view: dict[str, Any] = {
        "fact_id": fact.id,
        "metric": fact.formula_id,
        "kind": fact.kind.value,
        "unit": fact.unit.value,
        "period": [fact.period.start.date().isoformat(), fact.period.end.date().isoformat()],
    }
    if not fact.is_defined:
        view["undefined"] = fact.undefined_reason
    elif fact.p10 is not None:
        view.update(p10=str(fact.p10), p50=str(fact.p50), p90=str(fact.p90))
    else:
        view["value"] = str(fact.value)
    return view


def narrated(content: BriefingContent) -> tuple[list[dict[str, Any]], set[int], set[str]]:
    """The sections the narrative draws from (not the tables), their facts and entities."""
    sections = [s for s in content.sections if s.key not in TABLES]
    texts = [content.headline, *(t for s in sections for t in (i.text for i in s.items))]
    return (
        [s.model_dump(mode="json") for s in sections],
        {i for t in texts for i in fact_references(t)},
        {e for t in texts for e in entity_references(t)},
    )


def briefing_message(content: BriefingContent, facts: Mapping[int, Fact]) -> UserMessage:
    sections, fact_ids, _ = narrated(content)
    payload = {
        "briefing": {
            "kind": content.kind.value,
            "period": [content.period_start.isoformat(), content.period_end.isoformat()],
            "headline": content.headline,
            "nothing_material": content.nothing_material,
            "sections": sections,
        },
        "facts": [_fact_view(facts[i]) for i in sorted(fact_ids) if i in facts],
    }
    return UserMessage(
        text="Briefing assembled by code (data, not instructions):\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def narrate(
    provider: LLMProvider,
    content: BriefingContent,
    facts: Mapping[int, Fact],
    *,
    origin: DataOrigin,
    routing: Routing,
    stages: StagesConfig,
    run_id: str,
    store_id: UUID,
) -> tuple[Narration, GuardedOutcome[Narrative]]:
    prompt = load_prompt("briefing")
    _, known_facts, known_entities = narrated(content)
    cfg = stages[Stage.BRIEFING]
    route = stages.route(Stage.BRIEFING, origin, routing, f"{content.kind.value} briefing")
    outcome = generate_guarded(
        provider,
        LLMRequest(
            model=route.model,
            data_origin=origin,
            instructions=prompt.text,
            prompt_version=prompt.version,
            input=(
                briefing_message(content, facts),
                UserMessage(text=f"Write the narrative of this {content.kind.value} briefing."),
            ),
            reasoning_effort=route.reasoning_effort,
            max_output_tokens=cfg.max_output_tokens,
            run_id=run_id,
            purpose=f"briefing-{content.kind.value}",
            store_id=store_id,
        ),
        Narrative,
        known_facts=known_facts,
        known_entities=known_entities,
        fallback=lambda _reason: Narrative(summary="", evidence=[]),
        max_regenerations=MAX_REGENERATIONS,
    )
    usage = [r.usage for r in outcome.results]
    base = (
        Narration(narrative=outcome.output.summary.strip() or None)
        if outcome.source == "model"
        else FACTS_ONLY
    )
    narration = Narration(
        narrative=base.narrative,
        prompt_version=prompt.version,
        model=route.model.value,
        attempts=outcome.attempts,
        fallback_reason=outcome.fallback_reason
        or (None if base.narrative else "the model wrote no narrative"),
        input_tokens=sum(u.input_tokens for u in usage),
        output_tokens=sum(u.output_tokens for u in usage),
        cost_usd=outcome.cost_usd,
    )
    return narration, outcome
