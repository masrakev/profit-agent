"""Generated data: domain records plus the ground truth used to produce them."""

from dataclasses import dataclass
from uuid import UUID

from app.domain.models import (
    AdCampaign,
    AdCampaignProduct,
    AdMetricDaily,
    CostItem,
    InventorySnapshot,
    Order,
    OrderLine,
    Product,
    Refund,
    Store,
)
from bench.generator.config import GeneratorConfig


@dataclass(frozen=True)
class ProductTruth:
    product_id: UUID
    base_daily_demand: float
    refund_rate: float
    lead_time_days: int
    reorder_point: int
    reorder_quantity: int


@dataclass(frozen=True)
class CampaignTruth:
    """Ad response: purchases = a * (1 - exp(-b * spend)) + noise."""

    campaign_id: UUID
    a: float
    b: float
    noise_sd: float
    attribution_bias: float
    start_day: int


@dataclass(frozen=True)
class GeneratedStore:
    store: Store
    products: tuple[Product, ...]
    orders: tuple[Order, ...]
    lines: tuple[OrderLine, ...]
    refunds: tuple[Refund, ...]
    inventory: tuple[InventorySnapshot, ...]
    campaigns: tuple[AdCampaign, ...]
    campaign_products: tuple[AdCampaignProduct, ...]
    ad_metrics: tuple[AdMetricDaily, ...]
    cost_items: tuple[CostItem, ...]
    product_truth: tuple[ProductTruth, ...]
    campaign_truth: tuple[CampaignTruth, ...]
    lost_sales_units: int
    config: GeneratorConfig
    # (order id, campaign id) for every ad-driven order: ground truth, never loaded.
    order_campaigns: tuple[tuple[UUID, UUID], ...] = ()

    def counts(self) -> dict[str, int]:
        return {
            "products": len(self.products),
            "orders": len(self.orders),
            "order_lines": len(self.lines),
            "refunds": len(self.refunds),
            "inventory_snapshots": len(self.inventory),
            "ad_campaigns": len(self.campaigns),
            "ad_campaign_products": len(self.campaign_products),
            "ad_metrics_daily": len(self.ad_metrics),
            "cost_items": len(self.cost_items),
        }
