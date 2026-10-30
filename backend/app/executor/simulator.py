"""Simulator adapter: the same actions on a synthetic store (ADR 0017).

The campaign row of the synthetic store changes (status, daily budget), and the change is
recorded as an event at the simulator's current day (`simulator_stores`), so that the benchmark
simulator can generate what the store does next with the action applied (bench/simulator.py)
and the outcome can be measured. Only synthetic stores registered with the simulator accept it.
"""

import json
from decimal import Decimal

from sqlalchemy import Engine, text

from app.db import tenant_transaction
from app.executor.adapters import AdapterError, CampaignRef, CampaignState, Change

MINOR_UNITS = {"JPY": 0, "KRW": 0, "BHD": 3, "KWD": 3}  # default: 2 decimals


def to_minor(amount: Decimal, currency: str) -> int:
    return int((amount * 10 ** MINOR_UNITS.get(currency, 2)).to_integral_value())


def from_minor(minor: int, currency: str) -> Decimal:
    return Decimal(minor) / Decimal(10) ** MINOR_UNITS.get(currency, 2)


class SimulatorAdapter:
    name = "simulator"

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.mutations = 0

    def read(self, campaign: CampaignRef) -> CampaignState:
        with tenant_transaction(self.engine, campaign.store_id) as conn:
            row = conn.execute(
                text(
                    "SELECT status, daily_budget FROM ad_campaigns WHERE store_id = :s AND id = :c"
                ),
                {"s": campaign.store_id, "c": campaign.campaign_id},
            ).first()
        if row is None:
            raise AdapterError("unknown campaign", retryable=False)
        return CampaignState(
            status="PAUSED" if row.status == "paused" else "ACTIVE",
            daily_budget_minor=to_minor(row.daily_budget, campaign.currency),
        )

    def validate(self, campaign: CampaignRef, change: Change) -> None:
        with tenant_transaction(self.engine, campaign.store_id) as conn:
            registered = conn.execute(
                text("SELECT 1 FROM simulator_stores WHERE store_id = :s"), {"s": campaign.store_id}
            ).first()
        if registered is None:
            raise AdapterError("the store is not run by the simulator", retryable=False)
        if change.daily_budget_minor is not None and change.daily_budget_minor <= 0:
            raise AdapterError("a daily budget must be positive", retryable=False)

    def apply(self, campaign: CampaignRef, change: Change) -> None:
        with tenant_transaction(self.engine, campaign.store_id) as conn:
            state = conn.execute(
                text("SELECT current_day FROM simulator_stores WHERE store_id = :s FOR UPDATE"),
                {"s": campaign.store_id},
            ).first()
            if state is None:
                raise AdapterError("the store is not run by the simulator", retryable=False)
            budget = (
                from_minor(change.daily_budget_minor, campaign.currency)
                if change.daily_budget_minor is not None
                else None
            )
            conn.execute(
                text(
                    "UPDATE ad_campaigns SET status = COALESCE(:status, status), "
                    "daily_budget = COALESCE(:budget, daily_budget) WHERE store_id = :s AND id = :c"
                ),
                {
                    "status": change.status.lower() if change.status else None,
                    "budget": budget,
                    "s": campaign.store_id,
                    "c": campaign.campaign_id,
                },
            )
            event = {
                "day": int(state.current_day),
                "campaign_id": str(campaign.campaign_id),
                "status": change.status,
                "daily_budget": str(budget) if budget is not None else None,
            }
            conn.execute(
                text(
                    "UPDATE simulator_stores SET events = events || CAST(:e AS jsonb), "
                    "updated_at = now() WHERE store_id = :s"
                ),
                {"e": json.dumps([event]), "s": campaign.store_id},
            )
        self.mutations += 1
