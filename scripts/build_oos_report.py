"""Build the canonical portable HTML report input from sealed OOS cohort data."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _number(value: object) -> float | int | None:
    if value is None or isinstance(value, (float, int)):
        return value
    return float(Decimal(str(value)))


def _numeric_rows(rows: list[dict[str, object]], numeric: set[str]) -> list[dict[str, object]]:
    return [
        {key: _number(value) if key in numeric else value for key, value in row.items()}
        for row in rows
    ]


def build_artifact(analysis_dir: Path, seal_dir: Path) -> dict[str, object]:
    cohort_rows = _numeric_rows(
        _read_json(analysis_dir / "cohort_metrics.json")["rows"],
        {
            "starting_capital",
            "ending_equity",
            "gross_profit",
            "gross_return",
            "maximum_drawdown_dollars",
            "maximum_drawdown",
            "profit_drawdown",
            "median_revision_return",
            "gross_positive_profit",
            "gross_losses",
            "losses_offset_share_of_gains",
            "largest_share_of_gross_positive_profit",
            "top_three_share_of_gross_positive_profit",
        },
    )
    strategy_rows = _numeric_rows(
        _read_json(analysis_dir / "strategy_metrics.json")["rows"],
        {
            "starting_equity",
            "ending_equity",
            "gross_profit",
            "gross_return",
            "maximum_drawdown_dollars",
            "maximum_drawdown",
            "profit_drawdown",
            "exposure_mean",
            "exposure_maximum",
            "turnover",
            "break_even_proportional_cost",
        },
    )
    equity_rows = _numeric_rows(
        [row for row in _read_jsonl(analysis_dir / "cohort_equity.jsonl")],
        {
            "raw_equity",
            "normalized_index",
            "return",
            "drawdown",
            "starting_capital",
        },
    )
    leave_one_out = _numeric_rows(
        _read_jsonl(analysis_dir / "leave_one_out.jsonl"),
        {
            "starting_capital",
            "ending_equity",
            "gross_profit",
            "gross_return",
            "maximum_drawdown_dollars",
            "maximum_drawdown",
            "profit_drawdown",
        },
    )
    overlap = _numeric_rows(
        _read_jsonl(analysis_dir / "overlap.jsonl"),
        {"symbol_jaccard", "entry_session_jaccard", "filled_trade_jaccard"},
    )
    seal = _read_json(seal_dir / "seal.json")
    by_cohort = {str(row["cohort"]): row for row in cohort_rows}
    vf9, mc5, fo4 = (by_cohort[name] for name in ("VF9", "MC5", "FO4"))
    source_id = "cohort_equity_file"
    source_specs = {
        "cohort_equity_file": (
            "Cohort equity paths",
            "runs/swing-ranking-v1/oos-cohort-comparison-v1/cohort_equity.jsonl",
            "SELECT * FROM read_json_auto('runs/swing-ranking-v1/oos-cohort-comparison-v1/cohort_equity.jsonl', format='newline_delimited')",
        ),
        "cohort_metrics_file": (
            "Exact cohort metrics",
            "runs/swing-ranking-v1/oos-cohort-comparison-v1/cohort_metrics.json",
            "SELECT row.* FROM read_json_auto('runs/swing-ranking-v1/oos-cohort-comparison-v1/cohort_metrics.json') AS source, UNNEST(source.rows) AS t(row)",
        ),
        "strategy_metrics_file": (
            "Exact strategy metrics",
            "runs/swing-ranking-v1/oos-cohort-comparison-v1/strategy_metrics.json",
            "SELECT row.* FROM read_json_auto('runs/swing-ranking-v1/oos-cohort-comparison-v1/strategy_metrics.json') AS source, UNNEST(source.rows) AS t(row)",
        ),
        "leave_one_out_file": (
            "Leave-one-out cohort paths",
            "runs/swing-ranking-v1/oos-cohort-comparison-v1/leave_one_out.jsonl",
            "SELECT * FROM read_json_auto('runs/swing-ranking-v1/oos-cohort-comparison-v1/leave_one_out.jsonl', format='newline_delimited')",
        ),
        "overlap_file": (
            "Pairwise overlap diagnostics",
            "runs/swing-ranking-v1/oos-cohort-comparison-v1/overlap.jsonl",
            "SELECT * FROM read_json_auto('runs/swing-ranking-v1/oos-cohort-comparison-v1/overlap.jsonl', format='newline_delimited')",
        ),
    }
    sources = [
        {
            "id": identifier,
            "label": label,
            "path": path,
            "query": {
                "engine": "duckdb",
                "language": "sql",
                "sql": sql,
                "description": "Read the sealed, deterministic cohort-analysis file used by this report surface.",
                "tables_used": [path],
                "filters": {"costs": "None assumed or deducted"},
            },
        }
        for identifier, (label, path, sql) in source_specs.items()
    ]
    charts = [
        {
            "id": "normalized_equity",
            "title": "Normalized cohort equity",
            "subtitle": "Equal-weight $100 starting indexes across the complete OOS path",
            "type": "line",
            "intent": "trend",
            "question": "How did VF9, MC5, and FO4 evolve on a comparable capital base?",
            "rationale": "A multi-series line chart preserves the full path and compares normalized cohorts fairly.",
            "dataset": "cohort_equity",
            "sourceId": source_id,
            "palette": {"kind": "identity", "name": "vf9-blue-mc5-orange-fo4-neutral"},
            "legend": {"position": "bottom", "interactive": True, "sort": "spec"},
            "labels": {"values": "endpoints"},
            "encodings": {
                "x": {"field": "session", "type": "temporal", "label": "Session"},
                "y": {"field": "normalized_index", "type": "quantitative", "label": "Index", "format": "number"},
                "color": {"field": "cohort", "type": "nominal", "label": "Cohort"},
            },
        },
        {
            "id": "vf9_raw_equity",
            "title": "VF9 raw cohort equity",
            "subtitle": "$900,000 starting capital; shown separately from MC5",
            "type": "line",
            "intent": "trend",
            "question": "How did VF9's actual dollar equity move through OOS?",
            "rationale": "A single-series line preserves VF9's path without overlaying an incompatible capital base.",
            "dataset": "vf9_equity",
            "sourceId": source_id,
            "palette": {"kind": "identity", "name": "vf9-blue"},
            "labels": {"values": "endpoints"},
            "encodings": {
                "x": {"field": "session", "type": "temporal", "label": "Session"},
                "y": {"field": "raw_equity", "type": "quantitative", "label": "Equity", "format": "currency"},
            },
        },
        {
            "id": "mc5_raw_equity",
            "title": "MC5 raw cohort equity",
            "subtitle": "$500,000 starting capital; shown separately from VF9",
            "type": "line",
            "intent": "trend",
            "question": "How did MC5's actual dollar equity move through OOS?",
            "rationale": "A single-series line preserves MC5's path without overlaying an incompatible capital base.",
            "dataset": "mc5_equity",
            "sourceId": source_id,
            "palette": {"kind": "identity", "name": "mc5-orange"},
            "labels": {"values": "endpoints"},
            "encodings": {
                "x": {"field": "session", "type": "temporal", "label": "Session"},
                "y": {"field": "raw_equity", "type": "quantitative", "label": "Equity", "format": "currency"},
            },
        },
        {
            "id": "cohort_drawdown",
            "title": "Cohort drawdown",
            "subtitle": "Peak-to-trough drawdown on each directly aggregated cohort path",
            "type": "line",
            "intent": "trend",
            "question": "When and how deeply did each cohort draw down?",
            "rationale": "Aligned drawdown series show path-dependent risk without attempting an invalid decomposition.",
            "dataset": "cohort_equity",
            "sourceId": source_id,
            "palette": {"kind": "identity", "name": "vf9-blue-mc5-orange-fo4-neutral"},
            "legend": {"position": "bottom", "interactive": True, "sort": "spec"},
            "encodings": {
                "x": {"field": "session", "type": "temporal", "label": "Session"},
                "y": {"field": "drawdown", "type": "quantitative", "label": "Drawdown", "format": "percent"},
                "color": {"field": "cohort", "type": "nominal", "label": "Cohort"},
            },
        },
        {
            "id": "strategy_profit",
            "title": "Configuration gross P&L",
            "subtitle": "All nine independent $100,000 books, sorted by gross dollar result",
            "type": "horizontalBar",
            "intent": "comparison",
            "question": "Which revisions contributed gains and losses to the cohort totals?",
            "rationale": "Sorted horizontal bars fit the long revision labels and preserve signed magnitude around zero.",
            "dataset": "strategy_metrics",
            "sourceId": "strategy_metrics_file",
            "palette": {"kind": "diverging", "name": "signed-blue-orange"},
            "labels": {"values": "all"},
            "referenceLines": [{"axis": "y", "value": 0, "color": "neutral", "lineStyle": "solid", "label": "Zero"}],
            "encodings": {
                "x": {"field": "display_name", "type": "ordinal", "label": "Revision"},
                "y": {"field": "gross_profit", "type": "quantitative", "label": "Gross P&L", "format": "currency"},
            },
        },
    ]
    tables = [
        {
            "id": "cohort_detail",
            "title": "Exact cohort metrics",
            "subtitle": "Raw capital bases and path-derived metrics for VF9, MC5, and FO4",
            "dataset": "cohort_metrics",
            "sourceId": "cohort_metrics_file",
            "defaultSort": {"field": "member_count", "direction": "desc"},
            "columns": [
                {"field": "cohort", "label": "Cohort", "type": "text"},
                {"field": "member_count", "label": "Books", "format": "number"},
                {"field": "starting_capital", "label": "Start", "format": "currency"},
                {"field": "ending_equity", "label": "End", "format": "currency"},
                {"field": "gross_profit", "label": "Gross P&L", "format": "currency", "movement": True},
                {"field": "gross_return", "label": "Return", "format": "percent", "movement": True},
                {"field": "maximum_drawdown", "label": "Max DD", "format": "percent"},
                {"field": "profit_drawdown", "label": "P/DD", "format": "number", "movement": True},
                {"field": "positive_revision_count", "label": "Positive", "format": "number"},
                {"field": "negative_revision_count", "label": "Negative", "format": "number"},
                {"field": "closed_trades", "label": "Trades", "format": "number"},
            ],
        },
        {
            "id": "strategy_detail",
            "title": "Exact strategy metrics",
            "subtitle": "Every approved revision; no result is omitted or filtered",
            "dataset": "strategy_metrics",
            "sourceId": "strategy_metrics_file",
            "defaultSort": {"field": "gross_profit", "direction": "desc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "strategy_name", "label": "Revision", "type": "text"},
                {"field": "membership", "label": "Group", "type": "text"},
                {"field": "ending_equity", "label": "End equity", "format": "currency"},
                {"field": "gross_profit", "label": "Gross P&L", "format": "currency", "movement": True},
                {"field": "gross_return", "label": "Return", "format": "percent", "movement": True},
                {"field": "maximum_drawdown_dollars", "label": "Max DD $", "format": "currency"},
                {"field": "maximum_drawdown", "label": "Max DD %", "format": "percent"},
                {"field": "profit_drawdown", "label": "P/DD", "format": "number", "movement": True},
                {"field": "closed_trades", "label": "Trades", "format": "number"},
                {"field": "exposure_mean", "label": "Mean exposure", "format": "percent"},
                {"field": "turnover", "label": "Turnover", "format": "number"},
                {"field": "break_even_proportional_cost", "label": "Break-even cost", "format": "percent"},
            ],
        },
        {
            "id": "leave_one_out",
            "title": "Leave-one-out cohort sensitivity",
            "subtitle": "Path metrics after removing each member from VF9, MC5, or FO4",
            "dataset": "leave_one_out",
            "sourceId": "leave_one_out_file",
            "defaultSort": {"field": "cohort", "direction": "asc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "cohort", "label": "Cohort", "type": "text"},
                {"field": "omitted_strategy_name", "label": "Omitted revision", "type": "text"},
                {"field": "gross_return", "label": "Return", "format": "percent", "movement": True},
                {"field": "maximum_drawdown", "label": "Max DD", "format": "percent"},
                {"field": "profit_drawdown", "label": "P/DD", "format": "number", "movement": True},
            ],
        },
        {
            "id": "overlap",
            "title": "Pairwise filled-trade overlap",
            "subtitle": "All 36 strategy pairs; Jaccard overlap by symbol, entry session, and exact filled trade",
            "dataset": "overlap",
            "sourceId": "overlap_file",
            "defaultSort": {"field": "filled_trade_jaccard", "direction": "desc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "left_strategy_revision_identity", "label": "Left SHA", "type": "text"},
                {"field": "right_strategy_revision_identity", "label": "Right SHA", "type": "text"},
                {"field": "symbol_jaccard", "label": "Symbol overlap", "format": "percent"},
                {"field": "entry_session_jaccard", "label": "Time overlap", "format": "percent"},
                {"field": "filled_trade_jaccard", "label": "Filled-trade overlap", "format": "percent"},
                {"field": "shared_filled_trades", "label": "Shared fills", "format": "number"},
            ],
        },
    ]
    return {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": "Swing Ranking V1 OOS Cohort Results",
            "description": "Sealed one-time OOS comparison of VF9, MC5, and diagnostic FO4.",
            "generatedAt": "2026-07-31T23:59:59-07:00",
            "cards": [],
            "charts": charts,
            "tables": tables,
            "sources": [
                {"id": source["id"], "label": source["label"], "path": source["path"]}
                for source in sources
            ],
            "blocks": [
                {"id": "title", "type": "markdown", "body": "# Swing Ranking V1 OOS Cohort Results"},
                {
                    "id": "technical_summary",
                    "type": "markdown",
                    "body": (
                        "## Technical summary\n\n"
                        f"The one-time OOS opening is sealed by `{seal['seal_identity']}`. "
                        f"VF9 returned **{vf9['gross_return']:.2%}** on a $900k base; MC5 returned "
                        f"**{mc5['gross_return']:.2%}** on a $500k base; diagnostic FO4 returned "
                        f"**{fo4['gross_return']:.2%}**. Only two of nine books were positive. "
                        "Both VF9 and MC5 proceed to forward paper unchanged because their eligibility was fixed before OOS."
                    ),
                },
                {
                    "id": "normalized_finding",
                    "type": "markdown",
                    "body": (
                        "## FO4 reduced the full frontier's loss\n\n"
                        "The fair normalized comparison shows MC5 trailing VF9. FO4 lost less than MC5, "
                        "so adding the four frontier-only books improved VF9's aggregate return; this is descriptive OOS evidence, not a promotion rule."
                    ),
                },
                {"id": "normalized_chart", "type": "chart", "chartId": "normalized_equity"},
                {
                    "id": "raw_equity_finding",
                    "type": "markdown",
                    "body": "## Raw dollar books stay on their true capital bases\n\nVF9 and MC5 are shown in separate aligned panels because $900k and $500k totals are not directly comparable. Exact start, end, and gross P&L values follow in the cohort table.",
                },
                {"id": "vf9_raw_chart", "type": "chart", "chartId": "vf9_raw_equity"},
                {"id": "mc5_raw_chart", "type": "chart", "chartId": "mc5_raw_equity"},
                {
                    "id": "drawdown_finding",
                    "type": "markdown",
                    "body": "## Drawdown was path-dependent and material in every cohort\n\nCohort drawdown is calculated directly from each summed equity curve. It is not inferred from member averages and cannot be decomposed with the VF9 attribution formula.",
                },
                {"id": "drawdown_chart", "type": "chart", "chartId": "cohort_drawdown"},
                {"id": "cohort_table", "type": "table", "tableId": "cohort_detail", "layout": "full"},
                {
                    "id": "contribution_finding",
                    "type": "markdown",
                    "body": "## Seven losses outweighed two profitable books\n\nThe contribution view exposes dispersion that a cohort average would hide. The largest positive book supplied most gross gains, while losses more than offset all positive P&L.",
                },
                {"id": "strategy_profit_chart", "type": "chart", "chartId": "strategy_profit"},
                {"id": "strategy_table", "type": "table", "tableId": "strategy_detail", "layout": "full"},
                {
                    "id": "scope",
                    "type": "markdown",
                    "body": "## Scope, data, and metric definitions\n\nEach revision is an independent zero-cost $100,000 book. VF9 contains all nine validation-frontier revisions; MC5 contains the five revisions present in at least two validation top-five lists; FO4 is the four-member complement used only for diagnosis. Normalized indexes equal-weight the same independent books. OOS entries span March 13 through June 8, 2026; all outcomes close by June 8 in this artifact.",
                },
                {
                    "id": "method",
                    "type": "markdown",
                    "body": "## Methodology and sealing\n\nThe engine reused the frozen protocol, causal candidates, geometry, zero-cost simulator, and charter. The selection bound exact strategy SHA-256 identities and unconditional VF9/MC5 forward eligibility before OOS. The audit rehashed every source artifact, reconciled strategy identities and record counts, and independently recomputed ending equity, gross profit, return, drawdown, and closed-trade P&L before publishing the cross-artifact seal.",
                },
                {
                    "id": "robustness",
                    "type": "markdown",
                    "sourceId": "overlap_file",
                    "body": "## Concentration and overlap remain visible\n\nLeave-one-out paths quantify dependence on every member. All 36 pairwise comparisons report symbol, entry-session, and exact filled-trade overlap; these diagnostics describe concentration but do not remove or promote any revision.",
                },
                {"id": "leave_one_out_table", "type": "table", "tableId": "leave_one_out", "layout": "full"},
                {"id": "overlap_table", "type": "table", "tableId": "overlap", "layout": "full"},
                {
                    "id": "limitations",
                    "type": "markdown",
                    "body": "## Limitations and uncertainty\n\nThe current-roster cache retains survivorship, symbol-history, delisting, adjustment-vintage, and historical earnings-schedule limitations. OOS is a single historical window and does not establish causality or stable future performance. Forward evidence is the arbiter, and no OOS result can change membership, weights, parameters, or execution rules.",
                },
                {
                    "id": "next_steps",
                    "type": "markdown",
                    "body": "## Forward test now starts unchanged\n\nInitialize VF9 and MC5 without backfill, retain all nine $100,000 virtual books, and preserve the same cohort aggregation and metrics. Ten- and twenty-trade checkpoints are descriptive; evidence becomes decision-ready only after every revision reaches 30 closed trades.",
                },
                {
                    "id": "questions",
                    "type": "markdown",
                    "body": "## Further questions\n\nForward monitoring should ask whether return breadth improves, whether contribution concentration persists, and whether filled-trade overlap remains similar. These are monitoring questions only; they do not create a post-OOS cohort or performance kill rule.",
                },
            ],
        },
        "snapshot": {
            "version": 1,
            "generatedAt": "2026-07-31T23:59:59-07:00",
            "status": "ready",
            "datasets": {
                "vf9_summary": [vf9],
                "mc5_summary": [mc5],
                "cohort_metrics": cohort_rows,
                "cohort_equity": equity_rows,
                "vf9_equity": [row for row in equity_rows if row["cohort"] == "VF9"],
                "mc5_equity": [row for row in equity_rows if row["cohort"] == "MC5"],
                "strategy_metrics": strategy_rows,
                "leave_one_out": leave_one_out,
                "overlap": overlap,
            },
        },
        "sources": sources,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", required=True)
    parser.add_argument("--seal", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    artifact = build_artifact(Path(args.analysis), Path(args.seal))
    output.write_text(
        json.dumps(artifact, allow_nan=False, separators=(",", ":"), sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(output, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
