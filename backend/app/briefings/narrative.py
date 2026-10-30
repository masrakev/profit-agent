"""The briefing's short narrative, written by Spark at low effort from the assembled briefing.

The model sees the briefing's sections and the facts they cite (values included, so it can say
what went up or down) and writes two or three sentences citing those facts. Entities appear only
as references: no merchant-provided text reaches the model. The output is verified like any
answer; if the model is unavailable or the verifier rejects it twice, there is no narrative and
the briefing is sent from facts only. Two rules of the narrative are checked by code:

- a loss is a positive amount with a word that says so ("lost", "down"), never a loss word next
  to a negative fact ("lost -$..."): such an answer is rejected like an invented number;
- at most three sentences: a longer narrative is rewritten once, then cut at a sentence end.
"""

import json
import re
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.agent.guard import GuardedOutcome, OutputViolation, feedback_messages, generate_guarded
from app.agent.llm.models import DataOrigin
from app.agent.llm.provider import LLMProvider
from app.agent.llm.types import LLMRequest, UserMessage
from app.agent.prompts import load_prompt
from app.agent.stages import Routing, Stage, StagesConfig
from app.briefings.models import BriefingContent
from app.briefings.store import Narration
from app.facts.model import Fact
from app.verifier import entity_references, fact_references
from app.verifier.render import REFERENCE

MAX_REGENERATIONS = 1  # two rejections, and the briefing goes out from facts only
TABLES = frozenset({"campaigns", "unit_economics"})  # most of the facts, not narrated
MAX_SENTENCES = 3
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# A loss word just before a reference: the reference must then be a positive amount.
LOSS_BEFORE = re.compile(
    r"(?i)(?:\b(?:lost|loses|losing|loss(?:es)?|down|fell|falls?|dropped|drops?|declined|"
    r"declines?|costs?|costing|shortfall)\b[^{}.!?]{0,24}|-\s*)$"
)
TOO_LONG = OutputViolation("summary", "length", "write at most three sentences")


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


def sentences(text: str) -> list[str]:
    return [x for x in SENTENCE_END.split(text.strip()) if x]


def loss_signs(facts: Mapping[int, Fact]) -> Callable[[Narrative], list[OutputViolation]]:
    """Reject a loss word next to a negative fact: the briefing cites losses as positive."""

    def check(narrative: Narrative) -> list[OutputViolation]:
        found = []
        for match in REFERENCE.finditer(narrative.summary):
            fact = facts.get(int(match.group(1)))
            level = None if fact is None else (fact.p50 if fact.p50 is not None else fact.value)
            if level is None or level >= 0:
                continue
            if LOSS_BEFORE.search(narrative.summary[max(0, match.start() - 40) : match.start()]):
                found.append(
                    OutputViolation(
                        "summary",
                        "contract",
                        f"{match.group(0)} is negative: write the loss as the positive amount "
                        "the briefing cites (lost, down), never a loss word with a negative one",
                    )
                )
        return found

    return check


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
    request = LLMRequest(
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
    )

    def guarded(req: LLMRequest, regenerations: int) -> GuardedOutcome[Narrative]:
        return generate_guarded(
            provider,
            req,
            Narrative,
            known_facts=known_facts,
            known_entities=known_entities,
            fallback=lambda _reason: Narrative(summary="", evidence=[]),
            max_regenerations=regenerations,
            validate=loss_signs(facts),
        )

    outcome = guarded(request, MAX_REGENERATIONS)
    results, attempts = list(outcome.results), outcome.attempts
    summary = outcome.output.summary.strip() if outcome.source == "model" else ""
    if len(sentences(summary)) > MAX_SENTENCES:
        rewrite = guarded(
            request.model_copy(
                update={
                    "input": (
                        *request.input,
                        *feedback_messages([TOO_LONG], outcome.output.model_dump_json()),
                    )
                }
            ),
            0,
        )
        results += rewrite.results
        attempts += rewrite.attempts
        shorter = rewrite.output.summary.strip() if rewrite.source == "model" else ""
        if shorter and len(sentences(shorter)) <= MAX_SENTENCES:
            summary = shorter
        else:  # cut at a sentence end: every sentence kept was verified
            summary = " ".join(sentences(shorter or summary)[:MAX_SENTENCES])
    usage = [r.usage for r in results]
    narration = Narration(
        narrative=summary or None,
        prompt_version=prompt.version,
        model=route.model.value,
        attempts=attempts,
        fallback_reason=outcome.fallback_reason
        or (None if summary else "the model wrote no narrative"),
        input_tokens=sum(u.input_tokens for u in usage),
        output_tokens=sum(u.output_tokens for u in usage),
        cost_usd=sum((r.cost_usd for r in results), Decimal(0)),
    )
    return narration, outcome
