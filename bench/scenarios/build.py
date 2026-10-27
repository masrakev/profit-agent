"""Build the benchmark suites deterministically and write their manifests.

    uv run python -m bench.scenarios.build            # both suites
    uv run python -m bench.scenarios.build --check    # fail if committed manifests differ

`test` (the reported suite): 5 scenarios per fault type + 10 healthy = 50.
`dev` (threshold tuning only): 3 per fault type + 6 healthy = 30, on different seeds.
Targets (campaign, product) are chosen from each store's own pre-fault data.
"""

import argparse
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import numpy as np

from bench.faults import (
    AnyFault,
    Cannibalization,
    CpaDrift,
    FeeIncrease,
    MixShift,
    RefundSpike,
    StockoutOnPromoted,
    SupplierCostIncrease,
    TrackingBreak,
)
from bench.generator import GeneratedStore, GeneratorConfig, generate
from bench.scenarios.manifest import ScenarioManifest, Suite, load_suite, save, suite_dir

D = Decimal

# Bench stores are healthy unless a fault is injected: no natural supplier cost changes,
# stock planned for ad-driven demand, and campaigns budgeted below their profit optimum.
BENCH_CONFIG = {
    "cost_change_probability": D(0),
    "initial_stock_days": (45, 60),
    "reorder_policy": "adaptive",
    "campaign_budget_policy": "profit_optimal",
}
SEED_BASE: dict[Suite, int] = {"test": 10_000, "dev": 50_000}
PER_FAULT: dict[Suite, int] = {"test": 5, "dev": 3}
HEALTHY: dict[Suite, int] = {"test": 10, "dev": 6}
MIN_CAMPAIGN_HISTORY_DAYS = 35


@dataclass(frozen=True)
class Variant:
    magnitude: Decimal
    start_day: int
    subtle: bool = False
    product_scope: bool = False  # fee_increase: per-unit fee of one product instead of payment fees


# Five variants per fault type: one deliberately subtle, the rest increasingly strong.
VARIANTS: dict[str, list[Variant]] = {
    "cpa_drift": [
        Variant(D("0.20"), 84, subtle=True),
        Variant(D("0.35"), 56),
        Variant(D("0.50"), 70),
        Variant(D("0.65"), 63),
        Variant(D("0.80"), 77),
    ],
    "cannibalization": [
        Variant(D("0.30"), 77, subtle=True),
        Variant(D("0.50"), 63),
        Variant(D("0.80"), 70),
        Variant(D("1.00"), 56),
        Variant(D("1.50"), 84),
    ],
    "stockout_on_promoted": [
        Variant(D(1), 88, subtle=True),
        Variant(D(1), 60),
        Variant(D(1), 70),
        Variant(D(1), 66),
        Variant(D(1), 78),
    ],
    "supplier_cost_increase": [
        Variant(D("0.05"), 80, subtle=True),
        Variant(D("0.10"), 58),
        Variant(D("0.20"), 67),
        Variant(D("0.30"), 74),
        Variant(D("0.50"), 62),
    ],
    "refund_spike": [
        Variant(D("0.05"), 75, subtle=True),
        Variant(D("0.10"), 60),
        Variant(D("0.15"), 68),
        Variant(D("0.25"), 64),
        Variant(D("0.40"), 71),
    ],
    "mix_shift": [
        Variant(D("0.15"), 82, subtle=True),
        Variant(D("0.25"), 59),
        Variant(D("0.35"), 66),
        Variant(D("0.50"), 73),
        Variant(D("0.65"), 61),
    ],
    "fee_increase": [
        Variant(D("0.15"), 79, subtle=True),
        Variant(D("0.30"), 61),
        Variant(D("0.50"), 69, product_scope=True),
        Variant(D("0.60"), 65),
        Variant(D("1.00"), 72, product_scope=True),
    ],
    "tracking_break": [
        Variant(D("0.60"), 81, subtle=True),
        Variant(D("0.80"), 57),
        Variant(D("0.90"), 65),
        Variant(D("1.00"), 72),
        Variant(D("1.00"), 60),
    ],
}
DEV_VARIANTS = (0, 2, 4)  # subtle, medium, strong


def bench_config(seed: int) -> GeneratorConfig:
    return GeneratorConfig.model_validate({"seed": seed, **BENCH_CONFIG})


def _units_before(data: GeneratedStore, day: int) -> Counter[UUID]:
    """Units sold per product in the 28 days before `day`."""
    start = data.config.start_date
    order_day = {o.id: (o.ordered_at.date() - start).days for o in data.orders}
    units: Counter[UUID] = Counter()
    for line in data.lines:
        if day - 28 <= order_day[line.order_id] < day:
            units[line.product_id] += line.quantity
    return units


def _ad_orders_before(data: GeneratedStore, day: int) -> Counter[UUID]:
    start = data.config.start_date
    order_day = {o.id: (o.ordered_at.date() - start).days for o in data.orders}
    return Counter(cid for oid, cid in data.order_campaigns if day - 28 <= order_day[oid] < day)


def _eligible_campaigns(data: GeneratedStore, day: int) -> list[UUID]:
    """Campaigns with enough history before the fault, busiest first."""
    ad_orders = _ad_orders_before(data, day)
    old_enough = {
        t.campaign_id for t in data.campaign_truth if t.start_day + MIN_CAMPAIGN_HISTORY_DAYS <= day
    }
    return sorted(
        (c for c in old_enough if ad_orders[c] >= 28),
        key=lambda c: (-ad_orders[c], str(c)),
    )


