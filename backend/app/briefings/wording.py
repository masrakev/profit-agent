"""Code-written words for briefings and alerts: causes, drivers and options, without numbers."""

from app.causes.drivers import Driver
from app.decisions.options import OptionKind
from app.detection.models import AlertLevel, FaultFamily

CAUSES: dict[FaultFamily, str] = {
    FaultFamily.CPA_DRIFT: "its cost per purchase keeps rising",
    FaultFamily.CANNIBALIZATION: "its ads may be buying sales that would happen anyway",
    FaultFamily.STOCKOUT_ON_PROMOTED: "ads keep spending on a product that is out of stock",
    FaultFamily.SUPPLIER_COST_INCREASE: "its unit cost from the supplier went up",
    FaultFamily.REFUND_SPIKE: "its refunds rose sharply",
    FaultFamily.MIX_SHIFT: "sales moved towards lower-margin products",
    FaultFamily.FEE_INCREASE: "fees per order went up",
    FaultFamily.TRACKING_BREAK: "the ad platform's tracking looks broken",
}
LEVELS: dict[AlertLevel, str] = {
    AlertLevel.CRITICAL: "critical",
    AlertLevel.HIGH: "high",
    AlertLevel.NORMAL: "normal",
    AlertLevel.DATA_QUALITY: "data issue",
    AlertLevel.WATCHLIST: "watchlist",
}
DRIVERS: dict[Driver, str] = {
    Driver.VOLUME: "volume",
    Driver.MIX: "product mix",
    Driver.PRICE: "price",
    Driver.UNIT_COST: "unit cost",
    Driver.FEES: "fees",
    Driver.REFUNDS: "refunds",
    Driver.AD_SPEND: "ad spend",
    Driver.FIXED_COSTS: "fixed costs",
}
OPTIONS: dict[OptionKind, str] = {
    OptionKind.REDUCE_BUDGET: "reduce its daily budget",
    OptionKind.PAUSE_CAMPAIGN: "pause the campaign",
    OptionKind.PAUSE_UNTIL_RESTOCK: "pause the campaigns that promote it until it is restocked",
    OptionKind.INCREASE_BUDGET: "raise its daily budget, within the cap",
    OptionKind.PREPARE_REORDER: "prepare a reorder for the supplier",
    OptionKind.PREPARE_PRICE_CHANGE: "prepare a price change",
    OptionKind.REVIEW_SUPPLIER: "review the supplier",
    OptionKind.INCREMENTALITY_TEST: "run an incrementality test",
    OptionKind.INVESTIGATE_PRODUCT_QUALITY: "investigate the product's quality",
    OptionKind.FIX_TRACKING: "fix the tracking before any budget change",
    OptionKind.MONITOR: "keep watching it",
}


def cause(family: FaultFamily | None) -> str:
    return CAUSES.get(family, "something changed") if family is not None else "something changed"


def option(kind: str) -> str:
    try:
        return OPTIONS[OptionKind(kind)]
    except (ValueError, KeyError):
        return kind.replace("_", " ")
