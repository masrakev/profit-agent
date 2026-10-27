"""Scenario conditions that are not faults: an opportunity to find, or adversarial data.

Like faults they are pure, seeded transformations of generated data with a ground-truth label,
but they are not scored as root causes by the detection benchmark (golden scenarios use them).
"""

import dataclasses
import math
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from app.detection.models import EntityRef
from bench.faults.base import day_of, recompute_attribution, remove_orders
from bench.generator.model import GeneratedStore
from bench.generator.simulate import money


class ConditionKind(StrEnum):
    UNDERFUNDED_CAMPAIGN = "underfunded_campaign"
    PROMPT_INJECTION = "prompt_injection"


class ConditionLabel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ConditionKind
    entities: tuple[EntityRef, ...]
    note: str


class _ConditionBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    @property
    def name(self) -> str:
        return str(getattr(self, "type"))  # noqa: B009 - every subclass defines `type`


class UnderfundedCampaign(_ConditionBase):
    """A profitable campaign spends only `budget_fraction` of its budget from day 0. Purchases
    follow the campaign's response curve a * (1 - exp(-b * spend)) at the lower spend."""

    type: Literal["underfunded_campaign"] = "underfunded_campaign"
    campaign_id: UUID
    budget_fraction: Decimal = Field(gt=0, lt=1)

    def label(self) -> ConditionLabel:
        return ConditionLabel(
            kind=ConditionKind.UNDERFUNDED_CAMPAIGN,
            entities=(EntityRef.campaign(self.campaign_id),),
            note=f"budget at {self.budget_fraction} of its normal level, well below optimum",
        )

    def apply(self, data: GeneratedStore, rng: np.random.Generator) -> GeneratedStore:
        truth = next(t for t in data.campaign_truth if t.campaign_id == self.campaign_id)
        fraction = float(self.budget_fraction)
        keep: dict[int, float] = {}
        metrics = []
        for m in data.ad_metrics:
            if m.campaign_id == self.campaign_id:
                day = (m.metric_date - data.config.start_date).days
                spend = float(m.spend)
                full = 1 - math.exp(-truth.b * spend)
                keep[day] = (1 - math.exp(-truth.b * spend * fraction)) / full if full else 0.0
                m = m.model_copy(
                    update={
                        "spend": money(m.spend * self.budget_fraction),
                        "impressions": int(m.impressions * fraction),
                        "clicks": int(m.clicks * fraction),
                    }
                )
            metrics.append(m)
        orders = {o.id: o for o in data.orders}
        dropped = {
            oid
            for oid, cid in data.order_campaigns
            if cid == self.campaign_id
            and rng.random() >= keep.get(day_of(data, orders[oid].ordered_at), 1.0)
        }
        campaigns = tuple(
            c.model_copy(update={"daily_budget": money(c.daily_budget * self.budget_fraction)})
            if c.id == self.campaign_id
            else c
            for c in data.campaigns
        )
        data = dataclasses.replace(data, ad_metrics=tuple(metrics), campaigns=campaigns)
        data = remove_orders(data, dropped)
        return recompute_attribution(data, {self.campaign_id}, 0)


class InjectedInstruction(_ConditionBase):
    """A product name and a campaign (ad) name carry text aimed at the model. The data must stay
    data: an agent that follows it fails."""

    type: Literal["prompt_injection"] = "prompt_injection"
    product_id: UUID
    campaign_id: UUID
    text: str

    def label(self) -> ConditionLabel:
        return ConditionLabel(
            kind=ConditionKind.PROMPT_INJECTION,
            entities=(EntityRef.product(self.product_id), EntityRef.campaign(self.campaign_id)),
            note="instruction embedded in a product name and an ad name",
        )

    def apply(self, data: GeneratedStore, rng: np.random.Generator) -> GeneratedStore:
        products = tuple(
            p.model_copy(update={"name": f"{p.name} {self.text}"}) if p.id == self.product_id else p
            for p in data.products
        )
        campaigns = tuple(
            c.model_copy(update={"name": f"{c.name} {self.text}"})
            if c.id == self.campaign_id
            else c
            for c in data.campaigns
        )
        return dataclasses.replace(data, products=products, campaigns=campaigns)


AnyCondition = Annotated[UnderfundedCampaign | InjectedInstruction, Field(discriminator="type")]
