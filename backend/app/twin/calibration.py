"""Split-conformal widening of the twin's P10-P90 intervals (ADR 0014).

`calibration.toml` holds one factor per metric and per scenario kind ("do nothing", or an
action), computed on `dev` scenarios by `python -m bench.twin.calibrate` and then frozen. An
interval `[P10, P90]` of half-width `w` becomes `[P10 - q*w, P90 + q*w]`; P50 is unchanged.
`q > 0` widens, `q < 0` narrows (raw intervals that were too wide).
"""

import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from app.twin.model import METRICS, Range

CALIBRATION_FILE = Path(__file__).with_name("calibration.toml")
MIN_FACTOR = -0.9  # never invert or collapse an interval


@dataclass(frozen=True)
class Calibration:
    version: int
    method: str
    do_nothing: dict[str, float]
    action: dict[str, float]

    @classmethod
    def identity(cls) -> "Calibration":
        zeros = dict.fromkeys(METRICS, 0.0)
        return cls(version=0, method="uncalibrated", do_nothing=zeros, action=dict(zeros))

    def factor(self, metric: str, *, action: bool) -> float:
        return max((self.action if action else self.do_nothing).get(metric, 0.0), MIN_FACTOR)

    def change_factor(self, metric: str) -> float:
        """A difference of two simulated totals: the larger factor, never narrowed."""
        return max(self.factor(metric, action=True), self.factor(metric, action=False), 0.0)


def widen(r: Range, q: float) -> Range:
    w = (r.p90 - r.p10) / 2
    return Range(r.p10 - q * w, r.p50, r.p90 + q * w)


@cache
def load_calibration(path: Path = CALIBRATION_FILE) -> Calibration:
    if not path.exists():
        return Calibration.identity()
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return Calibration(
        version=int(raw["version"]),
        method=str(raw["method"]),
        do_nothing={m: float(raw["do_nothing"][m]) for m in METRICS},
        action={m: float(raw["action"][m]) for m in METRICS},
    )
