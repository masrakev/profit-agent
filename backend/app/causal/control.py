"""Synthetic control (Task 4 B4, ADR 0018).

The treated series is reproduced, over the pre-period, as an intercept plus a convex
combination of donor series (weights >= 0 summing to 1; fitted on demeaned series by projected
gradient descent). After the action, the same combination is the counterfactual; the effect is
the sum of actual minus counterfactual over the window. Its interval comes from the pre-period
residuals: circular blocks of the window's length, bootstrapped (seeded). The method abstains
when the window is not fully observed yet, when there is no donor, or when the pre-period fit
is weak (R-squared below `MIN_R2`): never a raw before/after.
"""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
MIN_R2 = 0.3
BOOTSTRAP = 2000
ITERATIONS = 3000


def project_simplex(v: FloatArray) -> FloatArray:
    """Euclidean projection on {w >= 0, sum w = 1} (Duchi et al., 2008)."""
    u = np.sort(v)[::-1]
    cumulative = np.cumsum(u) - 1.0
    k = np.arange(1, len(v) + 1)
    rho = int(np.nonzero(u - cumulative / k > 0)[0][-1])
    theta = cumulative[rho] / (rho + 1)
    out: FloatArray = np.maximum(v - theta, 0.0)
    return out


def simplex_weights(donors: FloatArray, target: FloatArray) -> tuple[FloatArray, float]:
    """Weights and intercept minimising the squared pre-period error."""
    x = donors - donors.mean(axis=0)
    y = target - target.mean()
    k = donors.shape[1]
    w = np.full(k, 1.0 / k)
    gram = x.T @ x
    lipschitz = float(np.linalg.eigvalsh(gram).max()) if k else 0.0
    step = 1.0 / lipschitz if lipschitz > 0 else 1.0
    xty = x.T @ y
    for _ in range(ITERATIONS):
        w = project_simplex(w - step * (gram @ w - xty))
    intercept = float(target.mean() - donors.mean(axis=0) @ w)
    return w, intercept


@dataclass(frozen=True)
class ControlResult:
    measured: bool
    reason: str
    effect: tuple[float, float, float] | None = None  # P10, P50, P90 of the summed effect
    pre_r2: float | None = None
    weights: tuple[float, ...] = ()
    actual: float | None = None
    counterfactual: float | None = None


def synthetic_control(
    target: FloatArray,
    donors: FloatArray,
    split: int,
    window: int,
    rng: np.random.Generator,
) -> ControlResult:
    """`target` (T,), `donors` (T, k); the action takes effect at index `split`."""
    if len(target) < split + window:
        return ControlResult(False, "too little post-decision history to measure the window")
    if donors.shape[1] == 0:
        return ControlResult(False, "no untouched campaign or product to compare with")
    if split < 2 * window:
        return ControlResult(False, "too little history before the action")
    w, b = simplex_weights(donors[:split], target[:split])
    fitted = donors[:split] @ w + b
    residuals = target[:split] - fitted
    total = float(((target[:split] - target[:split].mean()) ** 2).sum())
    r2 = 1.0 - float((residuals**2).sum()) / total if total > 0 else 0.0
    if r2 < MIN_R2:
        return ControlResult(False, "the pre-period fit is too weak", pre_r2=r2)
    post = slice(split, split + window)
    counterfactual = donors[post] @ w + b
    actual = float(target[post].sum())
    cf = float(counterfactual.sum())
    effect = actual - cf
    starts = rng.integers(0, split, size=BOOTSTRAP)
    blocks = (starts[:, None] + np.arange(window)[None, :]) % split
    noise = residuals[blocks].sum(axis=1)
    q10, q50, q90 = np.percentile(noise, [10, 50, 90])
    return ControlResult(
        True,
        "measured",
        effect=(effect - float(q90), effect - float(q50), effect - float(q10)),
        pre_r2=r2,
        weights=tuple(float(x) for x in w),
        actual=actual,
        counterfactual=cf,
    )
