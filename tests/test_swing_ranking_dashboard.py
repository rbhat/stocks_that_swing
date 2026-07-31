from __future__ import annotations

import json
from pathlib import Path

import pytest

from sts.swing_ranking.dashboard import data
from sts.swing_ranking.identity import sha256_hex

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from sts.swing_ranking.dashboard.app import create_app  # noqa: E402
from sts.swing_ranking.dashboard.auth import SESSION_COOKIE, make_session  # noqa: E402

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


def test_overview_route_carries_forward_backtests_and_legacy_link(client: TestClient):
    payload = client.get("/api/overview").json()
    assert payload["forward"]["run_id"] == data.FORWARD_RUN_ID
    assert [w["window"] for w in payload["backtests"]] == list(data.BACKTEST_WINDOWS)
    assert payload["legacy_dashboard_url"] == "http://127.0.0.1:8000"
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
    for path in sorted(source.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {alias.name for alias in node.names} & forbidden, path
            elif isinstance(node, ast.ImportFrom):
                assert node.module not in forbidden, path
