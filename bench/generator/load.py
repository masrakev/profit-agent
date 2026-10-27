"""Write a generated store to PostgreSQL through the application's repositories."""

from sqlalchemy import Engine

from app.db import refresh_planner_statistics, tenant_transaction
from app.domain.audit import append_audit
from app.domain.repositories import (
    AdMetricsRepository,
    CampaignRepository,
    CostItemRepository,
    InventoryRepository,
    OrderRepository,
    ProductRepository,
    RefundRepository,
    StoreRepository,
)
from bench.generator.config import GeneratorConfig
from bench.generator.model import GeneratedStore


class StoreExistsError(RuntimeError):
    pass


def load(engine: Engine, data: GeneratedStore, config: GeneratorConfig) -> None:
    store_id = data.store.store_id
    with tenant_transaction(engine, store_id) as conn:
        stores = StoreRepository(conn)
        if stores.get(store_id) is not None:
            raise StoreExistsError(str(store_id))
        stores.create(data.store)
        ProductRepository(conn).add_many(data.products)
        CampaignRepository(conn).add_many(data.campaigns, data.campaign_products)
        OrderRepository(conn).add_many(data.orders, data.lines)
        RefundRepository(conn).add_many(data.refunds)
        InventoryRepository(conn).add_many(data.inventory)
        AdMetricsRepository(conn).add_many(data.ad_metrics)
        CostItemRepository(conn).add_many(data.cost_items)
        append_audit(
            conn,
            store_id,
            actor="bench:generator",
            action="store.generated",
            payload={
                "config": config.model_dump(),
                "config_fingerprint": config.fingerprint,
                "counts": data.counts(),
            },
        )
    # After commit: without fresh statistics the first fact queries on a new store are very slow.
    refresh_planner_statistics(engine)
