"""Exact Shapley values, and rounding that preserves their sum.

Values are computed with `fractions.Fraction`: Shapley weights (k! (n-k-1)! / n!) and per-unit
ratios are rational, so exact rational arithmetic guarantees efficiency, symmetry and the null
player property with no rounding at all. Conversion to `Decimal` happens once, at the end, on a
grid fine enough to be invisible at presentation, with the sum preserved exactly.
"""

from collections.abc import Callable, Hashable, Sequence
from decimal import Decimal
from fractions import Fraction
from math import factorial, floor

MAX_PLAYERS = 12


def shapley[P: Hashable](
    players: Sequence[P], value: Callable[[frozenset[P]], Fraction]
) -> dict[P, Fraction]:
    """phi_i = sum over S not containing i of |S|! (n-|S|-1)! / n! * (v(S + i) - v(S))."""
    n = len(players)
    if n > MAX_PLAYERS:
        raise ValueError(f"exact enumeration is limited to {MAX_PLAYERS} players")
    if len(set(players)) != n:
        raise ValueError("players must be distinct")
    weights = [Fraction(factorial(k) * factorial(n - k - 1), factorial(n)) for k in range(n)]
    cache: dict[int, Fraction] = {}

    def v(mask: int) -> Fraction:
        if mask not in cache:
            cache[mask] = value(frozenset(p for i, p in enumerate(players) if mask >> i & 1))
        return cache[mask]

    result: dict[P, Fraction] = {}
    for i, player in enumerate(players):
        bit = 1 << i
        total = Fraction(0)
        for mask in range(1 << n):
            if not mask & bit:
                total += weights[mask.bit_count()] * (v(mask | bit) - v(mask))
        result[player] = total
    return result


def round_to_grid(values: Sequence[Fraction], target: Decimal, quantum: Decimal) -> list[Decimal]:
    """Round exact values to multiples of `quantum` so that they sum exactly to `target`.

    Each value is floored to the grid; the remaining units go to the values with the largest
    remainders (or are taken from the smallest when the target is below the floors). Exact zeros
    never receive a unit, so a null player stays exactly zero. Ties break by position.
    """
    units = Fraction(target) / Fraction(quantum)
    if units.denominator != 1:
        raise ValueError(f"target {target} is not a multiple of {quantum}")
    scaled = [v / Fraction(quantum) for v in values]
    floors = [floor(s) for s in scaled]
    residual = int(units) - sum(floors)
    eligible = [i for i, v in enumerate(values) if v != 0]
    if residual and not eligible:
        raise ValueError("cannot reach a non-zero target with all-zero values")
    if residual > 0:
        order = sorted(eligible, key=lambda i: (-(scaled[i] - floors[i]), i))
        step = 1
    else:
        order = sorted(eligible, key=lambda i: (scaled[i] - floors[i], i))
        step = -1
    for k in range(abs(residual)):
        floors[order[k % len(order)]] += step
    return [f * quantum for f in floors]
