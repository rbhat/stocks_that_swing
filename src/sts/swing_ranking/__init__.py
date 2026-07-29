"""Immutable contracts for the ``swing-ranking-v1`` discovery study."""

from sts.swing_ranking.contracts import (
    Candidate,
    CandidateGrammar,
    Charter,
    ContractViolation,
    DiscoveryProtocol,
    EntryGeometry,
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
    "ContractViolation",
    "DiscoveryProtocol",
    "EntryGeometry",
    "SourceFact",
    "SourceLimitation",
    "StrategyRevision",
    "locked_tie_break",
    "swing_ranking_charter",
]
