"""Generate a synthetic store and load it into PostgreSQL.

    uv run python -m bench.generator --seed 42

The store id is derived from the seed and config, so running twice reports the existing store.
"""

import argparse
import json
import sys
from datetime import date

from app.config import get_settings
from app.db import app_engine
from app.observability import configure_logging, get_logger
from bench.generator.config import GeneratorConfig
from bench.generator.load import StoreExistsError, load
from bench.generator.simulate import generate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a synthetic store")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2026, 6, 1))
    parser.add_argument("--name")
    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)
    log = get_logger("bench.generator")

    config = GeneratorConfig(
        seed=args.seed, days=args.days, start_date=args.start_date, store_name=args.name
    )
    data = generate(config)
    store_id = str(data.store.store_id)
    engine = app_engine()
    try:
        load(engine, data, config)
        status = "created"
    except StoreExistsError:
        status = "exists"
    finally:
        engine.dispose()
    result = {"store_id": store_id, "status": status, "counts": data.counts()}
    log.info("store.generated", **result)
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
