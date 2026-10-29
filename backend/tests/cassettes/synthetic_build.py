"""Hand-written cassettes for the smoke conversation, until real ones are recorded.

The request side is produced by the provider itself (so the cassette keys match what it sends);
the response side is written by hand in the documented Responses API format. Every cassette is
marked `"synthetic": true`. Rebuild after a change to the smoke prompt or request encoding:

    uv run python backend/tests/cassettes/synthetic_build.py
"""

import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.agent.llm import BudgetCaps, BudgetGuard, InMemorySpendLedger, ModelId
from app.agent.llm import fake as f
from app.agent.llm.cassette import CassetteStore, RecordTransport
from app.agent.llm.provider import MetaResponsesProvider
from app.agent.llm.smoke import REFERENCE, run

NOTE = (
    "SYNTHETIC: hand-written response in the documented format, not a real model output; "
    "pending live verification (record with scripts/smoke_live.py --mode record)"
)
ROOT = Path(__file__).resolve().parent


def _ids(body: dict[str, Any], prefix: str) -> dict[str, Any]:
    body["id"] = f"resp_{prefix}"
    for i, item in enumerate(body["output"]):
        if item["type"] == "reasoning":
            item["id"] = f"rs_{prefix}_{i}:rs_{prefix}_{i}"
        elif "id" in item:
            item["id"] = f"{item['type'][:3]}_{prefix}_{i}"
    return body


def _steps(model: ModelId) -> list[f.Step]:
    tag = model.value.replace(".", "_")
    call = f.function_call("get_fact", {"fact_id": 1}, call_id=f"call_{tag}")
    first = f.response(
        [f.reasoning(f"enc-{tag}-1"), call],
        model=model.value,
        use=f.usage(212, 46, reasoning=28),
    )
    answer = json.dumps({"fact_reference": REFERENCE, "used_tool": True})
    second = f.response(
        [f.reasoning(f"enc-{tag}-2"), f.message(answer)],
        model=model.value,
        use=f.usage(318, 37, cached=192, reasoning=15),
    )
    return [f.Reply(200, _ids(first, f"{tag}_1")), f.Reply(200, _ids(second, f"{tag}_2"))]


def build(root: Path = ROOT) -> list[Path]:
    store = CassetteStore(root)
    written: list[Path] = []
    for model in ModelId:
        transport = RecordTransport(
            f.FakeTransport(_steps(model)), store, synthetic=True, note=NOTE
        )
        provider = MetaResponsesProvider(
            api_key="synthetic",
            transport=transport,
            budget=BudgetGuard(BudgetCaps(Decimal(1), Decimal(1)), InMemorySpendLedger()),
            transport_mode="synthetic-build",
        )
        (outcome,) = run(provider, [model])
        if not outcome.ok:
            raise RuntimeError(f"synthetic smoke for {model} does not pass: {outcome.detail}")
        written.extend(transport.written)
    return written


if __name__ == "__main__":
    for path in build():
        sys.stdout.write(f"{path}\n")
