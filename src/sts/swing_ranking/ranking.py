"""Independent, SHA-tied leaderboards for ``swing-ranking-v1``."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from sts.swing_ranking.contracts import ContractViolation, _sha256
from sts.swing_ranking.metrics import SignalOccurrence, StrategyMetrics


class RankingViolation(ContractViolation):
    """Supplied strategy metrics cannot form an unambiguous leaderboard."""


@dataclass(frozen=True)
class RankedStrategy:
    """One raw-metric rank.  No composite score is represented anywhere."""

    strategy_revision_identity: str
    rank: int
    metrics: StrategyMetrics

    def __post_init__(self) -> None:
        _sha256(self.strategy_revision_identity, "strategy_revision_identity")
        if self.strategy_revision_identity != self.metrics.strategy_revision_identity:
            raise RankingViolation("ranked strategy identity does not match metrics")
        if isinstance(self.rank, bool) or not isinstance(self.rank, int) or self.rank < 1:
            raise RankingViolation("rank must be a positive integer")


@dataclass(frozen=True)
class ComparisonRow:
    """The raw values and independent ranks for a top-five-union strategy."""

    strategy_revision_identity: str
    gross_profit: Decimal
    maximum_drawdown: Decimal
    profit_drawdown_status: str
    profit_drawdown: Decimal | None
    profit_rank: int | None
    drawdown_rank: int | None
    profit_drawdown_rank: int | None

    def __post_init__(self) -> None:
        _sha256(self.strategy_revision_identity, "strategy_revision_identity")
        if not isinstance(self.gross_profit, Decimal) or not isinstance(self.maximum_drawdown, Decimal):
            raise RankingViolation("comparison metrics must be Decimal values")
        if self.profit_drawdown is not None and not isinstance(self.profit_drawdown, Decimal):
            raise RankingViolation("profit_drawdown must be Decimal or None")
        for name in ("profit_rank", "drawdown_rank", "profit_drawdown_rank"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
                raise RankingViolation(f"{name} must be a positive integer or None")


@dataclass(frozen=True)
class StrategyOverlap:
    """Pairwise permanent-ID/session overlap for the top-five union only."""

    left_strategy_revision_identity: str
    right_strategy_revision_identity: str
    candidate_signal_intersection: int
    candidate_signal_union: int
    candidate_signal_jaccard: Decimal | None
    filled_trade_intersection: int
    filled_trade_union: int
    filled_trade_jaccard: Decimal | None

    def __post_init__(self) -> None:
        left = _sha256(self.left_strategy_revision_identity, "left_strategy_revision_identity")
        right = _sha256(self.right_strategy_revision_identity, "right_strategy_revision_identity")
        if left >= right:
            raise RankingViolation("overlap identities must be distinct and SHA ordered")
        for name in (
            "candidate_signal_intersection",
            "candidate_signal_union",
            "filled_trade_intersection",
            "filled_trade_union",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RankingViolation(f"{name} must be a non-negative integer")
        for prefix in ("candidate_signal", "filled_trade"):
            intersection = getattr(self, f"{prefix}_intersection")
            union = getattr(self, f"{prefix}_union")
            ratio = getattr(self, f"{prefix}_jaccard")
            if intersection > union:
                raise RankingViolation("overlap intersection cannot exceed union")
            if union == 0:
                if ratio is not None:
                    raise RankingViolation("empty overlap union has no jaccard value")
            elif ratio != Decimal(intersection) / Decimal(union):
                raise RankingViolation("overlap jaccard must reconcile")


@dataclass(frozen=True)
class RankingReport:
    """Three independent leaderboards and their top-five-union comparison."""

    profit: tuple[RankedStrategy, ...]
    drawdown: tuple[RankedStrategy, ...]
    profit_drawdown: tuple[RankedStrategy, ...]
    comparison: tuple[ComparisonRow, ...]
    overlaps: tuple[StrategyOverlap, ...]

    def __post_init__(self) -> None:
        for name in ("profit", "drawdown", "profit_drawdown"):
            values = tuple(getattr(self, name))
            if not all(isinstance(value, RankedStrategy) for value in values):
                raise RankingViolation(f"{name} must contain RankedStrategy values")
            object.__setattr__(self, name, values)
        comparison = tuple(self.comparison)
        if not all(isinstance(row, ComparisonRow) for row in comparison):
            raise RankingViolation("comparison must contain ComparisonRow values")
        if tuple(row.strategy_revision_identity for row in comparison) != tuple(sorted(row.strategy_revision_identity for row in comparison)):
            raise RankingViolation("comparison must be strategy-SHA ordered")
        object.__setattr__(self, "comparison", comparison)
        overlaps = tuple(self.overlaps)
        if not all(isinstance(row, StrategyOverlap) for row in overlaps):
            raise RankingViolation("overlaps must contain StrategyOverlap values")
        object.__setattr__(self, "overlaps", overlaps)


def _require_metrics(metrics: Sequence[StrategyMetrics]) -> tuple[StrategyMetrics, ...]:
    values = tuple(metrics)
    if not all(isinstance(value, StrategyMetrics) for value in values):
        raise RankingViolation("metrics must contain StrategyMetrics values")
    identities = [value.strategy_revision_identity for value in values]
    if len(identities) != len(set(identities)):
        raise RankingViolation("strategy metrics must be unique by strategy SHA")
    return values


def _rank(values: Sequence[StrategyMetrics], metric: str) -> tuple[RankedStrategy, ...]:
    if metric == "profit":
        ordered = sorted(values, key=lambda value: (-value.gross_profit, value.strategy_revision_identity))
    elif metric == "drawdown":
        ordered = sorted(values, key=lambda value: (value.maximum_drawdown, value.strategy_revision_identity))
    elif metric == "profit_drawdown":
        status_order = {"positive_return_no_drawdown": 0, "defined": 1, "undefined": 2}
        ordered = sorted(
            values,
            key=lambda value: (
                status_order[value.profit_drawdown_status],
                -(value.profit_drawdown or Decimal(0)),
                value.strategy_revision_identity,
            ),
        )
    else:  # pragma: no cover - internal fixed alternatives only
        raise AssertionError(metric)
    return tuple(RankedStrategy(value.strategy_revision_identity, rank, value) for rank, value in enumerate(ordered, 1))


def _overlap(
    left: StrategyMetrics,
    right: StrategyMetrics,
) -> StrategyOverlap:
    left_id, right_id = sorted((left.strategy_revision_identity, right.strategy_revision_identity))
    if left_id != left.strategy_revision_identity:
        left, right = right, left

    def counts(left_items: tuple[SignalOccurrence, ...], right_items: tuple[SignalOccurrence, ...]) -> tuple[int, int, Decimal | None]:
        union = set(left_items) | set(right_items)
        intersection = set(left_items) & set(right_items)
        return len(intersection), len(union), None if not union else Decimal(len(intersection)) / Decimal(len(union))

    candidate_intersection, candidate_union, candidate_jaccard = counts(left.candidate_signals, right.candidate_signals)
    filled_intersection, filled_union, filled_jaccard = counts(left.filled_trade_signals, right.filled_trade_signals)
    return StrategyOverlap(
        left_strategy_revision_identity=left_id,
        right_strategy_revision_identity=right_id,
        candidate_signal_intersection=candidate_intersection,
        candidate_signal_union=candidate_union,
        candidate_signal_jaccard=candidate_jaccard,
        filled_trade_intersection=filled_intersection,
        filled_trade_union=filled_union,
        filled_trade_jaccard=filled_jaccard,
    )


def rank_strategies(metrics: Sequence[StrategyMetrics], *, top_n: int = 5) -> RankingReport:
    """Build independent raw-metric rankings; no gate or score is applied."""
    if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n < 1:
        raise RankingViolation("top_n must be a positive integer")
    values = _require_metrics(metrics)
    profit_all = _rank(values, "profit")
    drawdown_all = _rank(values, "drawdown")
    ratio_all = _rank(values, "profit_drawdown")
    profit = profit_all[:top_n]
    drawdown = drawdown_all[:top_n]
    ratio = ratio_all[:top_n]
    ranks = {
        "profit": {row.strategy_revision_identity: row.rank for row in profit_all},
        "drawdown": {row.strategy_revision_identity: row.rank for row in drawdown_all},
        "profit_drawdown": {row.strategy_revision_identity: row.rank for row in ratio_all},
    }
    by_id = {value.strategy_revision_identity: value for value in values}
    union_ids = sorted({row.strategy_revision_identity for row in (*profit, *drawdown, *ratio)})
    comparison = tuple(
        ComparisonRow(
            strategy_revision_identity=identity,
            gross_profit=by_id[identity].gross_profit,
            maximum_drawdown=by_id[identity].maximum_drawdown,
            profit_drawdown_status=by_id[identity].profit_drawdown_status,
            profit_drawdown=by_id[identity].profit_drawdown,
            profit_rank=ranks["profit"][identity],
            drawdown_rank=ranks["drawdown"][identity],
            profit_drawdown_rank=ranks["profit_drawdown"][identity],
        )
        for identity in union_ids
    )
    overlaps = tuple(
        _overlap(by_id[left], by_id[right])
        for index, left in enumerate(union_ids)
        for right in union_ids[index + 1 :]
    )
    return RankingReport(profit, drawdown, ratio, comparison, overlaps)
