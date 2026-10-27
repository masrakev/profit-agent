"""Run a benchmark suite end to end and write reports.

    uv run python -m bench.runner                  # test_v2 suite (what `make eval` runs)
    uv run python -m bench.runner --suite dev      # tuning suite

Uses a dedicated database (`profit_bench`), recreated and migrated on every run, and runs
scenarios in parallel worker processes. Results do not depend on the number of workers.
"""

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text

from app.config import get_settings
from app.detection.config import default_config
from app.observability import configure_logging
from bench.runner.report import REPORT_DIR, write_reports
from bench.runner.run import run_job, worker_init
from bench.runner.score import judge, summarize
from bench.scenarios.manifest import load_suite

ROOT = Path(__file__).resolve().parents[2]
BENCH_DB = "profit_bench"


def _with_db(url: str, database: str) -> str:
    return make_url(url).set(database=database).render_as_string(hide_password=False)


def prepare_database() -> str:
    """Recreate and migrate the bench database; return the app-role URL for it."""
    settings = get_settings()
    maintenance = create_engine(
        _with_db(settings.database_url, "postgres"), isolation_level="AUTOCOMMIT"
    )
    with maintenance.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{BENCH_DB}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{BENCH_DB}"'))
    maintenance.dispose()
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    config.attributes["url"] = _with_db(settings.database_url, BENCH_DB)
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
    return _with_db(settings.app_database_url, BENCH_DB)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the detection benchmark")
    parser.add_argument("--suite", choices=["dev", "test_v2", "golden"], default="test_v2")
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("--only", nargs="*", help="scenario ids to run")
    parser.add_argument("--out", type=Path, default=REPORT_DIR)
    args = parser.parse_args(argv)
    configure_logging("WARNING")

    manifests = load_suite(args.suite)
    if args.only:
        manifests = [m for m in manifests if m.scenario_id in set(args.only)]
    if not manifests:
        parser.error("no scenarios to run")
    started = datetime.now(UTC).replace(microsecond=0)
    began = time.perf_counter()
    app_url = prepare_database()
    jobs = [(m, app_url) for m in manifests]
    if args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers, initializer=worker_init) as pool:
            outcomes = list(pool.map(run_job, jobs))
    else:
        outcomes = [run_job(job) for job in jobs]
    total = time.perf_counter() - began
    judgements = [judge(o) for o in outcomes]
    summary = summarize(judgements, outcomes)
    json_path, md_path = write_reports(
        args.suite,
        started,
        summary,
        judgements,
        outcomes,
        total,
        default_config().version,
        args.out,
    )
    sys.stdout.write(md_path.read_text(encoding="utf-8"))
    sys.stdout.write(f"\nReports: {json_path}, {md_path}\n")
    return 1 if any(j.error for j in judgements) else 0


if __name__ == "__main__":
    raise SystemExit(main())
