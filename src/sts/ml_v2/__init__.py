"""Reusable research contracts and deterministic portfolio simulator.

The package remains free of network, market-download, model-fitting, and
development-run I/O. The active study may adapt these implementation
components under a new study identity without changing their tested behavior.
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
