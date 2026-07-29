from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from sts.swing_ranking.config import load_study_bundle
from sts.swing_ranking.contracts import REQUIRED_SOURCE_KINDS
from sts.swing_ranking.study_bundle import (
    OUTCOME_BUFFER_SESSIONS,
    build_strategy_grid,
    build_study_bundle,
    derive_study_dates,
)


def test_strategy_grid_is_complete_unique_and_readable() -> None:
    strategies = build_strategy_grid()
    assert len(strategies) == 4 * 3 * 4 * 3
    assert len({row["name"] for row in strategies}) == len(strategies)
    assert all(len(row["readable_rules"]) == 6 for row in strategies)


def test_study_bundle_loads_with_explicit_development_window(
    tmp_path: Path,
) -> None:
    start = dt.date(2025, 1, 2)
    end = dt.date(2026, 3, 17)
    cutoff = dt.date(2026, 4, 17)
    bundle = build_study_bundle(
        source_hashes={kind: "a" * 64 for kind in REQUIRED_SOURCE_KINDS},
        evaluation_start=start,
        evaluation_end_exclusive=end,
        data_cutoff=cutoff,
        coverage_end_exclusive=cutoff + dt.timedelta(days=1),
        roster_as_of="2026-04-20",
    )
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")

    configured = load_study_bundle(path)

    assert configured.evidence_window == "development"
    assert configured.window == configured.protocol.evaluation_split.development
    assert len(configured.strategies) == 144
    assert len(configured.protocol.candidate_grammar.definition["members"]) == 144


def test_derive_study_dates_reserves_outcome_buffer() -> None:
    cutoff = dt.date(2026, 7, 9)
    manifest = {
        "symbols": {
            "AAA": {
                "first_session": "2025-01-02",
                "last_session": cutoff.isoformat(),
            },
            "BBB": {
                "first_session": "2025-03-28",
                "last_session": cutoff.isoformat(),
            },
        }
    }

    start, end, coverage_end = derive_study_dates(
        manifest=manifest,
        data_cutoff=cutoff,
    )

    assert start == dt.date(2025, 3, 28)
    assert end == dt.date(2026, 6, 9)
    assert coverage_end == dt.date(2026, 7, 10)
    assert OUTCOME_BUFFER_SESSIONS == 21
