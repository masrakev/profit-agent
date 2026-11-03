"""Serve the demo store (`make demo-seed`) for a demo or its end-to-end test.

    uv run python -m bench.demo_serve api      # make demo-api: the API on 127.0.0.1:8000
    uv run python -m bench.demo_serve worker   # the executor, which carries out approvals

Both use the `profit_demo` database. The API replays the demo's recorded model exchanges
(`backend/tests/cassettes/demo/`) at their recorded pace, so the agent's work streams on screen
as it did when recorded; `LLM_MODE=record` in the environment records new exchanges there
instead (a question not recorded yet, with a model key). Never for real stores.
"""

import argparse
import os
import sys

from app.config import get_settings
from bench.demo_seed import DEMO_DB
from bench.runner.__main__ import _with_db


def demo_environment() -> None:
    """Point the app at the demo database and its cassettes, replayed at their pace."""
    settings = get_settings()
    os.environ["APP_DATABASE_URL"] = _with_db(settings.app_database_url, DEMO_DB)
    os.environ["DATABASE_URL"] = _with_db(settings.database_url, DEMO_DB)
    os.environ.setdefault("LLM_MODE", "replay")
    os.environ.setdefault("LLM_REPLAY_PACE", "true")
    os.environ.setdefault("LLM_CASSETTE_DIR", "backend/tests/cassettes/demo")
    get_settings.cache_clear()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the demo store")
    parser.add_argument("what", choices=["api", "worker"])
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    demo_environment()
    if args.what == "api":
        import uvicorn

        uvicorn.run("app.api.main:app", host="127.0.0.1", port=args.port)
        return 0
    from app.executor.__main__ import main as executor

    return executor(["--loop", "2"])


if __name__ == "__main__":
    sys.exit(main())
