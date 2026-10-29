"""Facts derived on demand by tools, with lineage to the facts they come from.

- `compute`: safe arithmetic over existing facts. The expression may contain only fact
  references (`F12`), `+ - * /`, unary minus and parentheses: no literal numbers, so a model
  cannot slip a number of its own into a "derived" fact. Exact decimal arithmetic; units and
  currencies are checked; division by zero gives an `undefined` fact.
- series helpers: difference, mean and OLS slope of daily facts.
"""

import ast
import math
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

import numpy as np

from app.domain.hashing import canonical_json, sha256_hex
from app.facts.arith import RATIO_CONTEXT, UndefinedValue, exact_sub, exact_sum, ratio
from app.facts.model import (
    Fact,
    FactKind,
    FactStatus,
    Lineage,
    ParentRef,
    Period,
    Scope,
    Unit,
)

COMPUTE_FORMULA = ("derived.compute", 1)
DIFFERENCE_FORMULA = ("derived.difference", 1)
MEAN_FORMULA = ("derived.mean", 1)
SLOPE_FORMULA = ("derived.daily_slope", 1)
SLOPE_METHOD = "ols_daily_normal_v1"
Z_80 = 1.2815515655446004  # P10 / P90 of a standard normal
MAX_OPERANDS = 12


class ComputeError(ValueError):
    pass


def _fact(
    *,
    template: Fact,
    formula: tuple[str, int],
    kind: FactKind,
    unit: Unit,
    currency: str | None,
    scope: Scope,
    period: Period,
    baseline: Period | None,
    parents: Sequence[tuple[str, Fact]],
    params: object,
    value: Decimal | None,
    undefined_reason: str | None = None,
    quantiles: tuple[Decimal, Decimal, Decimal] | None = None,
    method: str | None = None,
) -> Fact:
    inputs_hash = sha256_hex(
        canonical_json(
            {"formula": formula, "params": params, "parents": [p.fact_hash for _, p in parents]}
        )
    )
    defined = undefined_reason is None
    return Fact(
        store_id=template.store_id,
        formula_id=formula[0],
        formula_version=formula[1],
        kind=kind,
        scope=scope,
        period=period,
        baseline=baseline,
        status=FactStatus.DEFINED if defined else FactStatus.UNDEFINED,
        value=value if defined else None,
        unit=unit,
        currency=currency,
        undefined_reason=undefined_reason,
        p10=quantiles[0] if quantiles and defined else None,
        p50=quantiles[1] if quantiles and defined else None,
        p90=quantiles[2] if quantiles and defined else None,
        method=method if defined else None,
        inputs_hash=inputs_hash,
        lineage=Lineage(
            parents=tuple(ParentRef(role=r, fact_hash=p.fact_hash) for r, p in parents)
        ),
    )


# --- compute -------------------------------------------------------------------------------


Value = tuple[Decimal, Unit, str | None]  # value, unit, currency


def _combine(op: ast.operator, a: Value, b: Value) -> Value:
    (x, ux, cx), (y, uy, cy) = a, b
    if isinstance(op, ast.Add | ast.Sub):
        if ux is not uy or cx != cy:
            raise ComputeError(
                f"cannot add or subtract {ux.value} {cx or ''} and {uy.value} {cy or ''}"
            )
        return (exact_sum(x, y) if isinstance(op, ast.Add) else exact_sub(x, y)), ux, cx
    if isinstance(op, ast.Mult):
        if ux is Unit.RATIO:
            return RATIO_CONTEXT.multiply(x, y), uy, cy
        if uy is Unit.RATIO:
            return RATIO_CONTEXT.multiply(x, y), ux, cx
        raise ComputeError(f"cannot multiply {ux.value} by {uy.value}: one factor must be a ratio")
    if isinstance(op, ast.Div):
        if (ux, cx) == (uy, cy):
            return ratio(x, y, denominator_name="the divisor"), Unit.RATIO, None
        if uy is Unit.RATIO:
            return ratio(x, y, denominator_name="the divisor"), ux, cx
        if ux is Unit.MONEY and uy in (Unit.COUNT, Unit.DAYS):
            return ratio(x, y, denominator_name="the divisor"), Unit.MONEY, cx
        raise ComputeError(f"cannot divide {ux.value} by {uy.value}")
    raise ComputeError("only + - * / are allowed")


def _evaluate(node: ast.AST, operands: dict[int, Fact]) -> Value:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, operands)
    if isinstance(node, ast.Name):
        if not node.id.startswith("F") or not node.id[1:].isdigit():
            raise ComputeError(f"unknown name {node.id!r}: reference facts as F<id>")
        fact = operands.get(int(node.id[1:]))
        if fact is None:
            raise ComputeError(f"{node.id} is not in fact_ids")
        if fact.value is None:
            raise UndefinedValue(f"{node.id} is undefined ({fact.undefined_reason})")
        return fact.value, fact.unit, fact.currency
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        v, u, c = _evaluate(node.operand, operands)
        return -v, u, c
    if isinstance(node, ast.BinOp):
        return _combine(node.op, _evaluate(node.left, operands), _evaluate(node.right, operands))
    if isinstance(node, ast.Constant):
        raise ComputeError("literal numbers are not allowed: every operand must be a fact")
    raise ComputeError(f"unsupported syntax {type(node).__name__}")


