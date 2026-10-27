"""Fault injection: pure, seeded transformations of generated data with ground-truth labels."""

from bench.faults.base import Driver, FaultLabel
from bench.faults.catalog import (
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

__all__ = [
    "AnyFault",
    "Cannibalization",
    "CpaDrift",
    "Driver",
    "FaultLabel",
    "FeeIncrease",
    "MixShift",
    "RefundSpike",
    "StockoutOnPromoted",
    "SupplierCostIncrease",
    "TrackingBreak",
]