def _pick(rng: np.random.Generator, items: list[UUID], subtle: bool) -> UUID:
    """A strong variant targets one of the busiest entities; a subtle one a quieter entity."""
    pool = (
        items[len(items) // 2 :] if subtle and len(items) > 1 else items[: max(1, len(items) // 2)]
    )
    return pool[int(rng.integers(0, len(pool)))]


def _fault(
    kind: str, v: Variant, data: GeneratedStore, rng: np.random.Generator
) -> AnyFault | None:
    units = _units_before(data, v.start_day)
    products = sorted(units, key=lambda p: (-units[p], str(p)))
    campaigns = _eligible_campaigns(data, v.start_day)
    if kind in {"cpa_drift", "cannibalization", "tracking_break", "stockout_on_promoted"}:
        if not campaigns:
            return None
        campaign = _pick(rng, campaigns, v.subtle)
        if kind == "cpa_drift":
            return CpaDrift(campaign_id=campaign, start_day=v.start_day, magnitude=v.magnitude)
        if kind == "cannibalization":
            return Cannibalization(
                campaign_id=campaign, start_day=v.start_day, magnitude=v.magnitude
            )
        if kind == "tracking_break":
            return TrackingBreak(campaign_id=campaign, start_day=v.start_day, magnitude=v.magnitude)
        promoted = sorted(
            (link.product_id for link in data.campaign_products if link.campaign_id == campaign),
            key=lambda p: (-units[p], str(p)),
        )
        product = promoted[-1] if v.subtle else promoted[0]
        return StockoutOnPromoted(
            campaign_id=campaign, product_id=product, start_day=v.start_day, magnitude=v.magnitude
        )
    if kind == "mix_shift":
        return MixShift(start_day=v.start_day, magnitude=v.magnitude)
    if kind == "fee_increase" and not v.product_scope:
        return FeeIncrease(start_day=v.start_day, magnitude=v.magnitude)
    product = _pick(rng, products, v.subtle)
    if kind == "fee_increase":
        return FeeIncrease(start_day=v.start_day, magnitude=v.magnitude, product_id=product)
    if kind == "supplier_cost_increase":
        return SupplierCostIncrease(
            product_id=product, start_day=v.start_day, magnitude=v.magnitude
        )
    if kind == "refund_spike":
        return RefundSpike(product_id=product, start_day=v.start_day, magnitude=v.magnitude)
    raise ValueError(kind)


def build_suite(suite: Suite, only: set[str] | None = None) -> list[ScenarioManifest]:
    """Manifests for a suite. `only` restricts to scenario ids (used by tests).

    Scenario number `i` draws seeds from its own range `base + 100 * i + attempt`, so building
    one scenario alone gives exactly the manifest of the full build.
    """
    manifests: list[ScenarioManifest] = []
    plan: list[tuple[str, str, Variant | None]] = []
    for kind, variants in VARIANTS.items():
        chosen = variants if suite == "test" else [variants[i] for i in DEV_VARIANTS]
        for number, chosen_variant in enumerate(chosen[: PER_FAULT[suite]], start=1):
            plan.append((f"{suite}-{kind}-{number:02d}", kind, chosen_variant))
    plan.extend((f"{suite}-healthy-{n:02d}", "healthy", None) for n in range(1, HEALTHY[suite] + 1))
    for index, (scenario_id, kind, variant) in enumerate(plan):
        if only is not None and scenario_id not in only:
            continue
        manifests.append(
            _build_one(suite, scenario_id, kind, variant, SEED_BASE[suite] + 100 * index)
        )
    return manifests


def _build_one(
    suite: Suite, scenario_id: str, kind: str, variant: Variant | None, first_seed: int
) -> ScenarioManifest:
    if variant is None:
        return ScenarioManifest(
            scenario_id=scenario_id,
            suite=suite,
            description="healthy store, no fault",
            config=bench_config(first_seed),
        )
    for seed in range(first_seed, first_seed + 100):
        config = bench_config(seed)
        fault = _fault(kind, variant, generate(config), np.random.default_rng([seed, 2]))
        if fault is None:
            continue  # no eligible target in this store: try the next seed of this range
        day = (config.start_date + timedelta(days=variant.start_day)).isoformat()
        return ScenarioManifest(
            scenario_id=scenario_id,
            suite=suite,
            description=(
                f"{kind} {'(subtle) ' if variant.subtle else ''}magnitude {variant.magnitude} "
                f"from day {variant.start_day} ({day})"
            ),
            config=config,
            faults=(fault,),
            labels=(fault.label(),),
        )
    raise RuntimeError(f"{scenario_id}: no store with an eligible target")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build benchmark scenario manifests")
    parser.add_argument("--suite", choices=["dev", "test"], action="append")
    parser.add_argument("--check", action="store_true", help="compare with committed manifests")
    args = parser.parse_args(argv)
    suites: list[Suite] = args.suite or ["dev", "test"]
    status = 0
    for suite in suites:
        built = build_suite(suite)
        if args.check:
            fresh = sorted(m.to_json() for m in built)
            if fresh != sorted(m.to_json() for m in load_suite(suite)):
                sys.stderr.write(f"{suite}: committed manifests differ from a fresh build\n")
                status = 1
            continue
        for old in suite_dir(suite).glob("*.json"):
            old.unlink()
        for manifest in built:
            save(manifest)
        sys.stdout.write(f"{suite}: {len(built)} scenarios written to {suite_dir(suite)}\n")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
