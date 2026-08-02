from __future__ import annotations

import json
from pathlib import Path

import pytest

from sts.swing_ranking.dashboard import data
from sts.swing_ranking.dashboard.legacy import LegacyRoots
from sts.swing_ranking.dashboard.legacy import admin as legacy_admin
from sts.swing_ranking.identity import sha256_hex

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from sts.swing_ranking.dashboard.app import create_app
from sts.swing_ranking.dashboard.auth import SESSION_COOKIE, make_session

SECRET = "test-secret"

CHARTER = {
    "run_id": data.FORWARD_RUN_ID,
    "charter_identity": "c" * 64,
    "selection_identity": "s" * 64,
    "no_backfill": True,
    "paper_only": True,
    "first_eligible_signal_session": "2026-08-03",
    "forward_eligible_cohorts": ["VF9", "MC5"],
    "evidence_thresholds": {
        "decision_ready_closed_trades_per_revision": 30,
        "interim_closed_trades_per_revision": [10, 20],
    },
    "aggregation": {
        "strategy_book_starting_capital": "100000",
        "VF9_raw_starting_capital": "200000",
        "MC5_raw_starting_capital": "100000",
        "FO4_raw_starting_capital": "100000",
    },
    "cohorts": {"VF9": ["a" * 64, "b" * 64], "MC5": ["a" * 64], "FO4": ["b" * 64]},
}

STATE = {
    "run_id": data.FORWARD_RUN_ID,
    "status": "active",
    "as_of": "2026-08-04",
    "last_processed_session": "2026-08-04",
    "next_eligible_signal_session": "2026-08-05",
    "no_backfill": True,
    "decision_readiness": "not_ready",
    "cohort_status": {"VF9": "descriptive_10", "MC5": "pre_10", "FO4": "diagnostic_pre_10"},
    "books": [
        {
            "strategy_revision_identity": "a" * 64,
            "strategy_name": "monthly-ema6-below__close-cross-sma10__atr14x1p5__target-risk2p5",
            "memberships": ["VF9", "MC5"],
            "status": "active",
            "starting_equity": "100000",
            "current_equity": "101000",
            "closed_trades": 12,
            "open_positions": 1,
            "maximum_drawdown": "0.01",
            "execution": {"positions": [{"symbol": "CVS", "quantity": "10"}]},
        },
        {
            "strategy_revision_identity": "b" * 64,
            "strategy_name": "weekly-ema13-below__close-cross-ema5__atr14x1__target-risk1p75",
            "memberships": ["VF9", "FO4"],
            "status": "active",
            "starting_equity": "100000",
            "current_equity": "99000",
            "closed_trades": 4,
            "open_positions": 0,
            "maximum_drawdown": "0.02",
        },
    ],
}


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _manifest_for(root: Path, names: list[str], **extra: object) -> None:
    hashes = {name: sha256_hex((root / name).read_bytes()) for name in names}
    _write(root / "manifest.json", {"content_hashes": hashes, **extra})


