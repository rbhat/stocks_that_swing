#!/usr/bin/env python3
"""Freeze the post-STOP Task 5 profitability-versus-selection diagnostic."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sts.calendar import sessions_between
from sts.ml.contracts import canonical_json
from sts.ml.controls import fixed_control_scores, select_top_k
from sts.ml.development import (
    _add_score_ranks,
    _stream_random_control,
    load_development_artifacts,
    sha256_file,
)
from sts.ml.evaluation import LOCKED_FOLDS, split_fold
from sts.ml.models import fit_arm, locked_arms
from sts.ml.walls import DEVELOPMENT_END_EXCLUSIVE, DEVELOPMENT_START_INCLUSIVE

SCHEMA = "ml-task5-diagnostic-v1"
GENERATED_AT = "2026-07-28T00:00:00-07:00"
REPORT_RELATIVE = Path("runs/ml-restart/development/report.json")
INPUT_RELATIVE = Path("runs/ml-restart/development")
DATA_RELATIVE = Path("runs/ml-restart/development/task5-diagnostics.json")
ARTIFACT_RELATIVE = Path("docs/reports/ml-task5-diagnostics/artifact.json")


def _sha256_identities(frame: pd.DataFrame) -> str:
    payload = frame["row_id"].astype(str).tolist()
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def _round(value: float, digits: int = 10) -> float:
    return round(float(value), digits)


def _regime(frame: pd.DataFrame) -> pd.Series:
    return frame["spy_above_ma_200"].map(
        lambda value: (
            "missing"
            if pd.isna(value)
            else ("above_200d" if float(value) == 1.0 else "at_or_below_200d")
        )
    )


def _summarize_group(
    frame: pd.DataFrame,
    control_by_date: pd.Series,
    *,
    method: str,
    dimension: str,
    value: str,
) -> dict[str, Any]:
    by_date = frame.groupby("signal_session", sort=True)["net_r_2x"].mean()
    controls = control_by_date.reindex(by_date.index)
    if controls.isna().any():
        raise RuntimeError(f"missing same-date random control in {dimension}={value}")
    return {
        "method": method,
        "dimension": dimension,
        "value": str(value),
        "rows": len(frame),
        "dates": int(frame["signal_session"].nunique()),
        "symbols": int(frame["symbol"].nunique()),
        "net_r_2x_mean": _round(frame["net_r_2x"].mean()),
        "raw_h15_mean": _round(frame["raw_h15_return"].mean()),
        "incremental_vs_random_mean": _round((by_date - controls).mean()),
        "net_profit_2x": _round(
            (frame["gross_profit"] - frame["friction_2x"]).sum(), 2
        ),
    }


def _slice_rows(
    frame: pd.DataFrame, control_by_date: pd.Series, method: str
) -> list[dict[str, Any]]:
    rows = []
    years = pd.to_datetime(frame["signal_session"]).dt.year.astype(str)
    for value in sorted(years.unique()):
        rows.append(
            _summarize_group(
                frame.loc[years == value],
                control_by_date,
                method=method,
                dimension="year",
                value=value,
            )
        )
    regimes = _regime(frame)
    for value in sorted(regimes.unique()):
        rows.append(
            _summarize_group(
                frame.loc[regimes == value],
                control_by_date,
                method=method,
                dimension="spy_regime",
                value=value,
            )
        )
    return rows


def _symbol_rows(frame: pd.DataFrame, method: str) -> list[dict[str, Any]]:
    grouped = (
        frame.assign(year=pd.to_datetime(frame["signal_session"]).dt.year)
        .groupby("symbol", sort=True)
        .agg(
            rows=("row_id", "size"),
            dates=("signal_session", "nunique"),
            years=("year", "nunique"),
            net_r_2x_mean=("net_r_2x", "mean"),
            net_profit_2x=("gross_profit", "sum"),
            friction_2x=("friction_2x", "sum"),
        )
    )
    grouped["net_profit_2x"] -= grouped.pop("friction_2x")
    grouped = grouped.sort_values(
        ["rows", "net_profit_2x"], ascending=[False, False], kind="mergesort"
    )
    total = len(frame)
    return [
        {
            "method": method,
            "symbol": str(symbol),
            "rows": int(row.rows),
            "row_share": _round(row.rows / total),
            "dates": int(row.dates),
            "years": int(row.years),
            "net_r_2x_mean": _round(row.net_r_2x_mean),
            "net_profit_2x": _round(row.net_profit_2x, 2),
        }
        for symbol, row in grouped.head(15).iterrows()
    ]


def _concentration(frame: pd.DataFrame) -> dict[str, Any]:
    counts = frame.groupby("symbol", sort=True).size().sort_values(
        ascending=False, kind="mergesort"
    )
    shares = counts / len(frame)
    return {
        "unique_symbols": len(counts),
        "largest_symbol_share": _round(shares.iloc[0]),
        "top_3_symbol_share": _round(shares.head(3).sum()),
        "top_10_symbol_share": _round(shares.head(10).sum()),
        "symbol_hhi": _round(np.square(shares).sum()),
    }


def _overlap_rows(
    model: pd.DataFrame, constant: pd.DataFrame, fold_name: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    model_sets = model.groupby("signal_session")["symbol"].agg(
        lambda values: set(map(str, values))
    )
    constant_sets = constant.groupby("signal_session")["symbol"].agg(
        lambda values: set(map(str, values))
    )
    rows = []
    for day in sorted(model_sets.index):
        count = len(model_sets.loc[day] & constant_sets.loc[day])
        rows.append(
            {
                "fold": fold_name,
                "signal_session": pd.Timestamp(day).date().isoformat(),
                "overlap_count": count,
                "overlap_share": count / 3,
            }
        )
    counts = Counter(row["overlap_count"] for row in rows)
    return rows, {
        "fold": fold_name,
        "dates": len(rows),
        "mean_overlap_count": _round(np.mean([row["overlap_count"] for row in rows])),
        "mean_overlap_share": _round(np.mean([row["overlap_share"] for row in rows])),
        "zero_overlap_dates": counts[0],
        "one_overlap_dates": counts[1],
        "two_overlap_dates": counts[2],
        "three_overlap_dates": counts[3],
    }


def _permutation_clears(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for arm in report["arms"]:
        for permutation in arm["permutation_controls"]:
            if permutation["credible_under_real_gate"]:
                rows.append(
                    {
                        "arm": arm["canonical_config_id"],
                        "replicate": int(permutation["replicate"]),
                        "incremental_mean": _round(
                            permutation["pooled_incremental"]["mean"]
                        ),
                        "lower90": _round(
                            permutation["pooled_incremental"]["lower90"]
                        ),
                        "positive_folds": sum(
                            value > 0
                            for value in permutation["fold_incremental_means"]
                        ),
                    }
                )
    return rows


def compute_diagnostic(root: Path) -> dict[str, Any]:
    report_path = root / REPORT_RELATIVE
    report = json.loads(report_path.read_text())
    if report["verdict"] != "STOP" or report["candidate_count"] != 0:
        raise RuntimeError("Task 5 report is not the locked zero-candidate STOP")
    if report["development_wall"]["end_exclusive"] != "2024-01-01":
        raise RuntimeError("Task 5 report wall changed")
    if report["development_wall"]["post_wall_rows_observed"] != 0:
        raise RuntimeError("Task 5 report observed post-wall rows")

    frames, manifest, provenance = load_development_artifacts(root / INPUT_RELATIVE)
    if any(int(shard["year"]) >= 2024 for shard in provenance["verified_shards"]):
        raise RuntimeError("post-wall shard was read")
    arm = next(
        candidate
        for candidate in locked_arms(include_m3=True)
        if candidate.canonical_id == "A-T1-M3"
    )
    report_arm = next(
        row for row in report["arms"] if row["canonical_config_id"] == arm.canonical_id
    )
    sessions = tuple(
        timestamp.date()
        for timestamp in sessions_between(
            DEVELOPMENT_START_INCLUSIVE,
            DEVELOPMENT_END_EXCLUSIVE - dt.timedelta(days=1),
        )
    )

    selected_model = []
    selected_constant = []
    all_controls = []
    fold_rows = []
    overlap_daily = []
    overlap_folds = []
    identity_checks = []
    for fold, report_fold in zip(LOCKED_FOLDS, report_arm["folds"], strict=True):
        training, validation, split = split_fold(
            frames["A"], fold, exchange_sessions=sessions
        )
        fitted = fit_arm(training, arm)
        model_scored = _add_score_ranks(validation, fitted.score(validation))
        model = select_top_k(
            model_scored, score_column="score", top_k=3, track="A"
        ).copy()
        constant_scored = _add_score_ranks(
            validation, fixed_control_scores(validation)["constant_equal"].to_numpy()
        )
        constant = select_top_k(
            constant_scored, score_column="score", top_k=3, track="A"
        ).copy()
        controls, control_evidence = _stream_random_control(
            validation,
            config_hash=arm.config_hash,
            fold=fold.name,
            track="A",
            top_k=3,
        )
        model_by_date = model.groupby("signal_session", sort=True)["net_r_2x"].mean()
        constant_by_date = constant.groupby("signal_session", sort=True)[
            "net_r_2x"
        ].mean()
        expected_control = controls.reindex(model_by_date.index)
        model_incremental = float((model_by_date - expected_control).mean())
        constant_incremental = float((constant_by_date - expected_control).mean())
        model_hash = _sha256_identities(model)
        constant_hash = _sha256_identities(constant)
        checks = {
            "fold": fold.name,
            "model_selected_hash_match": (
                model_hash == report_fold["primary"]["selected_identities_sha256"]
            ),
            "constant_selected_hash_match": (
                constant_hash
                == report_fold["fixed_baselines"]["constant_equal"][
                    "selected_identities_sha256"
                ]
            ),
            "random_control_hash_match": (
                control_evidence["sha256"]
                == report_fold["same_date_random_controls"]["top_3"]["sha256"]
            ),
            "model_incremental_match": math.isclose(
                model_incremental,
                report_fold["primary"]["incremental"]["mean"],
                abs_tol=1e-12,
            ),
            "constant_incremental_match": math.isclose(
                constant_incremental,
                report_fold["fixed_baselines"]["constant_equal"]["incremental"][
                    "mean"
                ],
                abs_tol=1e-12,
            ),
        }
        if not all(value for key, value in checks.items() if key != "fold"):
            raise RuntimeError(f"Task 5 identity/value reproduction failed: {checks}")
        identity_checks.append(checks)
        model["fold"] = fold.name
        constant["fold"] = fold.name
        selected_model.append(model)
        selected_constant.append(constant)
        control_frame = controls.rename("control").to_frame()
        control_frame.index.name = "signal_session"
        all_controls.append(control_frame.assign(fold=fold.name))
        fold_rows.append(
            {
                "fold": fold.name,
                "validation_period": (
                    f"{fold.validation_start.year}-{fold.validation_end.year - 1}"
                ),
                "dates": int(model["signal_session"].nunique()),
                "model_incremental": _round(model_incremental),
                "constant_incremental": _round(constant_incremental),
                "model_minus_constant": _round(
                    model_incremental - constant_incremental
                ),
                "model_net_r_2x": _round(model["net_r_2x"].mean()),
                "constant_net_r_2x": _round(constant["net_r_2x"].mean()),
                "purged_training_rows": int(split["purged_training_rows"]),
                "embargoed_validation_rows": int(split["embargoed_validation_rows"]),
            }
        )
        daily, summary = _overlap_rows(model, constant, fold.name)
        overlap_daily.extend(daily)
        overlap_folds.append(summary)

    model = pd.concat(selected_model, ignore_index=True)
    constant = pd.concat(selected_constant, ignore_index=True)
    controls_frame = pd.concat(all_controls).reset_index().set_index("signal_session")
    control_by_date = controls_frame["control"]
    if not control_by_date.index.is_unique:
        raise RuntimeError("fold controls have duplicate dates")

    slice_rows = [
        *_slice_rows(model, control_by_date, "M3 ranker"),
        *_slice_rows(constant, control_by_date, "Constant/equal"),
    ]
    year_rows = [row for row in slice_rows if row["dimension"] == "year"]
    regime_rows = [row for row in slice_rows if row["dimension"] == "spy_regime"]
    symbol_rows = [
        *_symbol_rows(model, "M3 ranker"),
        *_symbol_rows(constant, "Constant/equal"),
    ]
    permutations = _permutation_clears(report)
    m3_permutation_clears = sum(
        permutation["credible_under_real_gate"]
        for permutation in report_arm["permutation_controls"]
    )
    all_arm_rows = [
        {
            "arm": row["canonical_config_id"],
            "net_r_2x_mean": _round(row["selected"]["net_r_2x_mean"]),
            "raw_h15_mean": _round(row["selected"]["raw_h15_mean"]),
            "incremental_mean": _round(row["primary_incremental_mean"]),
            "lower90": _round(row["pooled_lower90"]),
            "credible": bool(row["credible"]),
        }
        for row in report["arms"]
    ]
    baseline_rows = [
        {
            "method": "M3 ranker",
            "incremental_vs_random_mean": _round(
                report_arm["primary_incremental_mean"]
            ),
        },
        *[
            {
                "method": name.replace("_", " ").title(),
                "incremental_vs_random_mean": _round(value),
            }
            for name, value in report_arm["baseline_incremental_means"].items()
        ],
    ]
    baseline_rows.sort(key=lambda row: row["incremental_vs_random_mean"], reverse=True)

    model_years_positive = sum(
        row["net_r_2x_mean"] > 0
        for row in year_rows
        if row["method"] == "M3 ranker"
    )
    constant_years_positive = sum(
        row["net_r_2x_mean"] > 0
        for row in year_rows
        if row["method"] == "Constant/equal"
    )
    model_year_wins = sum(
        m3["incremental_vs_random_mean"] > const["incremental_vs_random_mean"]
        for m3, const in zip(
            [row for row in year_rows if row["method"] == "M3 ranker"],
            [row for row in year_rows if row["method"] == "Constant/equal"],
            strict=True,
        )
    )
    pooled_overlap = {
        "dates": len(overlap_daily),
        "mean_overlap_count": _round(
            np.mean([row["overlap_count"] for row in overlap_daily])
        ),
        "mean_overlap_share": _round(
            np.mean([row["overlap_share"] for row in overlap_daily])
        ),
        "zero_overlap_dates": sum(
            row["overlap_count"] == 0 for row in overlap_daily
        ),
        "three_overlap_dates": sum(
            row["overlap_count"] == 3 for row in overlap_daily
        ),
    }
    diagnostic = {
        "schema": SCHEMA,
        "generated_at": GENERATED_AT,
        "scope": {
            "status": "post_hoc_descriptive_diagnostic",
            "verdict_change_authorized": False,
            "task_6_authorized": False,
            "development_start_inclusive": manifest["walls"][
                "development_start_inclusive"
            ],
            "development_end_exclusive": manifest["walls"][
                "development_end_exclusive"
            ],
            "post_wall_rows_observed": 0,
        },
        "source_hashes": {
            "task5_report_sha256": sha256_file(report_path),
            "task3_manifest_sha256": provenance["manifest_sha256"],
            "track_a_sha256": provenance["track_a_sha256"],
            "task5_complete_analysis_sha256": report["determinism"][
                "first_analysis_sha256"
            ],
        },
        "reproduction": {
            "all_checks_pass": all(
                value
                for row in identity_checks
                for key, value in row.items()
                if key != "fold"
            ),
            "fold_checks": identity_checks,
        },
        "headline": {
            "task5_verdict": report["verdict"],
            "candidate_count": report["candidate_count"],
            "real_arms_profitable_net_r_2x": sum(
                row["net_r_2x_mean"] > 0 for row in all_arm_rows
            ),
            "real_arms_total": len(all_arm_rows),
            "real_arms_positive_raw_h15": sum(
                row["raw_h15_mean"] > 0 for row in all_arm_rows
            ),
            "m3_incremental_vs_random_mean": _round(
                report_arm["primary_incremental_mean"]
            ),
            "m3_lower90": _round(report_arm["pooled_lower90"]),
            "constant_incremental_vs_random_mean": _round(
                report_arm["baseline_incremental_means"]["constant_equal"]
            ),
            "m3_minus_constant": _round(
                report_arm["primary_incremental_mean"]
                - report_arm["baseline_incremental_means"]["constant_equal"]
            ),
            "m3_positive_years": model_years_positive,
            "constant_positive_years": constant_years_positive,
            "years_total": 8,
            "m3_years_beating_constant": model_year_wins,
            "permutation_controls_clearing_real_gate": len(permutations),
            "permutation_controls_total": 260,
            "m3_permutation_controls_clearing_real_gate": m3_permutation_clears,
            "m3_permutation_controls_total": 20,
            "permutation_clear_rate": _round(len(permutations) / 260),
            "illustrative_any_false_positive_at_1pct_independent": _round(
                1 - 0.99**260
            ),
        },
        "conclusion": {
            "profitable_patterns_found": True,
            "validated_unique_ranking_edge_found": False,
            "primary_explanation": (
                "A-T1-M3 showed positive economic ranking evidence against same-date "
                "random. Its fixed-baseline failure was driven by a constant/equal "
                "implementation that deterministically selected alphabetical symbols; "
                "the global permutation STOP was driven by eight Track B controls, not "
                "by an A-T1-M3 permutation."
            ),
            "interpretation_limits": [
                "The constant/equal baseline is a deterministic alphabetical tie-break, not an investable factor.",
                "Daily 15-session labels overlap and are not a slot- or capital-constrained portfolio.",
                "Survivor-only roster and revised adjusted history can inflate development profitability.",
                "The 260-control family creates a strong any-clear STOP rule; the 92.7% figure is illustrative under independence, which is not true here.",
            ],
        },
        "baseline_comparison": baseline_rows,
        "fold_comparison": fold_rows,
        "year_comparison": year_rows,
        "regime_comparison": regime_rows,
        "concentration": {
            "M3 ranker": _concentration(model),
            "Constant/equal": _concentration(constant),
        },
        "symbol_concentration": symbol_rows,
        "selection_overlap": {
            "pooled": pooled_overlap,
            "folds": overlap_folds,
        },
        "permutation_clears": permutations,
        "all_real_arms": all_arm_rows,
    }
    return diagnostic


def build_artifact(diagnostic: dict[str, Any]) -> dict[str, Any]:
    headline = diagnostic["headline"]
    overlap = diagnostic["selection_overlap"]["pooled"]
    concentration = diagnostic["concentration"]
    source_id = "task5_diagnostic"
    cards = [
        {
            "id": "profitable_arms",
            "dataset": "headline",
            "sourceId": source_id,
            "description": "Real arms with positive mean net R at doubled friction.",
            "metrics": [
                {
                    "label": "Profitable real arms",
                    "field": "profitable_arms_label",
                    "format": "text",
                }
            ],
        },
        {
            "id": "m3_edge",
            "dataset": "headline",
            "sourceId": source_id,
            "description": "M3 selected mean minus same-date random-control mean.",
            "metrics": [
                {
                    "label": "M3 incremental",
                    "field": "m3_incremental_vs_random_mean",
                    "format": "number",
                    "signed": True,
                }
            ],
        },
        {
            "id": "constant_edge",
            "dataset": "headline",
            "sourceId": source_id,
            "description": "Alphabetical constant/equal top-3 minus random control.",
            "metrics": [
                {
                    "label": "Constant incremental",
                    "field": "constant_incremental_vs_random_mean",
                    "format": "number",
                    "signed": True,
                }
            ],
        },
        {
            "id": "permutation_clears",
            "dataset": "headline",
            "sourceId": source_id,
            "description": "Aggregated permutations clearing the real-arm economic gate.",
            "metrics": [
                {
                    "label": "Permutation clears",
                    "field": "permutation_label",
                    "format": "text",
                }
            ],
        },
    ]
    charts = [
        {
            "id": "baseline_comparison",
            "title": "Incremental mean by selection method",
            "subtitle": "Mean selected net R at doubled friction minus same-date random.",
            "type": "bar",
            "dataset": "baseline_comparison",
            "sourceId": source_id,
            "encodings": {
                "x": {"field": "method", "type": "nominal", "label": "Method"},
                "y": {
                    "field": "incremental_vs_random_mean",
                    "type": "quantitative",
                    "label": "Incremental net R",
                    "format": "number",
                },
            },
        },
        {
            "id": "year_comparison",
            "title": "Incremental mean by year and method",
            "subtitle": "Validation years 2016–2023; doubled-friction net R versus random.",
            "type": "bar",
            "dataset": "year_comparison",
            "sourceId": source_id,
            "encodings": {
                "x": {"field": "value", "type": "nominal", "label": "Year"},
                "y": {
                    "field": "incremental_vs_random_mean",
                    "type": "quantitative",
                    "label": "Incremental net R",
                    "format": "number",
                },
                "color": {"field": "method", "type": "nominal", "label": "Method"},
            },
        },
    ]
    tables = [
        {
            "id": "fold_comparison",
            "title": "Fold comparison",
            "dataset": "fold_comparison",
            "sourceId": source_id,
            "defaultSort": {"field": "fold", "direction": "asc"},
            "columns": [
                {"field": "fold", "label": "Fold", "type": "text"},
                {
                    "field": "validation_period",
                    "label": "Validation",
                    "type": "text",
                },
                {"field": "dates", "label": "Dates", "format": "number"},
                {
                    "field": "model_incremental",
                    "label": "M3 ΔR",
                    "format": "number",
                },
                {
                    "field": "constant_incremental",
                    "label": "Constant ΔR",
                    "format": "number",
                },
                {
                    "field": "model_minus_constant",
                    "label": "M3 − constant",
                    "format": "number",
                },
            ],
        },
        {
            "id": "regime_comparison",
            "title": "SPY 200-day regime comparison",
            "dataset": "regime_comparison",
            "sourceId": source_id,
            "defaultSort": {"field": "value", "direction": "asc"},
            "columns": [
                {"field": "method", "label": "Method", "type": "text"},
                {"field": "value", "label": "Regime", "type": "text"},
                {"field": "rows", "label": "Rows", "format": "number"},
                {"field": "dates", "label": "Dates", "format": "number"},
                {
                    "field": "net_r_2x_mean",
                    "label": "Net R 2x",
                    "format": "number",
                },
                {
                    "field": "incremental_vs_random_mean",
                    "label": "ΔR vs random",
                    "format": "number",
                },
            ],
        },
        {
            "id": "symbol_concentration",
            "title": "Top selected symbols",
            "dataset": "symbol_concentration",
            "sourceId": source_id,
            "defaultSort": {"field": "rows", "direction": "desc"},
            "columns": [
                {"field": "method", "label": "Method", "type": "text"},
                {"field": "symbol", "label": "Symbol", "type": "text"},
                {"field": "rows", "label": "Rows", "format": "number"},
                {"field": "row_share", "label": "Share", "format": "percent"},
                {"field": "years", "label": "Years", "format": "number"},
                {
                    "field": "net_r_2x_mean",
                    "label": "Net R 2x",
                    "format": "number",
                },
                {
                    "field": "net_profit_2x",
                    "label": "Net profit 2x",
                    "format": "currency",
                },
            ],
        },
        {
            "id": "permutation_table",
            "title": "Permutation controls clearing the real-arm gate",
            "dataset": "permutation_clears",
            "sourceId": source_id,
            "defaultSort": {"field": "lower90", "direction": "desc"},
            "columns": [
                {"field": "arm", "label": "Arm", "type": "text"},
                {"field": "replicate", "label": "Replicate", "format": "number"},
                {
                    "field": "incremental_mean",
                    "label": "Incremental mean",
                    "format": "number",
                },
                {"field": "lower90", "label": "Lower 90%", "format": "number"},
                {
                    "field": "positive_folds",
                    "label": "Positive folds",
                    "format": "number",
                },
            ],
        },
    ]
    title = "ML Task 5 Diagnostic: Profitability vs Selection Edge"
    blocks = [
        {"id": "title", "type": "markdown", "body": f"# {title}"},
        {
            "id": "summary",
            "type": "markdown",
            "sourceId": source_id,
            "body": (
                "## Technical summary\n\n"
                f"- Profitability was present: **{headline['real_arms_profitable_net_r_2x']}/"
                f"{headline['real_arms_total']}** real arms had positive mean net R at "
                "doubled friction.\n"
                f"- M3 added **{headline['m3_incremental_vs_random_mean']:+.4f}R** "
                "versus same-date random, but constant/equal added "
                f"**{headline['constant_incremental_vs_random_mean']:+.4f}R**; M3 "
                f"trailed it by **{headline['m3_minus_constant']:+.4f}R**.\n"
                f"- **{headline['permutation_controls_clearing_real_gate']}/"
                f"{headline['permutation_controls_total']}** aggregated permutations "
                "cleared the real-arm economic gate. Result: profitable opportunity "
                "set, no validated unique ranking edge; Task 5 remains STOP."
            ),
        },
        {
            "id": "metrics",
            "type": "metric-strip",
            "cardIds": [
                "profitable_arms",
                "m3_edge",
                "constant_edge",
                "permutation_clears",
            ],
        },
        {
            "id": "findings",
            "type": "markdown",
            "sourceId": source_id,
            "body": (
                "## Key findings\n\n"
                f"- M3 was profitable in **{headline['m3_positive_years']}/8** validation "
                f"years and beat constant/equal in only **{headline['m3_years_beating_constant']}/8**.\n"
                f"- M3 and constant/equal shared **{overlap['mean_overlap_share']:.1%}** "
                f"of selections per date; zero overlap occurred on "
                f"**{overlap['zero_overlap_dates']:,}/{overlap['dates']:,}** dates.\n"
                f"- M3 top-10 symbol share was "
                f"**{concentration['M3 ranker']['top_10_symbol_share']:.1%}** versus "
                f"**{concentration['Constant/equal']['top_10_symbol_share']:.1%}** for "
                "constant/equal; this exposes the tie-break artifact.\n"
                "- Constant/equal is the alphabetical tie-break under equal scores. Its "
                f"top three symbols supplied **{concentration['Constant/equal']['top_3_symbol_share']:.1%}** "
                "of rows; its performance is a roster/cohort artifact, not an equal-weight baseline."
            ),
        },
        {"id": "baseline_chart", "type": "chart", "chartId": "baseline_comparison"},
        {"id": "year_chart", "type": "chart", "chartId": "year_comparison"},
        {"id": "fold_table", "type": "table", "tableId": "fold_comparison"},
        {"id": "regime_table", "type": "table", "tableId": "regime_comparison"},
        {"id": "symbol_table", "type": "table", "tableId": "symbol_concentration"},
        {
            "id": "methodology",
            "type": "markdown",
            "sourceId": source_id,
            "body": (
                "## Scope, data, and methodology\n\n"
                "Exact A-T1-M3 and constant/equal top-3 selections were reconstructed "
                "for the four locked walk-forward folds from the hash-verified 2011–2023 "
                "Track A shards. Each fold retained the locked 15-session purge/embargo, "
                "doubled friction, and 100-replicate same-date random control. Model, "
                "baseline, and control hashes match Task 5. No 2024+ row was read."
            ),
        },
        {"id": "permutation", "type": "table", "tableId": "permutation_table"},
        {
            "id": "limitations",
            "type": "markdown",
            "sourceId": source_id,
            "body": (
                "## Limitations and robustness\n\n"
                "- The 15-session outcomes are overlapping event labels, not a "
                "slot- or capital-constrained 2–3-week portfolio backtest.\n"
                "- The roster is survivor-only; adjusted history may include later "
                "source revisions. Absolute profit is development evidence only.\n"
                f"- With 260 controls, an independent 1% false-positive rate implies "
                f"**{headline['illustrative_any_false_positive_at_1pct_independent']:.1%}** "
                "chance of at least one clear. The controls are dependent, so this is "
                "diagnostic context, not a retroactive threshold change.\n"
                f"- A-T1-M3 had **{headline['m3_permutation_controls_clearing_real_gate']}/"
                f"{headline['m3_permutation_controls_total']}** local permutation clears; "
                "all eight family-level clears were Track B arms.\n"
                "- This post-hoc report cannot create candidates, amend STOP, or authorize Task 6."
            ),
        },
        {
            "id": "next_steps",
            "type": "markdown",
            "body": (
                "## Next steps\n\n"
                "None authorized. Preserve Task 5 STOP. Any redesigned multiplicity rule, "
                "point-in-time universe, or slot-constrained portfolio test requires a new "
                "preregistered task."
            ),
        },
    ]
    headline_dataset = {
        **headline,
        "profitable_arms_label": (
            f"{headline['real_arms_profitable_net_r_2x']}/"
            f"{headline['real_arms_total']}"
        ),
        "permutation_label": (
            f"{headline['permutation_controls_clearing_real_gate']}/"
            f"{headline['permutation_controls_total']}"
        ),
    }
    source = {
        "id": source_id,
        "label": "Locked Task 5 report plus exact pre-2024 selection reconstruction",
        "path": str(DATA_RELATIVE),
        "query": {
            "description": "Load the canonical diagnostic record used by every report block.",
            "engine": "duckdb",
            "language": "sql",
            "sql": (
                "SELECT * FROM read_json_auto("
                "'runs/ml-restart/development/task5-diagnostics.json'"
                ");"
            ),
            "tables_used": [str(DATA_RELATIVE)],
            "filters": [
                "development_end_exclusive = 2024-01-01",
                "post_wall_rows_observed = 0",
            ],
            "metric_definitions": [
                "net_r_2x_mean = mean net R after doubled locked friction",
                "incremental_vs_random_mean = selected top-3 mean net R minus the mean of 100 deterministic same-date random top-3 draws",
                "net_profit_2x = sum(gross_profit - friction_2x); event simulations, not portfolio P&L",
            ],
        },
    }
    # The compact metric strip duplicates the sourced technical summary.
    cards = []
    blocks = [block for block in blocks if block["type"] != "metric-strip"]
    return {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": title,
            "description": "Post-STOP diagnostic of absolute profitability and ranking credibility.",
            "generatedAt": GENERATED_AT,
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "sources": [
                {
                    "id": source_id,
                    "label": source["label"],
                    "path": source["path"],
                }
            ],
            "blocks": blocks,
        },
        "snapshot": {
            "version": 1,
            "generatedAt": GENERATED_AT,
            "status": "ready",
            "datasets": {
                "headline": [headline_dataset],
                "baseline_comparison": diagnostic["baseline_comparison"],
                "year_comparison": diagnostic["year_comparison"],
                "fold_comparison": diagnostic["fold_comparison"],
                "regime_comparison": diagnostic["regime_comparison"],
                "symbol_concentration": diagnostic["symbol_concentration"],
                "permutation_clears": diagnostic["permutation_clears"],
            },
        },
        "sources": [source],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--artifact-only",
        action="store_true",
        help="Rebuild the presentation from an already verified diagnostic JSON.",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    diagnostic = (
        json.loads((root / DATA_RELATIVE).read_text())
        if args.artifact_only
        else compute_diagnostic(root)
    )
    artifact = build_artifact(diagnostic)
    data_path = root / DATA_RELATIVE
    artifact_path = root / ARTIFACT_RELATIVE
    data_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    if not args.artifact_only:
        data_path.write_text(json.dumps(diagnostic, indent=2, sort_keys=True) + "\n")
    artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    if not args.artifact_only:
        print(f"wrote {data_path.relative_to(root)}")
    print(f"wrote {artifact_path.relative_to(root)}")


if __name__ == "__main__":
    main()
