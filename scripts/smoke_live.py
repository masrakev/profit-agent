"""Smoke test of the Meta Model API: one tool call and one structured output per model.

    uv run python scripts/smoke_live.py                 # live, every model
    uv run python scripts/smoke_live.py --mode record   # live, and write cassettes (recorded/)
    uv run python scripts/smoke_live.py --mode replay   # from committed cassettes, no key

Needs MODEL_API_KEY (in `.env`) for live and record. Prints tokens and cost per model and exits
with status 1, saying what differed, if any response is not what the provider expects.
"""

import argparse
import sys
from decimal import Decimal

from app.agent.llm.cassette import LLMMode
from app.agent.llm.factory import build_provider
from app.agent.llm.models import ModelId
from app.agent.llm.smoke import run
from app.config import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=[m.value for m in LLMMode], default="live")
    parser.add_argument(
        "--model", action="append", choices=[m.value for m in ModelId], dest="models"
    )
    args = parser.parse_args(argv)
    models = [ModelId(m) for m in args.models] if args.models else list(ModelId)
    provider = build_provider(get_settings(), mode=LLMMode(args.mode))
    outcomes = run(provider, models)
    out = sys.stdout
    out.write(
        f"{'model':<28} {'ok':<4} {'input':>7} {'cached':>7} {'output':>7} "
        f"{'reason.':>7} {'cost USD':>12}  detail\n"
    )
    total = Decimal(0)
    for o in outcomes:
        u = o.usage
        total += o.cost_usd
        out.write(
            f"{o.model.value:<28} {'yes' if o.ok else 'NO':<4} {u.input_tokens:>7} "
            f"{u.cached_tokens:>7} {u.output_tokens:>7} {u.reasoning_tokens:>7} "
            f"{o.cost_usd:>12.6f}  {o.detail}\n"
        )
    note = " (replayed: no money spent)" if args.mode == "replay" else ""
    out.write(f"total cost USD {total:.6f}{note}\n")
    failed = [o.model.value for o in outcomes if not o.ok]
    if failed:
        sys.stderr.write(f"SMOKE FAILED for {', '.join(failed)}: see the detail column\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
