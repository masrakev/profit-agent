"""One interface for the platforms actions execute on (Task 4 B3, ADR 0017)."""

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

CampaignStatus = Literal["ACTIVE", "PAUSED"]


@dataclass(frozen=True)
class CampaignRef:
    store_id: UUID
    campaign_id: UUID  # ours
    external_id: str  # the platform's
    currency: str


@dataclass(frozen=True)
class CampaignState:
    status: CampaignStatus
    daily_budget_minor: int | None  # the currency's minor unit (cents for USD)


@dataclass(frozen=True)
class Change:
    """The target state; None leaves a field as it is."""

    status: CampaignStatus | None = None
    daily_budget_minor: int | None = None

    def satisfied_by(self, state: CampaignState) -> bool:
        return (self.status is None or state.status == self.status) and (
            self.daily_budget_minor is None or state.daily_budget_minor == self.daily_budget_minor
        )


class AdapterError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool, code: str | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.code = code


class Adapter(Protocol):
    name: str

    def read(self, campaign: CampaignRef) -> CampaignState: ...

    def validate(self, campaign: CampaignRef, change: Change) -> None:
        """Dry run: raises AdapterError if the platform would refuse the change."""
        ...

    def apply(self, campaign: CampaignRef, change: Change) -> None: ...
