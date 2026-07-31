"""Closed-OOS revision-selection analysis for ``swing-ranking-v1``."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, getcontext
from itertools import combinations
from pathlib import Path

getcontext().prec = 50

ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = ROOT / "runs" / "swing-ranking-v1"
WINDOWS = ("development", "validation")
METRICS = ("profit", "drawdown", "profit_drawdown")


@dataclass(frozen=True)
class AnalysisResult:
    strategies: dict[str, dict[str, object]]
    metrics: dict[str, dict[str, dict[str, object]]]
    ranks: dict[str, dict[str, dict[str, int]]]
    options: dict[str, set[str]]
    spearman: dict[str, Decimal]
    shared_top20: dict[str, set[str]]
    overlap: dict[str, dict[str, dict[str, Decimal | int | None]]]


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_content_hash(directory: Path, file_name: str) -> None:
    manifest = _load_json(directory / "manifest.json")
    expected = manifest["content_hashes"][file_name]
    observed = hashlib.sha256((directory / file_name).read_bytes()).hexdigest()
    if observed != expected:
        raise ValueError(f"{directory.name}/{file_name} does not match its manifest")


def _load_metrics(window: str) -> dict[str, dict[str, object]]:
    directory = RUN_ROOT / f"{window}-v1"
    _verify_content_hash(directory, "metrics.jsonl")
    _verify_content_hash(directory, "ranking.json")
    records: dict[str, dict[str, object]] = {}
    with (directory / "metrics.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)["record"]
            identity = record["strategy_revision_identity"]
            record["gross_profit"] = Decimal(record["gross_profit"])
            record["maximum_drawdown"] = Decimal(record["maximum_drawdown"])
            ratio = record["profit_drawdown"]
            record["profit_drawdown"] = None if ratio is None else Decimal(ratio)
            records[identity] = record
    return records


def _load_strategies() -> dict[str, dict[str, object]]:
    strategy_root = RUN_ROOT / "development-v1" / "strategies"
    strategies: dict[str, dict[str, object]] = {}
    for path in sorted(strategy_root.glob("*.json")):
        document = _load_json(path)
        strategy = document["strategy"]
        strategies[document["strategy_identity"]] = {
            "name": strategy["strategy_name"],
            "readable_rules": tuple(strategy["readable_rules"]),
        }
    return strategies


def _rank(
    records: dict[str, dict[str, object]],
) -> dict[str, dict[str, int]]:
    ordered = {
        "profit": sorted(
            records,
            key=lambda identity: (-records[identity]["gross_profit"], identity),
        ),
        "drawdown": sorted(
            records,
            key=lambda identity: (records[identity]["maximum_drawdown"], identity),
        ),
        "profit_drawdown": sorted(
            records,
            key=lambda identity: (
                {"positive_return_no_drawdown": 0, "defined": 1, "undefined": 2}[
                    records[identity]["profit_drawdown_status"]
                ],
                -(records[identity]["profit_drawdown"] or Decimal(0)),
                identity,
            ),
        ),
    }
    return {
        metric: {
            identity: rank
            for rank, identity in enumerate(identities, start=1)
        }
        for metric, identities in ordered.items()
    }


def _spearman(
    development_ranks: dict[str, int],
    validation_ranks: dict[str, int],
) -> Decimal:
    identities = sorted(development_ranks)
    count = Decimal(len(identities))
    development_mean = (
        sum(Decimal(development_ranks[item]) for item in identities) / count
    )
    validation_mean = (
        sum(Decimal(validation_ranks[item]) for item in identities) / count
    )
    covariance = sum(
        (Decimal(development_ranks[item]) - development_mean)
        * (Decimal(validation_ranks[item]) - validation_mean)
        for item in identities
    )
    development_variance = sum(
        (Decimal(development_ranks[item]) - development_mean) ** 2
        for item in identities
    )
    validation_variance = sum(
        (Decimal(validation_ranks[item]) - validation_mean) ** 2
        for item in identities
    )
    return covariance / (development_variance * validation_variance).sqrt()


def _top_union(
    ranks: dict[str, dict[str, int]],
    limit: int,
) -> set[str]:
    return {
        identity
        for metric in METRICS
        for identity, rank in ranks[metric].items()
        if rank <= limit
    }


def _filled_trade_overlap(
    identities: set[str],
    records: dict[str, dict[str, object]],
) -> dict[str, Decimal | int | None]:
    pair_values: list[Decimal] = []
    for left, right in combinations(sorted(identities), 2):
        left_trades = {
            (item["permanent_id"], item["session"])
            for item in records[left]["filled_trade_signals"]
        }
        right_trades = {
            (item["permanent_id"], item["session"])
            for item in records[right]["filled_trade_signals"]
        }
        union = left_trades | right_trades
        pair_values.append(
            Decimal(len(left_trades & right_trades)) / Decimal(len(union))
            if union
            else Decimal(0)
        )
    return {
        "pairs": len(pair_values),
        "mean": (
            sum(pair_values, Decimal(0)) / Decimal(len(pair_values))
            if pair_values
            else None
        ),
        "maximum": max(pair_values) if pair_values else None,
    }


def build_analysis() -> AnalysisResult:
    metrics = {window: _load_metrics(window) for window in WINDOWS}
    strategies = _load_strategies()
    development = metrics["development"]
    validation = metrics["validation"]
    if not (
        len(development)
        == len(validation)
        == len(strategies)
        == 144
        and set(development) == set(validation) == set(strategies)
    ):
        raise ValueError("development, validation, and strategy identities do not align")

    ranks = {window: _rank(metrics[window]) for window in WINDOWS}
    development_ranks = ranks["development"]
    validation_ranks = ranks["validation"]
    shared_top20 = {
        metric: {
            identity
            for identity in development
            if development_ranks[metric][identity] <= 20
            and validation_ranks[metric][identity] <= 20
        }
        for metric in METRICS
    }
    options = {
        "A": _top_union(validation_ranks, 5),
        "B": {
            identity
            for identity in validation
            if sum(
                validation_ranks[metric][identity] <= 5 for metric in METRICS
            )
            >= 2
        },
        "C": set().union(*shared_top20.values()),
    }
    overlap = {
        option: {
            window: _filled_trade_overlap(identities, metrics[window])
            for window in WINDOWS
        }
        for option, identities in options.items()
    }
    return AnalysisResult(
        strategies=strategies,
        metrics=metrics,
        ranks=ranks,
        options=options,
        spearman={
            metric: _spearman(
                development_ranks[metric],
                validation_ranks[metric],
            )
            for metric in METRICS
        },
        shared_top20=shared_top20,
        overlap=overlap,
    )


if __name__ == "__main__":
    result = build_analysis()
    summary = {
        "revision_count": len(result.strategies),
        "option_counts": {
            option: len(identities)
            for option, identities in result.options.items()
        },
        "spearman": {
            metric: str(value) for metric, value in result.spearman.items()
        },
        "shared_top20": {
            metric: len(identities)
            for metric, identities in result.shared_top20.items()
        },
        "validation_mean_filled_trade_overlap": {
            option: str(result.overlap[option]["validation"]["mean"])
            for option in result.options
        },
    }
    print(json.dumps(summary, indent=2))
