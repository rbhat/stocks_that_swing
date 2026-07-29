"""Immutable contracts for the ``swing-ranking-v1`` discovery study."""

from sts.swing_ranking.candidates import (
    ConditionSpec,
    FeatureSpec,
    StrategyProgram,
    build_feature_matrix,
    generate_candidates,
)
from sts.swing_ranking.contracts import (
    Candidate,
    CandidateGrammar,
    Charter,
    ContractViolation,
    DiscoveryProtocol,
    EntryGeometry,
    SignalFact,
    SourceFact,
    SourceLimitation,
    StrategyRevision,
    locked_tie_break,
    swing_ranking_charter,
)

__all__ = [
    "Candidate",
    "CandidateGrammar",
    "Charter",
    "ConditionSpec",
    "ContractViolation",
    "DiscoveryProtocol",
    "EntryGeometry",
    "FeatureSpec",
    "SignalFact",
    "SourceFact",
    "SourceLimitation",
    "StrategyProgram",
    "StrategyRevision",
    "build_feature_matrix",
    "generate_candidates",
    "locked_tie_break",
    "swing_ranking_charter",
]
