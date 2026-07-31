"""Immutable cohort analysis and sealing for the one-time OOS opening."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from statistics import median

from sts.swing_ranking.artifacts import (
    ArtifactPackage,
    ArtifactViolation,
    ArtifactWriteResult,
    write_artifact_package,
)
from sts.swing_ranking.config import CohortSelection
from sts.swing_ranking.identity import canonical_bytes, identity_hash, sha256_hex
from sts.swing_ranking.metrics import maximum_drawdown

D0 = Decimal(0)
D100 = Decimal(100)


@dataclass(frozen=True)
class OosCohortResult:
    analysis: ArtifactWriteResult
    seal: ArtifactWriteResult


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ArtifactViolation(f"{path} must contain a JSON object")
    return value


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if not all(isinstance(row, dict) for row in rows):
        raise ArtifactViolation(f"{path} must contain JSON objects")
    return rows


def _decimal(value: object) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ArtifactViolation("cohort input contains a non-finite decimal")
    return result


def _json(value: object) -> bytes:
    return canonical_bytes(value) + b"\n"


def _jsonl(rows: list[object]) -> bytes:
    return b"".join(_json(row) for row in rows)


def _artifact_inventory(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_hex(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _drawdown_dollars(equity: list[Decimal]) -> Decimal:
    peak = equity[0]
    worst = D0
    for value in equity:
        peak = max(peak, value)
        worst = max(worst, peak - value)
    return worst


def _curve_metrics(equity: list[Decimal], starting_capital: Decimal) -> dict[str, object]:
    ending = equity[-1]
    profit = ending - starting_capital
    gross_return = profit / starting_capital
    drawdown = maximum_drawdown(equity)
    return {
        "starting_capital": starting_capital,
        "ending_equity": ending,
        "gross_profit": profit,
        "gross_return": gross_return,
        "maximum_drawdown_dollars": _drawdown_dollars(equity),
        "maximum_drawdown": drawdown,
        "profit_drawdown": None if drawdown == D0 else gross_return / drawdown,
    }


def _chunks(rows: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    chunks: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    previous: str | None = None
    for wrapper in rows:
        record = wrapper.get("record")
        if not isinstance(record, dict) or not isinstance(record.get("session"), str):
            raise ArtifactViolation("equity rows must contain dated records")
        session = record["session"]
        if previous is not None and session <= previous:
            chunks.append(current)
            current = []
        current.append(record)
        previous = session
    if current:
        chunks.append(current)
    return chunks


def _short_name(name: str) -> str:
    return name.replace("monthly-ema6-", "M6-").replace("weekly-ema13-", "W13-")


def build_oos_cohort_analysis(
    *,
    oos_path: Path,
    selection: CohortSelection,
    output: Path,
) -> ArtifactWriteResult:
    """Audit one immutable OOS artifact and publish cohort analysis atomically."""
    oos_path = Path(oos_path)
    manifest = _read_json(oos_path / "manifest.json")
    if manifest.get("artifact_identity") is None:
        raise ArtifactViolation("OOS manifest lacks an artifact identity")
    expected_inventory = manifest.get("content_hashes")
    if not isinstance(expected_inventory, dict):
        raise ArtifactViolation("OOS manifest lacks content hashes")
    for name, expected in expected_inventory.items():
        path = oos_path / str(name)
        if not path.is_file() or sha256_hex(path.read_bytes()) != expected:
            raise ArtifactViolation(f"OOS content hash mismatch: {name}")
    selected_ids = tuple(sorted(member.strategy_revision_identity for member in selection.members))
    if (
        manifest.get("evidence_window") != "oos"
        or tuple(manifest.get("strategy_identities", ())) != selected_ids
        or manifest.get("record_counts", {}).get("metrics") != 9
    ):
        raise ArtifactViolation("OOS manifest does not match the approved nine revisions")

    strategy_names: dict[str, str] = {}
    for identity in selected_ids:
        row = _read_json(oos_path / "strategies" / f"{identity}.json")
        strategy = row.get("strategy")
        if not isinstance(strategy, dict) or not isinstance(strategy.get("strategy_name"), str):
            raise ArtifactViolation("strategy artifact lacks its readable name")
        strategy_names[identity] = strategy["strategy_name"]
    expected_names = {
        member.strategy_revision_identity: member.strategy_name for member in selection.members
    }
    if strategy_names != expected_names:
        raise ArtifactViolation("OOS strategy names do not match the approved selection")

    metric_wrappers = _read_jsonl(oos_path / "metrics.jsonl")
    metrics = [row["record"] for row in metric_wrappers]
    if not all(isinstance(row, dict) for row in metrics):
        raise ArtifactViolation("metric rows are malformed")
    metric_by_id = {str(row["strategy_revision_identity"]): row for row in metrics}
    if set(metric_by_id) != set(selected_ids):
        raise ArtifactViolation("metric identities do not match the approved selection")

    equity_chunks = _chunks(_read_jsonl(oos_path / "equity.jsonl"))
    if len(equity_chunks) != 9:
        raise ArtifactViolation("OOS equity cannot be partitioned into nine strategy paths")
    equity_by_id = dict(zip(selected_ids, equity_chunks, strict=True))
    sessions = tuple(str(row["session"]) for row in equity_chunks[0])
    if len(sessions) < 8 or any(
        tuple(str(row["session"]) for row in chunk) != sessions for chunk in equity_chunks
    ):
        raise ArtifactViolation("strategy equity paths are not aligned")

    trade_wrappers = _read_jsonl(oos_path / "trades.jsonl")
    trades_by_id: dict[str, list[dict[str, object]]] = {}
    cursor = 0
    for identity in selected_ids:
        count = int(metric_by_id[identity]["trade_count"])
        values = [row["record"] for row in trade_wrappers[cursor : cursor + count]]
        if not all(isinstance(row, dict) for row in values):
            raise ArtifactViolation("trade rows are malformed")
        trades_by_id[identity] = values
        cursor += count
    if cursor != len(trade_wrappers):
        raise ArtifactViolation("trade rows do not reconcile to strategy metric counts")

    audit_rows: list[dict[str, object]] = []
    strategy_rows: list[dict[str, object]] = []
    for identity in selected_ids:
        metric = metric_by_id[identity]
        equity = [_decimal(row["equity"]) for row in equity_by_id[identity]]
        starting = _decimal(metric["starting_capital"])
        recomputed = _curve_metrics(equity, starting)
        trade_profit = sum((_decimal(row["gross_pnl"]) for row in trades_by_id[identity]), D0)
        checks = {
            "ending_equity": recomputed["ending_equity"] == _decimal(metric["ending_equity"]),
            "gross_profit": recomputed["gross_profit"] == _decimal(metric["gross_profit"]),
            "gross_return": recomputed["gross_return"] == _decimal(metric["gross_return"]),
            "maximum_drawdown": recomputed["maximum_drawdown"] == _decimal(metric["maximum_drawdown"]),
            "closed_trade_profit": trade_profit == _decimal(metric["gross_profit"]),
        }
        if not all(checks.values()):
            raise ArtifactViolation(f"metric reconciliation failed for {identity}")
        member = next(item for item in selection.members if item.strategy_revision_identity == identity)
        strategy_rows.append(
            {
                "strategy_revision_identity": identity,
                "strategy_name": strategy_names[identity],
                "display_name": _short_name(strategy_names[identity]),
                "membership": "MC5" if "MC5" in member.memberships else "FO4",
                "starting_equity": starting,
                "ending_equity": _decimal(metric["ending_equity"]),
                "gross_profit": _decimal(metric["gross_profit"]),
                "gross_return": _decimal(metric["gross_return"]),
                "maximum_drawdown_dollars": recomputed["maximum_drawdown_dollars"],
                "maximum_drawdown": _decimal(metric["maximum_drawdown"]),
                "profit_drawdown": None if metric["profit_drawdown"] is None else _decimal(metric["profit_drawdown"]),
                "closed_trades": int(metric["trade_count"]),
                "exposure_mean": None if metric["exposure"]["mean"] is None else _decimal(metric["exposure"]["mean"]),
                "exposure_maximum": None if metric["exposure"]["maximum"] is None else _decimal(metric["exposure"]["maximum"]),
                "turnover": None if metric["turnover"] is None else _decimal(metric["turnover"]),
                "break_even_proportional_cost": (
                    None
                    if metric["break_even_proportional_cost"] is None
                    else _decimal(metric["break_even_proportional_cost"])
                ),
            }
        )
        audit_rows.append({"strategy_revision_identity": identity, "checks": checks})

    cohort_equity_rows: list[dict[str, object]] = []
    cohort_metrics: list[dict[str, object]] = []
    leave_one_out_rows: list[dict[str, object]] = []
    for cohort_name in ("VF9", "MC5", "FO4"):
        identities = selection.cohorts[cohort_name]
        start = Decimal(100000 * len(identities))
        curve = [
            sum((_decimal(equity_by_id[identity][index]["equity"]) for identity in identities), D0)
            for index in range(len(sessions))
        ]
        curve_metrics = _curve_metrics(curve, start)
        returns = [_decimal(metric_by_id[identity]["gross_return"]) for identity in identities]
        profits = [_decimal(metric_by_id[identity]["gross_profit"]) for identity in identities]
        gains = sum((value for value in profits if value > D0), D0)
        losses = -sum((value for value in profits if value < D0), D0)
        positive = [value for value in profits if value > D0]
        sorted_positive = sorted(positive, reverse=True)
        cohort_metrics.append(
            {
                "cohort": cohort_name,
                "member_count": len(identities),
                **curve_metrics,
                "positive_revision_count": sum(value > D0 for value in profits),
                "negative_revision_count": sum(value < D0 for value in profits),
                "flat_revision_count": sum(value == D0 for value in profits),
                "median_revision_return": Decimal(str(median(returns))),
                "gross_positive_profit": gains,
                "gross_losses": losses,
                "losses_offset_share_of_gains": None if gains == D0 else losses / gains,
                "largest_share_of_gross_positive_profit": (
                    None if gains == D0 else sorted_positive[0] / gains
                ),
                "top_three_share_of_gross_positive_profit": (
                    None if gains == D0 else sum(sorted_positive[:3], D0) / gains
                ),
                "closed_trades": sum(int(metric_by_id[identity]["trade_count"]) for identity in identities),
            }
        )
        peak = curve[0]
        for session, raw_equity in zip(sessions, curve, strict=True):
            peak = max(peak, raw_equity)
            cohort_equity_rows.append(
                {
                    "session": session,
                    "cohort": cohort_name,
                    "raw_equity": raw_equity,
                    "normalized_index": raw_equity / start * D100,
                    "return": raw_equity / start - Decimal(1),
                    "drawdown": Decimal(1) - raw_equity / peak,
                    "member_count": len(identities),
                    "starting_capital": start,
                }
            )
        if len(identities) > 1:
            for omitted in identities:
                retained = tuple(identity for identity in identities if identity != omitted)
                retained_start = Decimal(100000 * len(retained))
                retained_curve = [
                    sum(
                        (_decimal(equity_by_id[identity][index]["equity"]) for identity in retained),
                        D0,
                    )
                    for index in range(len(sessions))
                ]
                leave_one_out_rows.append(
                    {
                        "cohort": cohort_name,
                        "omitted_strategy_revision_identity": omitted,
                        "omitted_strategy_name": strategy_names[omitted],
                        **_curve_metrics(retained_curve, retained_start),
                    }
                )

    overlap_rows: list[dict[str, object]] = []
    for left, right in combinations(selected_ids, 2):
        left_signals = {
            (str(row["permanent_id"]), str(row["session"]))
            for row in metric_by_id[left]["filled_trade_signals"]
        }
        right_signals = {
            (str(row["permanent_id"]), str(row["session"]))
            for row in metric_by_id[right]["filled_trade_signals"]
        }
        left_symbols = {item[0] for item in left_signals}
        right_symbols = {item[0] for item in right_signals}
        left_sessions = {item[1] for item in left_signals}
        right_sessions = {item[1] for item in right_signals}

        def jaccard(a: set[object], b: set[object]) -> Decimal:
            return D0 if not a | b else Decimal(len(a & b)) / Decimal(len(a | b))

        overlap_rows.append(
            {
                "left_strategy_revision_identity": left,
                "right_strategy_revision_identity": right,
                "symbol_jaccard": jaccard(left_symbols, right_symbols),
                "entry_session_jaccard": jaccard(left_sessions, right_sessions),
                "filled_trade_jaccard": jaccard(left_signals, right_signals),
                "shared_filled_trades": len(left_signals & right_signals),
            }
        )

    strategy_rows.sort(key=lambda row: (-row["gross_profit"], row["strategy_revision_identity"]))
    cohort_by_name = {row["cohort"]: row for row in cohort_metrics}
    vf9 = cohort_by_name["VF9"]
    mc5 = cohort_by_name["MC5"]
    report = [
        "# Swing Ranking V1 OOS Cohort Results",
        "",
        "## Technical summary",
        "",
        (
            f"The one-time OOS opening is sealed. VF9 returned {vf9['gross_return']:.4%} "
            f"on $900,000 and MC5 returned {mc5['gross_return']:.4%} on $500,000. "
            "Both cohorts proceed to forward paper unchanged because eligibility was fixed before OOS."
        ),
        "",
        "## Raw strategy books",
        "",
        "| Strategy | Group | Gross P&L | Return | Max DD | P/DD | Trades |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in strategy_rows:
        ratio = "—" if row["profit_drawdown"] is None else f"{row['profit_drawdown']:.4f}"
        report.append(
            f"| `{row['strategy_name']}` | {row['membership']} | "
            f"${row['gross_profit']:,.2f} | {row['gross_return']:.4%} | "
            f"{row['maximum_drawdown']:.4%} | {ratio} | {row['closed_trades']} |"
        )
    report.extend(
        [
            "",
            "## Cohort comparison",
            "",
            "| Cohort | Start | End | Gross P&L | Return | Max DD | P/DD | Breadth | Trades |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in cohort_metrics:
        ratio = "—" if row["profit_drawdown"] is None else f"{row['profit_drawdown']:.4f}"
        report.append(
            f"| {row['cohort']} | ${row['starting_capital']:,.0f} | ${row['ending_equity']:,.2f} | "
            f"${row['gross_profit']:,.2f} | {row['gross_return']:.4%} | {row['maximum_drawdown']:.4%} | "
            f"{ratio} | {row['positive_revision_count']}+ / {row['negative_revision_count']}- | "
            f"{row['closed_trades']} |"
        )
    report.extend(
        [
            "",
            "## Scope, definitions, and robustness",
            "",
            "Each revision is an independent $100,000 zero-cost book. Cohort raw equity is the sum of member books; normalized indexes equal-weight those same books. Drawdown and profit/drawdown are calculated directly from each cohort path. Leave-one-out and pairwise overlap files preserve concentration and dependency diagnostics.",
            "",
            "All OOS content hashes, strategy identities, record counts, equity-derived metrics, and closed-trade P&L reconcile. The accepted current roster retains survivorship, symbol-history, delisting, adjusted-vintage, and historical earnings-schedule limitations.",
            "",
            "## Next step",
            "",
            "Forward paper starts with VF9 and MC5 unchanged and without backfill. Ten- and twenty-trade views are descriptive; evidence becomes decision-ready only after every revision reaches 30 closed trades.",
            "",
        ]
    )

    source = {
        "oos_artifact_identity": manifest["artifact_identity"],
        "cohort_selection_identity": selection.identity,
        "evidence_start": manifest["evidence_start"],
        "evidence_end_exclusive": manifest["evidence_end_exclusive"],
        "outcome_end_exclusive": manifest["outcome_end_exclusive"],
    }
    files: dict[str, bytes] = {
        "source.json": _json(source),
        "strategy_metrics.json": _json({"rows": strategy_rows}),
        "cohort_metrics.json": _json({"rows": cohort_metrics}),
        "cohort_equity.jsonl": _jsonl(cohort_equity_rows),
        "leave_one_out.jsonl": _jsonl(leave_one_out_rows),
        "overlap.jsonl": _jsonl(overlap_rows),
        "audit.json": _json(
            {
                "status": "passed",
                "content_hash_count": len(expected_inventory),
                "strategy_metric_checks": audit_rows,
                "equity_session_count_per_strategy": len(sessions),
                "trade_count": len(trade_wrappers),
                "note": "Unlabeled concatenated trade/equity rows are partitioned by the artifact's validated strategy-SHA order and per-strategy counts.",
            }
        ),
        "report.md": ("\n".join(report)).encode("utf-8"),
        "chart_map.json": _json(
            {
                "charts": [
                    {"id": "normalized_cohort_equity", "family": "line", "dataset": "cohort_equity", "fields": ["session", "cohort", "normalized_index"]},
                    {"id": "raw_cohort_equity", "family": "line", "dataset": "cohort_equity", "fields": ["session", "cohort", "raw_equity"]},
                    {"id": "cohort_drawdown", "family": "line", "dataset": "cohort_equity", "fields": ["session", "cohort", "drawdown"]},
                    {"id": "strategy_profit", "family": "bar", "dataset": "strategy_metrics", "fields": ["display_name", "gross_profit", "membership"]},
                ]
            }
        ),
    }
    analysis_identity = identity_hash(
        "swing-ranking-v1/oos-cohort-analysis/v1",
        {"source": source, "files": {name: sha256_hex(value) for name, value in files.items()}},
    )
    content_hashes = {name: sha256_hex(value) for name, value in files.items()}
    files["manifest.json"] = _json(
        {
            "schema_version": "swing-ranking-v1.oos-cohort-analysis.v1",
            "analysis_identity": analysis_identity,
            "source": source,
            "record_counts": {
                "strategies": len(strategy_rows),
                "cohorts": len(cohort_metrics),
                "cohort_equity": len(cohort_equity_rows),
                "leave_one_out": len(leave_one_out_rows),
                "overlap_pairs": len(overlap_rows),
            },
            "content_hashes": content_hashes,
        }
    )
    return write_artifact_package(
        Path(output), ArtifactPackage(analysis_identity, files, synthetic=False)
    )


def seal_oos(
    *,
    oos_path: Path,
    analysis_path: Path,
    selection: CohortSelection,
    output: Path,
) -> ArtifactWriteResult:
    """Publish a cross-artifact cryptographic seal after all OOS analysis passes."""
    oos_manifest = _read_json(Path(oos_path) / "manifest.json")
    analysis_manifest = _read_json(Path(analysis_path) / "manifest.json")
    payload = {
        "schema_version": "swing-ranking-v1.oos-seal.v1",
        "status": "sealed",
        "sealed_on": selection.approved_on,
        "selection_identity": selection.identity,
        "oos_artifact_identity": oos_manifest["artifact_identity"],
        "cohort_analysis_identity": analysis_manifest["analysis_identity"],
        "oos_inventory": _artifact_inventory(Path(oos_path)),
        "analysis_inventory": _artifact_inventory(Path(analysis_path)),
        "forward_eligibility": selection.forward_eligibility,
        "forward_eligible_cohorts": selection.forward_eligible_cohorts,
    }
    seal_identity = identity_hash("swing-ranking-v1/oos-seal/v1", payload)
    files = {
        "seal.json": _json({"seal_identity": seal_identity, **payload}),
        "README.md": (
            "# Swing Ranking V1 OOS Seal\n\n"
            f"OOS artifact `{oos_manifest['artifact_identity']}` and cohort analysis "
            f"`{analysis_manifest['analysis_identity']}` passed reconciliation and are sealed by "
            f"`{seal_identity}`. VF9 and MC5 forward eligibility was unconditional before OOS.\n"
        ).encode(),
    }
    return write_artifact_package(
        Path(output), ArtifactPackage(seal_identity, files, synthetic=False)
    )


__all__ = ["OosCohortResult", "build_oos_cohort_analysis", "seal_oos"]
