"""Golden question q38's store: the demo store (bench/demo_seed.py) as it is when its owner sets
the 90-day goal. The golden stockout store enters the simulator 28 days before its data end; the
goal asked aloud is the demo's own (net profit over the next 90 days, at the forecast's median).
"""

from uuid import UUID

from sqlalchemy import Engine

from bench.demo_seed import DAYS_BEFORE_END
from bench.scenarios.manifest import ScenarioManifest
from bench.simulator import register

SCENARIO = "golden-demo-goal"


def set_up(engine: Engine, manifest: ScenarioManifest) -> UUID:
    return register(engine, manifest, manifest.config.days - DAYS_BEFORE_END)
