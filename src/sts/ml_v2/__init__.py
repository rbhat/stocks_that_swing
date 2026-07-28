"""Pure contracts and synthetic simulator for the independent ML-v2 study.

Gate 1 code in this package performs no filesystem, network, market-data, or
model-fitting I/O.  Later gates may adapt certified inputs into these types,
but the types and simulator remain pure.
"""

from sts.ml_v2.contracts import (
    Bar,
    Candidate,
    CashDistribution,
    ContractViolation,
    Delisting,
    PointInTimeManifest,
    SessionFrame,
    SourceRecord,
    Split,
    locked_setup_contract,
)
from sts.ml_v2.portfolio import (
    SimulatedCrash,
    SimulationResult,
    simulate,
)

__all__ = [
    "Bar",
    "Candidate",
    "CashDistribution",
    "ContractViolation",
    "Delisting",
    "PointInTimeManifest",
    "SessionFrame",
    "SimulatedCrash",
    "SimulationResult",
    "SourceRecord",
    "Split",
    "locked_setup_contract",
    "simulate",
]