def _forward_run(runs_root: Path) -> Path:
    root = runs_root / data.FORWARD_RUN_ID
    _write(root / "charter.json", CHARTER)
    _write(root / "state.json", STATE)
    for name in ("candidates", "orders", "trades", "equity", "events"):
        (root / f"{name}.jsonl").write_text("", encoding="utf-8")
    (root / "equity.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "strategy_revision_identity": identity,
                    "identity": f"{identity}-{session}",
                    "record": {"session": session, "equity": equity},
                }
            )
            for identity, session, equity in [
                ("a" * 64, "2026-08-03", "100500"),
                ("a" * 64, "2026-08-04", "101000"),
                ("b" * 64, "2026-08-03", "99500"),
                ("b" * 64, "2026-08-04", "99000"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "trades.jsonl").write_text(
        json.dumps(
            {
                "strategy_revision_identity": "a" * 64,
                "identity": "t1",
                "record": {
                    "symbol": "CVS",
                    "entry_session": "2026-08-03",
                    "exit_session": "2026-08-04",
                    "gross_pnl": "500",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _manifest_for(
        root,
        ["charter.json", "state.json", "equity.jsonl", "trades.jsonl"],
        forward_identity="f" * 64,
    )
    return root


def _backtest_window(runs_root: Path, window: str) -> Path:
    root = runs_root / data.BACKTEST_ROOT_NAME / window
    _write(
        root / "ranking.json",
        {
            "artifact_identity": "r" * 64,
            "record": {
                axis: [
                    {
                        "strategy_revision_identity": "a" * 64,
                        "metrics": {
                            "gross_profit": "1234.5",
                            "maximum_drawdown": "0.04",
                            "profit_drawdown": "3.1",
                            "profit_drawdown_status": "defined",
                            "trade_count": 42,
                            # Dropped on read: megabytes per revision, unused.
                            "candidate_signals": [{"permanent_id": "X", "session": "2026-01-01"}],
                            "filled_trade_signals": [{"permanent_id": "X"}],
                        },
                    }
                ]
                for axis in data.RANKING_AXES
            },
        },
    )
    _write(
        root / "strategy_names.json",
        {"strategies": {"a" * 64: "monthly-ema6-below__close-cross-sma10__atr14x1p5__target-risk2p5"}},
    )
    (root / "report.md").write_text("# report\n", encoding="utf-8")
    _write(
        root / "protocol.json",
        {
            "record": {
                "evaluation_split": {
                    "development": {"start": "2025-03-28", "end_exclusive": "2025-11-13"},
                }
            }
        },
    )
    _manifest_for(
        root,
        ["ranking.json", "report.md", "protocol.json"],
        artifact_identity="w" * 64,
        evidence_label="retrospective_screening",
        strategy_identities=["a" * 64],
        record_counts={"trades": 7},
    )
    return root


def _metric_row(cohort: str) -> dict[str, object]:
    return {
        "cohort": cohort,
        "member_count": 1,
        "closed_trades": 1,
        "starting_capital": "100000",
        "ending_equity": "101000",
        "gross_profit": "1000",
        "gross_return": "0.01",
        "maximum_drawdown": "0.02",
        "maximum_drawdown_dollars": "2000",
        "profit_drawdown": "0.5",
        "positive_revision_count": 1,
        "negative_revision_count": 0,
        "flat_revision_count": 0,
    }


def _project_report_artifacts(runs_root: Path) -> None:
    identity = "a" * 64
    comparison = runs_root / data.BACKTEST_ROOT_NAME / data.COHORT_COMPARISON_DIR
    _write(
        comparison / "manifest.json",
        {
            "analysis_identity": "q" * 64,
            "source": {
                "evidence_start": "2026-03-13",
                "evidence_end_exclusive": "2026-06-09",
                "outcome_end_exclusive": "2026-07-10",
                "oos_artifact_identity": "o" * 64,
                "cohort_selection_identity": "s" * 64,
            },
        },
    )
    _write(
        comparison / "cohort_metrics.json",
        {"rows": [_metric_row("VF9"), _metric_row("MC5"), _metric_row("FO4")]},
    )
    _write(
        comparison / "strategy_metrics.json",
        {
            "rows": [
                {
                    "strategy_revision_identity": identity,
                    "strategy_name": "monthly-ema6-above__return5-cross-zero__rolling-low20__target-risk1p75",
                    "display_name": "M6-above__return5-cross-zero__rolling-low20__target-risk1p75",
                    "membership": "MC5",
                    "closed_trades": 1,
                    "gross_profit": "1000",
                    "gross_return": "0.01",
                    "maximum_drawdown": "0.02",
                    "maximum_drawdown_dollars": "2000",
                    "profit_drawdown": "0.5",
                    "turnover": "1.2",
                    "exposure_mean": "0.5",
                    "exposure_maximum": "0.8",
                    "break_even_proportional_cost": "0.001",
                }
            ]
        },
    )
    (comparison / "cohort_equity.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "session": "2026-03-13",
                    "cohort": cohort,
                    "normalized_index": "100",
                    "drawdown": "0",
                }
            )
            for cohort in data.COHORT_ORDER
        )
        + "\n",
        encoding="utf-8",
    )

    oos = runs_root / data.BACKTEST_ROOT_NAME / "oos-v1"
    _write(oos / "manifest.json", {"limitations": [{"kind": "sample", "statement": "sample limitation"}]})
    (oos / "candidates.jsonl").write_text(
        json.dumps(
            {
                "identity": "candidate-1",
                "record": {
                    "strategy_revision_identity": identity,
                    "symbol": "AAA",
                    "signal_session": "2026-03-13",
                    "signal_close": "10",
                    "average_dollar_volume": "100000000",
                    "priority_value": "0.1",
                    "signal_facts": {
                        "daily_return5": {"value": "0.1"},
                        "daily_rolling_low20": {"value": "9"},
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (oos / "trades.jsonl").write_text(
        json.dumps(
            {
                "identity": "trade-1",
                "record": {
                    "candidate_identity": "candidate-1",
                    "symbol": "AAA",
                    "permanent_id": "pid",
                    "entry_session": "2026-03-16",
                    "exit_session": "2026-03-20",
                    "entry_price": "10",
                    "exit_price": "11",
                    "quantity": "100",
                    "gross_pnl": "1000",
                    "exit_reason": "target",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write(
        oos / "strategies" / f"{identity}.json",
        {
            "geometries": [
                {
                    "candidate_identity": "candidate-1",
                    "initial_stop_price": "9",
                    "target_price": "11",
                    "planned_hold_sessions": 21,
                }
            ],
            "strategy": {
                "strategy_name": "monthly-ema6-above__return5-cross-zero__rolling-low20__target-risk1p75",
                "readable_rules": [
                    "monthly close is above its EMA6",
                    "5-session return crosses above zero",
                ],
                "parameters": {
                    "program": {
                        "features": [
                            {"name": "daily_return5"},
                            {"name": "daily_rolling_low20"},
                        ]
                    }
                },
            },
        },
    )


@pytest.fixture
def runs_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    _forward_run(root)
    _backtest_window(root, "development-v1")
    return root


@pytest.fixture
def client(runs_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DASHBOARD_SECRET", SECRET)
    app = create_app(runs_root=runs_root, repo_root=tmp_path)
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, make_session("t@example.com", "viewer", SECRET))
    return client


# --------------------------------------------------------------- tolerance


def test_missing_run_yields_empty_results_not_exceptions(tmp_path: Path):
    empty = tmp_path / "nothing"
    assert data.forward_charter(empty) == {}
    assert data.forward_state(empty) == {}
    assert data.forward_cohorts(empty) == []
    assert data.forward_trades(empty) == []
    assert data.forward_sessions(empty) == []
    assert data.forward_cohort(empty, "VF9") is None
    assert data.forward_overview(empty)["present"] is False
    assert data.backtest_window(empty, "oos-v1")["present"] is False
    assert data.cohort_comparison(empty)["present"] is False
    assert data.seal(empty)["present"] is False


def test_corrupt_files_are_skipped_rather_than_raising(tmp_path: Path, runs_root: Path):
    root = runs_root / data.FORWARD_RUN_ID
    (root / "state.json").write_text("{not json", encoding="utf-8")
    (root / "equity.jsonl").write_text('{"ok": 1}\nnot json\n\n', encoding="utf-8")

    assert data.forward_state(runs_root) == {}
    assert data.read_jsonl(root / "equity.jsonl") == [{"ok": 1}]
    # The charter still parses, so the cohorts survive with unresolved books.
    cohorts = {row["cohort"]: row for row in data.forward_cohorts(runs_root)}
    assert cohorts["VF9"]["members_resolved"] == 0
    assert cohorts["VF9"]["current_equity"] is None


def test_read_jsonl_limit_keeps_the_tail(tmp_path: Path):
    path = tmp_path / "rows.jsonl"
    path.write_text("\n".join(json.dumps({"i": i}) for i in range(10)) + "\n", encoding="utf-8")
    assert data.read_jsonl(path, limit=3) == [{"i": 7}, {"i": 8}, {"i": 9}]


# --------------------------------------------------------------- integrity


def test_manifest_mismatch_is_reported_not_raised(runs_root: Path):
    root = runs_root / data.FORWARD_RUN_ID
    assert data.verify_manifest(root)["status"] == "ok"

    (root / "state.json").write_text(json.dumps({**STATE, "status": "tampered"}), encoding="utf-8")
    report = data.verify_manifest(root)
    assert report["status"] == "degraded"
    assert report["mismatched"] == ["state.json"]
    # The run still renders underneath the banner.
    assert data.forward_overview(runs_root)["status"] == "tampered"


def test_an_absent_hashed_file_is_partial_not_degraded(runs_root: Path):
    """The curated subset pushed to the VM omits hashed raw projections.

    Reporting that as `degraded` would fire the warning banner permanently on
    every backtest view, which is how a banner stops being read.
    """
    root = runs_root / data.FORWARD_RUN_ID
    (root / "trades.jsonl").unlink()
    report = data.verify_manifest(root)
    assert report["status"] == "partial"
    assert report["missing"] == ["trades.jsonl"]
    assert report["mismatched"] == []


def test_a_changed_file_outranks_absent_ones(runs_root: Path):
    root = runs_root / data.FORWARD_RUN_ID
    (root / "trades.jsonl").unlink()
    (root / "equity.jsonl").write_text("tampered\n", encoding="utf-8")
    report = data.verify_manifest(root)
    assert report["status"] == "degraded"
    assert report["mismatched"] == ["equity.jsonl"]
    assert report["missing"] == ["trades.jsonl"]


def test_absent_manifest_is_unavailable_not_degraded(tmp_path: Path):
    report = data.verify_manifest(tmp_path)
    assert report["status"] == "unavailable"
    assert report["checked"] == 0


# ----------------------------------------------------------------- charter


def test_cohorts_keep_charter_order_membership_and_eligibility(runs_root: Path):
    rows = data.forward_cohorts(runs_root)
    assert [row["cohort"] for row in rows] == ["VF9", "MC5", "FO4"]
    by_name = {row["cohort"]: row for row in rows}
    assert by_name["VF9"]["member_count"] == 2
    assert by_name["FO4"]["forward_eligible"] is False
    assert by_name["FO4"]["role"] == "diagnostic"
    assert by_name["VF9"]["forward_eligible"] is True


def test_evidence_tier_follows_the_weakest_revision(runs_root: Path):
    by_name = {row["cohort"]: row for row in data.forward_cohorts(runs_root)}
    # VF9 holds a 12-trade and a 4-trade book, so it is pre-evidence.
    assert by_name["VF9"]["minimum_closed_trades_per_revision"] == 4
    assert by_name["VF9"]["evidence_tier"] == "pre_10"
    # MC5 holds only the 12-trade book.
    assert by_name["MC5"]["evidence_tier"] == "descriptive_10"


def test_cohort_equity_uses_declared_starting_capital(runs_root: Path):
    rows = data.forward_cohort_equity(runs_root, "VF9")
    assert [row["session"] for row in rows] == ["2026-08-03", "2026-08-04"]
    assert rows[0]["starting_capital"] == "200000"
    assert rows[0]["raw_equity"] == "200000"
    assert rows[0]["normalized_index"] == "100"
    assert rows[1]["raw_equity"] == "200000"


def test_cohort_equity_is_empty_when_a_member_has_no_rows(runs_root: Path):
    root = runs_root / data.FORWARD_RUN_ID
    kept = [
        line
        for line in (root / "equity.jsonl").read_text().splitlines()
        if "b" * 64 not in line
    ]
    (root / "equity.jsonl").write_text("\n".join(kept) + "\n", encoding="utf-8")
    assert data.forward_cohort_equity(runs_root, "VF9") == []


def test_unknown_cohort_is_none(runs_root: Path):
    assert data.forward_cohort(runs_root, "ZZ9") is None


# ---------------------------------------------------------------- backtests


def test_window_rankings_are_independent_and_shed_bulky_metrics(runs_root: Path):
    detail = data.backtest_window(runs_root, "development-v1")
    assert detail is not None
    assert set(detail["rankings"]) == set(data.RANKING_AXES)
    entry = detail["rankings"]["profit"][0]
    assert entry["strategy_name"].startswith("monthly-ema6-below")
    assert entry["gross_profit"] == "1234.5"
    assert "candidate_signals" not in entry
    assert "filled_trade_signals" not in entry


def test_window_bounds_fall_back_to_the_frozen_split(runs_root: Path):
    row = next(
        r for r in data.backtest_windows(runs_root) if r["window"] == "development-v1"
    )
    assert row["evidence_window"] == "development"
    assert row["evidence_start"] == "2025-03-28"
    assert row["evidence_end_exclusive"] == "2025-11-13"


def test_absent_window_is_reported_as_absent(runs_root: Path):
    row = next(r for r in data.backtest_windows(runs_root) if r["window"] == "oos-v1")
    assert row["present"] is False
    assert data.backtest_window(runs_root, "nope") is None


def test_strategy_names_prefer_the_compact_index(tmp_path: Path):
    window = tmp_path / "w"
    strategies = window / "strategies"
    strategies.mkdir(parents=True)
    _write(
        strategies / f"{'c' * 64}.json",
        {"strategy_identity": "c" * 64, "strategy": {"strategy_name": "from-directory"}},
    )
    assert data.strategy_names(window) == {"c" * 64: "from-directory"}

    _write(window / "strategy_names.json", {"strategies": {"c" * 64: "from-index"}})
    assert data.strategy_names(window) == {"c" * 64: "from-index"}


# --------------------------------------------------------------------- api


def test_unauthenticated_api_is_401_and_pages_redirect(runs_root: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_SECRET", SECRET)
    anonymous = TestClient(create_app(runs_root=runs_root, repo_root=tmp_path))
    assert anonymous.get("/healthz").json() == {"ok": True}
    assert anonymous.get("/api/overview").status_code == 401
    assert anonymous.get("/", follow_redirects=False).status_code == 303
    assert anonymous.get("/", follow_redirects=False).headers["location"] == "/login"


def test_a_forged_cookie_does_not_authenticate(runs_root: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_SECRET", SECRET)
    forged = TestClient(create_app(runs_root=runs_root, repo_root=tmp_path))
    forged.cookies.set(SESSION_COOKIE, make_session("t@example.com", "admin", "other-secret"))
    assert forged.get("/api/overview").status_code == 401


def test_overview_route_carries_forward_and_backtests(client: TestClient):
    payload = client.get("/api/overview").json()
    assert payload["forward"]["run_id"] == data.FORWARD_RUN_ID
    assert [w["window"] for w in payload["backtests"]] == list(data.BACKTEST_WINDOWS)
    assert "legacy_dashboard_url" not in payload
    assert payload["degraded"] == []


def test_cohort_routes(client: TestClient):
    assert client.get("/api/forward/VF9").json()["cohort"] == "VF9"
    assert client.get("/api/forward/ZZ9").status_code == 404
    # Literal paths must win over the {cohort} placeholder.
    assert "sessions" in client.get("/api/forward/sessions").json()
    assert "positions" in client.get("/api/forward/open-positions").json()


def test_backtest_cohorts_path_wins_over_the_window_placeholder(client: TestClient):
    body = client.get("/api/backtests/cohorts").json()
    assert "cohort_metrics" in body
    assert client.get("/api/backtests/nope").status_code == 404


def test_project_report_api_and_standalone_route(
    client: TestClient,
    runs_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _project_report_artifacts(runs_root)

    body = client.get("/api/backtests/project-report").json()
    assert body["present"] is True
    assert [(c["cohort"], len(c["strategies"])) for c in body["cohorts"]] == [
        ("VF9", 1),
        ("MC5", 1),
        ("FO4", 0),
    ]
    example = body["cohorts"][1]["strategies"][0]["examples"][0]
    assert example["kind"] == "win"
    assert example["trade"]["symbol"] == "AAA"
    assert example["geometry"]["target_price"] == "11"
    provenance = body["cohorts"][1]["strategies"][0]["provenance"]
    assert "why_chosen" in provenance
    assert "found_by" in provenance
    assert "tested_by" in provenance

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "project-report.html").write_text(
        "<!doctype html><title>report</title>",
        encoding="utf-8",
    )
    monkeypatch.setenv("DASHBOARD_SECRET", SECRET)
    app = create_app(runs_root=runs_root, repo_root=tmp_path, dist_dir=dist)
    standalone = TestClient(app)
    standalone.cookies.set(SESSION_COOKIE, make_session("t@example.com", "viewer", SECRET))
    response = standalone.get("/project-report.html")
    assert response.status_code == 200
    assert "<title>report</title>" in response.text


def test_degraded_run_still_serves_the_overview(client: TestClient, runs_root: Path):
    (runs_root / data.FORWARD_RUN_ID / "state.json").write_text("{}", encoding="utf-8")
    response = client.get("/api/overview")
    assert response.status_code == 200
    assert response.json()["degraded"] == [data.FORWARD_RUN_ID]


def test_a_curated_window_is_partial_and_not_flagged_degraded(
    client: TestClient, runs_root: Path
):
    (runs_root / data.BACKTEST_ROOT_NAME / "development-v1" / "report.md").unlink()
    payload = client.get("/api/overview").json()
    assert payload["degraded"] == []
    assert payload["partial"] == ["development-v1"]


def test_the_dashboard_never_imports_the_writing_engine():
    """The read layer must not be able to advance or truncate a run.

    Checked on the import graph rather than the file text, so prose about the
    firewall in a docstring does not read as a breach of it.
    """
    import ast

    source = Path(__file__).resolve().parents[1] / "src/sts/swing_ranking/dashboard"
    forbidden = {"sts.swing_ranking.forward", "sts.swing_ranking.runner"}
    for path in sorted(source.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {alias.name for alias in node.names} & forbidden, path
            elif isinstance(node, ast.ImportFrom):
                assert node.module not in forbidden, path


# ------------------------------------------------------------- unified legacy


@pytest.fixture
def legacy_roots(tmp_path: Path) -> LegacyRoots:
    roots = LegacyRoots.under(tmp_path / "legacy")
    roots.ledger.mkdir(parents=True)
    roots.runs.mkdir(parents=True)
    roots.runs_summary.mkdir(parents=True)
    roots.logs.mkdir(parents=True)
    roots.configs.mkdir(parents=True)
    (roots.ledger / "equity.jsonl").write_text(
        '\n'.join(
            [
                json.dumps({"book": "shared", "date": "2026-07-10", "equity": 100000}),
                "corrupt",
                json.dumps({"book": "h1solo", "date": "2026-07-10", "equity": 100100}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (roots.ledger / "h1.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "entry_id": "one",
                        "seq": 1,
                        "family": "h1",
                        "status": "open",
                        "usd_deployed": 1000,
                    }
                ),
                json.dumps(
                    {
                        "entry_id": "two",
                        "seq": 2,
                        "family": "h1",
                        "status": "closed",
                        "pnl_usd": 125,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (roots.ledger / "h2.jsonl").write_text("", encoding="utf-8")
    (roots.ledger / "signals.jsonl").write_text(
        json.dumps({"date": "2026-07-10", "kind": "upkeep_done"}) + "\n",
        encoding="utf-8",
    )
    _write(
        roots.runs_summary / "h1.json",
        {
            "family": "h1",
            "verdict": "PROCEED",
            "metrics": {"layer_b": {"gross": {"expectancy_r": 0.2}}},
            "trades": [{"symbol": "A"}],
            "equity_curve": [{"date": "2026-01-01"}],
        },
    )
    _write(roots.runs_summary / "h2.json", {"family": "h2", "verdict": "PARK"})
    (roots.runs_summary / "broken.json").write_text("{", encoding="utf-8")
    (roots.configs / "study_roster.yaml").write_text("symbols: [AAPL, SPY]\n", encoding="utf-8")
    (roots.configs / "dashboard_settings.yaml").write_text(
        "discord_alerts: true\nmonitor_gap_alert_pct: 0.1\n", encoding="utf-8"
    )
    (roots.configs.parent / "universe.yaml").write_text("seeds: [SPY]\n", encoding="utf-8")
    assert roots.env_file is not None
    roots.env_file.write_text("GOOGLE_CLIENT_SECRET=secret\nTZ=America/Los_Angeles\n", encoding="utf-8")
    (roots.logs / "eod.log").write_text("complete\n", encoding="utf-8")
    (roots.logs / "fill.log").write_text("fatal error\n", encoding="utf-8")
    return roots


@pytest.fixture
def legacy_client(
    runs_root: Path,
    legacy_roots: LegacyRoots,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    monkeypatch.setenv("DASHBOARD_SECRET", SECRET)
    app = create_app(runs_root=runs_root, repo_root=tmp_path, legacy_roots=legacy_roots)
    result = TestClient(app)
    result.cookies.set(SESSION_COOKIE, make_session("viewer@example.com", "viewer", SECRET))
    return result


def test_legacy_get_routes_match_recovered_contract(legacy_client: TestClient):
    overview = legacy_client.get("/api/legacy/overview")
    assert overview.status_code == 200
    assert overview.json()["tiles"] == {
        "total_pnl": 125.0,
        "open_count": 1,
        "usd_deployed": 1000.0,
        "win_rate": 1.0,
    }
    assert [row["book"] for row in overview.json()["equity"]] == ["h1solo", "shared"]

    assert legacy_client.get("/api/legacy/forward/h1").json()["open"][0]["entry_id"] == "one"
    assert legacy_client.get("/api/legacy/forward/h2").json() == {"rows": [], "open": []}
    assert legacy_client.get("/api/legacy/forward/h3").status_code == 404

    summaries = legacy_client.get("/api/legacy/backtests").json()
    assert [summary["family"] for summary in summaries] == ["h1", "h2"]
    assert "trades" not in summaries[0]
    assert "equity_curve" not in summaries[0]
    assert legacy_client.get("/api/legacy/backtests/h1").json()["trades"] == [{"symbol": "A"}]
    assert legacy_client.get("/api/legacy/backtests/missing").status_code == 404

    config = legacy_client.get("/api/legacy/config").json()
    assert config["env"] == {"GOOGLE_CLIENT_SECRET": "•••", "TZ": "America/Los_Angeles"}
    assert config["universe"] == {"seeds": ["SPY"]}
    assert config["editable"]["discord_alerts"] is True
    assert set(config["schema"]) == {
        "discord_alerts",
        "monitor_gap_alert_pct",
        "monitor_dd_alert_pct",
    }

    statuses = {row["name"]: row["status"] for row in legacy_client.get("/api/legacy/jobs").json()}
    assert statuses == {"eod": "ok", "fill": "failed", "monitor": "unknown", "sync": "unknown"}


def test_missing_and_corrupt_legacy_files_degrade_without_500(
    runs_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("DASHBOARD_SECRET", SECRET)
    roots = LegacyRoots.under(tmp_path / "absent")
    client = TestClient(create_app(runs_root=runs_root, repo_root=tmp_path, legacy_roots=roots))
    client.cookies.set(SESSION_COOKIE, make_session("v@example.com", "viewer", SECRET))
    assert client.get("/api/legacy/overview").json()["tiles"]["open_count"] == 0
    assert client.get("/api/legacy/backtests").json() == []
    assert client.get("/api/legacy/config").json()["editable"] == {}
    assert all(row["status"] == "unknown" for row in client.get("/api/legacy/jobs").json())


def test_one_session_authenticates_both_api_families_and_logout_invalidates_it(
    legacy_client: TestClient,
):
    assert legacy_client.get("/api/overview").status_code == 200
    assert legacy_client.get("/api/legacy/overview").status_code == 200
    response = legacy_client.post("/auth/logout")
    assert response.status_code == 200
    assert "Max-Age=0" in response.headers["set-cookie"]
    # TestClient does not evict a cookie inserted manually without a domain;
    # a browser applies the expiry header above.
    legacy_client.cookies.clear()
    assert legacy_client.get("/api/overview").status_code == 401
    assert legacy_client.get("/api/legacy/overview").status_code == 401


def test_viewer_cannot_mutate_legacy_resources(legacy_client: TestClient):
    assert legacy_client.post("/api/legacy/sync").status_code == 403
    assert legacy_client.put("/api/legacy/config/safe", json={"discord_alerts": False}).status_code == 403


def test_admin_config_update_is_validated_and_audited(
    legacy_client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    legacy_client.cookies.set(SESSION_COOKIE, make_session("admin@example.com", "admin", SECRET))
    assert legacy_client.put("/api/legacy/config/safe", json={"strategy": "changed"}).status_code == 422

    monkeypatch.setattr(
        legacy_admin,
        "update_config",
        lambda base_url, token, updates: {
            "old": {"discord_alerts": True},
            "new": {"discord_alerts": updates["discord_alerts"]},
        },
    )
    response = legacy_client.put("/api/legacy/config/safe", json={"discord_alerts": False})
    assert response.status_code == 200
    assert response.json() == {"discord_alerts": False}
    record = json.loads((tmp_path / "logs" / "dashboard-audit.log").read_text().splitlines()[-1])
    assert record["scope"] == "legacy"
    assert record["target"] == "configs/dashboard_settings.yaml"
    assert record["detail"]["before"] == {"discord_alerts": True}
    assert record["detail"]["after"] == {"discord_alerts": False}


def test_admin_sync_success_and_contention_are_bounded(
    legacy_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    legacy_client.cookies.set(SESSION_COOKIE, make_session("admin@example.com", "admin", SECRET))
    monkeypatch.setattr(
        legacy_admin, "start_sync", lambda base_url, token: {"id": "123456789abc"}
    )
    assert legacy_client.post("/api/legacy/sync").json() == {"id": "123456789abc"}

    def contention(base_url, token):
        raise FileExistsError

    monkeypatch.setattr(legacy_admin, "start_sync", contention)
    assert legacy_client.post("/api/legacy/sync").status_code == 409


def test_every_legacy_page_direct_load_uses_the_spa_fallback(
    runs_root: Path,
    legacy_roots: LegacyRoots,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("DASHBOARD_SECRET", SECRET)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<main>unified</main>", encoding="utf-8")
    client = TestClient(
        create_app(
            runs_root=runs_root,
            repo_root=tmp_path,
            legacy_roots=legacy_roots,
            dist_dir=dist,
        )
    )
    client.cookies.set(SESSION_COOKIE, make_session("v@example.com", "viewer", SECRET))
    for path in (
        "/legacy",
        "/legacy/forward/h1",
        "/legacy/forward/h2",
        "/legacy/backtests",
        "/legacy/backtests/h1",
        "/legacy/config",
        "/legacy/jobs",
    ):
        assert client.get(path).text == "<main>unified</main>"
