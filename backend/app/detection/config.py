"""Typed access to the versioned thresholds file (`thresholds_v1.toml`)."""

import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict

DEFAULT_THRESHOLDS = Path(__file__).with_name("thresholds_v1.toml")


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RobustZ(_Section):
    baseline_days: int
    threshold: float
    persist_days: int
    rel_floor: float
    abs_floor: float


class Cusum(_Section):
    reference_start_day: int
    reference_days: int
    current_days: int
    k: float
    h: float
    abs_floor: float


class CampaignCpa(_Section):
    min_reference_purchases: float


class ProductUnits(_Section):
    min_baseline_units: float
    threshold: float


class RelFloor(_Section):
    rel_floor: float


class StoreRate(_Section):
    rel_floor: float
    cusum_k: float
    cusum_h: float


class CampaignProfit(_Section):
    window_days: int
    persist_days: int
    min_loss_ratio: float


class InventoryCover(_Section):
    persist_days: int
    spend_window_days: int


class RefundRate(_Section):
    window_days: int
    baseline_days: int
    warmup_days: int
    ratio: float
    alpha: float
    min_baseline_rate: float
    persist_days: int


class AttributionCollapse(_Section):
    window_days: int
    baseline_days: int
    max_ratio_of_baseline: float
    orders_stable_tolerance: float
    max_explained_share: float
    min_drop_sigmas: float
    persist_days: int


class Incrementality(_Section):
    window_days: int
    baseline_days: int
    min_rise: float
    sales_flat_tolerance: float
    min_baseline_purchases: float
    persist_days: int


class SeverityBands(_Section):
    medium: float
    high: float
    score_cap: float


class Incidents(_Section):
    gap_days: int


class Attribution(_Section):
    min_window_days: int
    max_window_days: int
    pre_incident_gap_days: int
    bonus: float
    min_driver_share: float


class MultipleTesting(_Section):
    fdr: float


class NoiseBand(_Section):
    resamples: int
    min_pairs: int
    low_percentile: float
    high_percentile: float


class DetectionConfig(_Section):
    version: int
    robust_z: RobustZ
    cusum: Cusum
    campaign_cpa: CampaignCpa
    product_units: ProductUnits
    product_unit_cost: RelFloor
    product_unit_fee: RelFloor
    store_payment_fee_rate: StoreRate
    store_gross_margin_rate: StoreRate
    campaign_profit: CampaignProfit
    inventory_cover: InventoryCover
    refund_rate: RefundRate
    attribution_collapse: AttributionCollapse
    incrementality: Incrementality
    severity: SeverityBands
    incidents: Incidents
    attribution: Attribution
    noise_band: NoiseBand
    multiple_testing: MultipleTesting


def load_config(path: Path | None = None) -> DetectionConfig:
    with (path or DEFAULT_THRESHOLDS).open("rb") as handle:
        return DetectionConfig.model_validate(tomllib.load(handle))


@lru_cache(maxsize=1)
def default_config() -> DetectionConfig:
    return load_config()