def _span(facts: Sequence[Fact]) -> tuple[Period, Period | None]:
    periods = sorted({f.period for f in facts}, key=lambda p: (p.end, p.start))
    if len(periods) == 1:
        return periods[0], None
    first, last = periods[0], periods[-1]
    if len(periods) == 2 and first.end <= last.start:
        return last, first  # a comparison: current vs baseline
    return Period(start=min(p.start for p in periods), end=last.end), None


def compute(expression: str, operands: dict[int, Fact]) -> Fact:
    if not operands:
        raise ComputeError("give at least one fact id")
    if len(operands) > MAX_OPERANDS or len(expression) > 300:
        raise ComputeError("expression too long")
    if any(f.kind is not FactKind.EXACT for f in operands.values()):
        raise ComputeError("compute works on exact facts only; estimates carry an interval")
    try:
        tree = ast.parse(expression.replace("{{", "").replace("}}", ""), mode="eval")
    except SyntaxError as exc:
        raise ComputeError(f"invalid expression: {exc.msg}") from exc
    referenced = {
        int(n.id[1:]) for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id[1:].isdigit()
    }
    facts = [operands[i] for i in sorted(referenced) if i in operands]
    scopes = {f.scope for f in facts} or {Scope.store()}
    scope = scopes.pop() if len(scopes) == 1 else Scope.store()
    period, baseline = _span(facts or list(operands.values()))
    template = next(iter(operands.values()))
    try:
        value, unit, currency = _evaluate(tree, operands)
        reason = None
    except (UndefinedValue, InvalidOperation) as exc:
        value, reason = None, getattr(exc, "reason", "the result is not a finite number")
        unit, currency = template.unit, template.currency
        if unit is Unit.MONEY and currency is None:  # pragma: no cover - guarded by Fact
            currency = template.currency
    return _fact(
        template=template,
        formula=COMPUTE_FORMULA,
        kind=FactKind.EXACT,
        unit=unit,
        currency=currency,
        scope=scope,
        period=period,
        baseline=baseline,
        parents=[(f"operand:F{f.id}", f) for f in facts],
        params={"expression": ast.unparse(tree)},
        value=value,
        undefined_reason=reason,
    )


# --- series --------------------------------------------------------------------------------


def difference(start: Fact, end: Fact, period: Period) -> Fact:
    reason = None
    value = None
    if start.value is None or end.value is None:
        reason = "the first or last day is undefined"
    else:
        value = exact_sub(end.value, start.value)
    return _fact(
        template=end,
        formula=DIFFERENCE_FORMULA,
        kind=FactKind.EXACT,
        unit=end.unit,
        currency=end.currency,
        scope=end.scope,
        period=period,
        baseline=None,
        parents=[("start", start), ("end", end)],
        params="last minus first",
        value=value,
        undefined_reason=reason,
    )


def mean(days: Sequence[Fact], period: Period, template: Fact) -> Fact:
    defined = [d for d in days if d.value is not None]
    if not defined:
        value, reason = None, "no defined day"
    else:
        value = ratio(
            exact_sum(*(d.value for d in defined if d.value is not None)),
            Decimal(len(defined)),
            denominator_name="days",
        )
        reason = None
    return _fact(
        template=template,
        formula=MEAN_FORMULA,
        kind=FactKind.EXACT,
        unit=template.unit,
        currency=template.currency,
        scope=template.scope,
        period=period,
        baseline=None,
        parents=[(f"day:{i}", d) for i, d in enumerate(days)],
        params="mean of defined days",
        value=value,
        undefined_reason=reason,
    )


def _decimal(x: float) -> Decimal:
    return Decimal(repr(round(x, 10)))


def slope(days: Sequence[Fact], period: Period, template: Fact) -> Fact:
    """OLS slope of the daily values per day, with a normal 80% interval (estimate)."""
    points = [(i, float(d.value)) for i, d in enumerate(days) if d.value is not None]
    quantiles = None
    value = None
    reason = None
    if len(points) < 3:
        reason = "fewer than three defined days"
    else:
        x = np.array([p[0] for p in points], dtype=float)
        y = np.array([p[1] for p in points], dtype=float)
        xc = x - x.mean()
        b = float((xc * (y - y.mean())).sum() / (xc**2).sum())
        resid = y - (y.mean() + b * xc)
        se = math.sqrt(float((resid**2).sum()) / (len(points) - 2) / float((xc**2).sum()))
        value = _decimal(b)
        quantiles = (_decimal(b - Z_80 * se), value, _decimal(b + Z_80 * se))
    return _fact(
        template=template,
        formula=SLOPE_FORMULA,
        kind=FactKind.ESTIMATE,
        unit=template.unit,
        currency=template.currency,
        scope=template.scope,
        period=period,
        baseline=None,
        parents=[(f"day:{i}", d) for i, d in enumerate(days)],
        params="per day",
        value=value,
        undefined_reason=reason,
        quantiles=quantiles,
        method=SLOPE_METHOD,
    )


def change_point(days: Sequence[Fact], *, min_side: int = 5, min_t: float = 3.0) -> int | None:
    """Index of the first day after the largest mean shift (Welch t >= `min_t`), or None."""
    values = [float(d.value) if d.value is not None else math.nan for d in days]
    best, best_t = None, min_t
    for k in range(min_side, len(values) - min_side + 1):
        a = np.array([v for v in values[:k] if not math.isnan(v)])
        b = np.array([v for v in values[k:] if not math.isnan(v)])
        if len(a) < min_side or len(b) < min_side:
            continue
        var = a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b)
        if var <= 0:
            continue
        t = abs(float(b.mean() - a.mean())) / math.sqrt(float(var))
        if t >= best_t:
            best, best_t = k, t
    return best
