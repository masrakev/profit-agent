"""A briefing's narrative: written by the model from facts, or none (facts only) when the model
is unavailable or rejected twice; one briefing per store, kind and local day."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine

from app.agent.llm import fake as f
from app.briefings.models import BriefingKind
from app.briefings.service import generate
from app.detection import pipeline
from bench.generator.load import load
from bench.scenarios.manifest import load_suite
from tests.llm_helpers import Harness

pytestmark = pytest.mark.db
DATA_END = date(2026, 9, 29)
NOW = datetime(2026, 10, 30, 6, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def store(app_engine: Engine) -> Any:
    manifest = next(m for m in load_suite("golden") if m.scenario_id == "healthy-b")
    data = manifest.generate()
    load(app_engine, data, manifest.config)
    pipeline.run_pipeline(app_engine, data.store.store_id)
    return data.store.store_id


def briefing_facts(body: dict[str, Any]) -> list[dict[str, Any]]:
    text = next(
        i["content"][0]["text"]
        for i in body["input"]
        if i["content"][0]["text"].startswith("Briefing assembled by code")
    )
    facts: list[dict[str, Any]] = json.loads(text.split("\n", 1)[1])["facts"]
    return facts


def test_the_model_writes_the_narrative(app_engine: Engine, store: Any) -> None:
    seen: list[dict[str, Any]] = []

    def narrative(body: dict[str, Any]) -> f.Reply:
        facts = briefing_facts(body)
        seen.extend(facts)
        first = facts[0]["fact_id"]
        return f.structured(
            {"summary": f"Net profit was {{{{F{first}}}}} yesterday.", "evidence": [first]},
            model="muse-spark-1.3",
        )

    h = Harness([narrative])
    record = generate(
        app_engine, store, BriefingKind.DAILY, h.provider, local_today=DATA_END, now=NOW
    )
    assert record.status == "narrated"
    assert record.narration.narrative == f"Net profit was {{{{F{seen[0]['fact_id']}}}}} yesterday."
    assert (record.narration.model, record.narration.attempts) == ("muse-spark-1.3", 1)
    assert record.narration.prompt_version
    assert record.narration.input_tokens > 0
    assert record.narration.cost_usd > Decimal(0)
    assert {x["fact_id"] for x in seen} == set(record.content.fact_ids)
    assert all("name" not in json.dumps(x) for x in seen)  # facts only, never merchant text
    body = h.transport.requests[0]
    assert body["model"] == "muse-spark-1.3"
    assert body["reasoning"]["effort"] == "low"
    # The same day again: the stored briefing, no model call.
    again = generate(
        app_engine, store, BriefingKind.DAILY, h.provider, local_today=DATA_END, now=NOW
    )
    assert again.briefing_id == record.briefing_id
    assert len(h.transport.requests) == 1


def test_two_rejections_send_the_briefing_from_facts_only(app_engine: Engine, store: Any) -> None:
    invented = f.structured(
        {"summary": "Net profit was 1,234 dollars.", "evidence": []}, model="muse-spark-1.3"
    )
    h = Harness([invented, invented])
    record = generate(
        app_engine,
        store,
        BriefingKind.WEEKLY,
        h.provider,
        local_today=DATA_END,
        now=NOW,
    )
    assert record.status == "facts_only"
    assert record.narration.narrative is None
    assert record.narration.attempts == 2
    assert record.narration.fallback_reason == (
        "its output failed verification after every regeneration"
    )
    assert record.content.sections  # complete without the model
    assert len(h.transport.requests) == 2


def test_an_unavailable_model_sends_it_from_facts_only(app_engine: Engine, store: Any) -> None:
    h = Harness([f.overloaded()], max_attempts=1)
    record = generate(
        app_engine, store, BriefingKind.DAILY, h.provider, local_today=date(2026, 10, 1), now=NOW
    )
    assert record.status == "facts_only"
    assert record.narration.fallback_reason is not None
    assert "unavailable" in record.narration.fallback_reason
