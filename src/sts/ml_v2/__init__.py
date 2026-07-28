"""Contracts, source certification, and simulator for the ML-v2 study.

The package remains free of network, market-download, model-fitting, and
development-run I/O. Gate 2 source evidence is adapted into fail-closed
manifest values; later gates may adapt certified inputs into the Gate 1
types, but the contracts and simulator remain pure.
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
from sts.ml_v2.source_certification import (
    Gate2SourceManifest,
    SourceCertification,
)

__all__ = [
    "Bar",
    "Candidate",
    "CashDistribution",
    "ContractViolation",
    "Delisting",
    "Gate2SourceManifest",
    "PointInTimeManifest",
    "SessionFrame",
    "SimulatedCrash",
    "SimulationResult",
    "SourceCertification",
    "SourceRecord",
    "Split",
    "locked_setup_contract",
    "simulate",
]
