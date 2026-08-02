"""Tolerant, read-only readers for the forward ledger and backtest artifacts.

Every function here is read-only and tolerant of missing or corrupt files: a
missing directory, an unparseable JSON document, or a truncated JSONL line
yields an empty result rather than an exception. That discipline is inherited
from the legacy dashboard's `data.py`; the schemas are not.

This module deliberately does not import `sts.swing_ranking.forward` or any
other part of the writing engine. It reimplements the little reading it needs
directly on top of the artifact files, so the dashboard can never advance,
truncate, or re-hash a run. Decimal-valued fields are passed through as the
strings the artifacts store; they are never parsed into floats here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

FORWARD_RUN_ID = "swing-ranking-v1-forward-01"
BACKTEST_ROOT_NAME = "swing-ranking-v1"

#: Screening windows, in evaluation order.
BACKTEST_WINDOWS: tuple[str, ...] = ("development-v1", "validation-v1", "oos-v1")
COHORT_COMPARISON_DIR = "oos-cohort-comparison-v1"
SEAL_DIR = "oos-seal-v1"

#: Charter order: the two forward-eligible cohorts first, then the diagnostic.
COHORT_ORDER: tuple[str, ...] = ("VF9", "MC5", "FO4")

#: Ranking axes, ranked independently and never combined into a composite.
RANKING_AXES: tuple[str, ...] = ("profit", "drawdown", "profit_drawdown")

#: `metrics` records embed every candidate and filled-trade signal. They are
#: megabytes per revision and no view needs them, so they are dropped on read.
_BULKY_METRIC_FIELDS = frozenset({"candidate_signals", "filled_trade_signals"})


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------


def read_json(path: Path) -> dict[str, Any] | None:
    """Parse a JSON object. Missing, unreadable, or non-object -> None."""
    try:
        text = Path(path).read_text()
    except (OSError, UnicodeDecodeError):
        return None
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def read_jsonl(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Parse a JSONL file, skipping any line that fails to parse.

    `limit` keeps the last N rows, which is what every tail view wants and
    what stops a large projection from being held in memory twice.
    """
    rows: list[dict[str, Any]] = []
    try:
        with Path(path).open() as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                    if limit is not None and len(rows) > limit:
                        del rows[0]
    except (OSError, UnicodeDecodeError):
        return []
    return rows


def _sha256_file(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _decimal(value: object) -> Decimal | None:
    """Parse an artifact decimal string. Anything else -> None."""
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    return None


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _strip_metrics(metrics: object) -> dict[str, Any]:
    if not isinstance(metrics, dict):
        return {}
    return {k: v for k, v in metrics.items() if k not in _BULKY_METRIC_FIELDS}


# ---------------------------------------------------------------------------
# integrity
# ---------------------------------------------------------------------------


def verify_manifest(root: Path) -> dict[str, Any]:
    """Re-hash the files a run's `manifest.json` claims and report divergence.

    A mismatch is data for a banner, never an exception: the caller must still
    be able to render the run underneath it. `status` is one of:

    - `ok` — every hashed file is present and matches;
    - `partial` — everything present matches, but some hashed files are absent.
      That is the normal state of a screening window on the VM, which carries
      only the curated subset `deploy/push_backtests.sh` ships; the raw
      projections are hashed by the manifest and deliberately not sent;
    - `degraded` — a file is present and its content has changed. This is the
      only status that means something is wrong;
    - `unavailable` — no readable manifest.

    Keeping `partial` distinct matters: a banner that fires permanently on
    every backtest view is a banner nobody reads when it finally means
    something.
    """
    root = Path(root)
    manifest = read_json(root / "manifest.json")
    hashes = (manifest or {}).get("content_hashes")
    if not isinstance(hashes, dict):
        return {
            "status": "unavailable",
            "checked": 0,
            "mismatched": [],
            "missing": [],
            "detail": "manifest.json is absent or carries no content hashes",
        }

    mismatched: list[str] = []
    missing: list[str] = []
    for name in sorted(hashes):
        expected = hashes[name]
        actual = _sha256_file(root / name)
        if actual is None:
            missing.append(name)
        elif actual != expected:
            mismatched.append(name)

    if mismatched:
        status = "degraded"
        detail = "content changed since manifest.json was written"
    elif missing:
        status = "partial"
        detail = (
            f"{len(missing)} of {len(hashes)} hashed files are not on this host; "
            "every file present matches"
        )
    else:
        status = "ok"
        detail = "content hashes match"
    return {
        "status": status,
        "checked": len(hashes),
        "mismatched": mismatched,
        "missing": missing,
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# forward ledger
# ---------------------------------------------------------------------------


def _forward_root(runs_root: Path, run_id: str = FORWARD_RUN_ID) -> Path:
    return Path(runs_root) / run_id


def forward_charter(runs_root: Path) -> dict[str, Any]:
    return read_json(_forward_root(runs_root) / "charter.json") or {}


def forward_state(runs_root: Path) -> dict[str, Any]:
    return read_json(_forward_root(runs_root) / "state.json") or {}


def _books(state: dict[str, Any]) -> list[dict[str, Any]]:
    return _rows(state.get("books"))


def _cohort_members(charter: dict[str, Any]) -> dict[str, list[str]]:
    cohorts = charter.get("cohorts")
    if not isinstance(cohorts, dict):
        return {}
    members: dict[str, list[str]] = {}
    for name, identities in cohorts.items():
        if isinstance(identities, list):
            members[str(name)] = [str(i) for i in identities if isinstance(i, str)]
    return members


def _book_summary(book: dict[str, Any]) -> dict[str, Any]:
    """The subset of a state book a view needs, with equity as a string."""
    return {
        "strategy_revision_identity": _text(book.get("strategy_revision_identity")),
        "strategy_name": _text(book.get("strategy_name")),
        "memberships": [m for m in book.get("memberships", []) if isinstance(m, str)],
        "status": _text(book.get("status")),
        "starting_equity": _text(book.get("starting_equity")) or "100000",
        "current_equity": _text(book.get("current_equity")),
        "closed_trades": int(book.get("closed_trades") or 0),
        "open_positions": int(book.get("open_positions") or 0),
        "maximum_drawdown": _text(book.get("maximum_drawdown")),
        "maximum_drawdown_dollars": _text(book.get("maximum_drawdown_dollars")),
        "turnover": _text(book.get("turnover")),
        "session_count": int(book.get("session_count") or 0),
    }


def _evidence_tier(minimum_closed: int, thresholds: dict[str, Any]) -> str:
    """Charter evidence tier for a cohort's weakest member.

    Ten- and twenty-trade views are explicitly descriptive; only 30 closed
    trades per revision is decision-ready.
    """
    decision = int(thresholds.get("decision_ready_closed_trades_per_revision") or 30)
    interim = thresholds.get("interim_closed_trades_per_revision")
    tiers = sorted(int(t) for t in interim) if isinstance(interim, list) else [10, 20]
    if minimum_closed >= decision:
        return "decision_ready"
    for tier in reversed(tiers):
        if minimum_closed >= tier:
            return f"descriptive_{tier}"
    return f"pre_{tiers[0] if tiers else 10}"


def forward_cohorts(runs_root: Path) -> list[dict[str, Any]]:
    """One summary row per cohort, in charter order.

    Cohort equity is the sum of member book equities. Because every book
    starts at the same capital, equal weighting after normalising each book is
    the same number as the raw sum divided by the cohort's starting capital.
    """
    charter = forward_charter(runs_root)
    state = forward_state(runs_root)
    members = _cohort_members(charter)
    thresholds = charter.get("evidence_thresholds")
    thresholds = thresholds if isinstance(thresholds, dict) else {}
    eligible = charter.get("forward_eligible_cohorts")
    eligible = [c for c in eligible if isinstance(c, str)] if isinstance(eligible, list) else []
    reported = state.get("cohort_status")
    reported = reported if isinstance(reported, dict) else {}

    by_identity = {
        _text(book.get("strategy_revision_identity")): book for book in _books(state)
    }
    order = [c for c in COHORT_ORDER if c in members] + sorted(
        c for c in members if c not in COHORT_ORDER
    )

    summaries: list[dict[str, Any]] = []
    for cohort in order:
        identities = members[cohort]
        books = [by_identity[i] for i in identities if i in by_identity]
        closed = [int(b.get("closed_trades") or 0) for b in books]
        starting = Decimal(0)
        current = Decimal(0)
        complete = bool(books)
        for book in books:
            start = _decimal(book.get("starting_equity"))
            now = _decimal(book.get("current_equity"))
            if start is None or now is None:
                complete = False
                continue
            starting += start
            current += now
        minimum_closed = min(closed) if closed else 0
        summaries.append(
            {
                "cohort": cohort,
                "member_count": len(identities),
                "members_resolved": len(books),
                "forward_eligible": cohort in eligible,
                "role": "forward" if cohort in eligible else "diagnostic",
                "closed_trades": sum(closed),
                "minimum_closed_trades_per_revision": minimum_closed,
                "open_positions": sum(int(b.get("open_positions") or 0) for b in books),
                "starting_capital": str(starting) if complete else None,
                "current_equity": str(current) if complete else None,
                "evidence_tier": _evidence_tier(minimum_closed, thresholds),
                "charter_status": _text(reported.get(cohort)),
            }
        )
    return summaries


def _equity_by_identity(runs_root: Path) -> dict[str, list[dict[str, Any]]]:
    """session-ordered equity records keyed by strategy revision identity."""
    series: dict[str, list[dict[str, Any]]] = {}
    for row in read_jsonl(_forward_root(runs_root) / "equity.jsonl"):
        identity = _text(row.get("strategy_revision_identity"))
        record = row.get("record")
        if not identity or not isinstance(record, dict):
            continue
        series.setdefault(identity, []).append(record)
    for records in series.values():
        records.sort(key=lambda r: _text(r.get("session")))
    return series


def _cohort_starting_capital(charter: dict[str, Any], cohort: str, members: int) -> Decimal:
    """The cohort's declared raw starting capital, per the charter."""
    aggregation = charter.get("aggregation")
    aggregation = aggregation if isinstance(aggregation, dict) else {}
    declared = _decimal(aggregation.get(f"{cohort}_raw_starting_capital"))
    if declared is not None and declared > 0:
        return declared
    per_book = _decimal(aggregation.get("strategy_book_starting_capital")) or Decimal(100000)
    return per_book * members


def forward_cohort_equity(runs_root: Path, cohort: str) -> list[dict[str, Any]]:
    """Raw, normalised, and drawdown series for one cohort's member books.

    Starting capital is the charter's declared figure rather than the first
    recorded equity, so drawdown includes starting capital as the study's
    metrics do. Sessions where a member book has not yet recorded equity are
    skipped, so a partially advanced run yields a shorter curve, not a wrong one.
    """
    charter = forward_charter(runs_root)
    members = _cohort_members(charter).get(cohort)
    if not members:
        return []
    series = _equity_by_identity(runs_root)
    present = [identity for identity in members if identity in series]
    if len(present) != len(members):
        return []

    by_session: dict[str, dict[str, Decimal]] = {}
    for identity in present:
        for record in series[identity]:
            equity = _decimal(record.get("equity"))
            session = _text(record.get("session"))
            if equity is None or not session:
                continue
            by_session.setdefault(session, {})[identity] = equity

    starting = _cohort_starting_capital(charter, cohort, len(present))

    rows: list[dict[str, Any]] = []
    peak = starting
    for session in sorted(by_session):
        equities = by_session[session]
        if len(equities) != len(present):
            continue
        raw = sum(equities.values(), Decimal(0))
        peak = max(peak, raw)
        drawdown = Decimal(0) if peak == 0 else Decimal(1) - raw / peak
        normalized = Decimal(0) if starting == 0 else raw / starting * Decimal(100)
        rows.append(
            {
                "session": session,
                "cohort": cohort,
                "member_count": len(present),
                "raw_equity": str(raw),
                "normalized_index": str(normalized),
                "drawdown": str(drawdown),
                "starting_capital": str(starting),
            }
        )
    return rows


def forward_cohort(runs_root: Path, cohort: str) -> dict[str, Any] | None:
    """Members, equity curve, and recent closed trades for one cohort."""
    charter = forward_charter(runs_root)
    members = _cohort_members(charter).get(cohort)
    if not members:
        return None
    state = forward_state(runs_root)
    by_identity = {
        _text(book.get("strategy_revision_identity")): book for book in _books(state)
    }
    summary = next(
        (row for row in forward_cohorts(runs_root) if row["cohort"] == cohort),
        None,
    )
    member_rows = [
        _book_summary(by_identity[identity]) for identity in members if identity in by_identity
    ]
    member_rows.sort(key=lambda row: row["strategy_name"] or row["strategy_revision_identity"])
    return {
        "cohort": cohort,
        "summary": summary,
        "members": member_rows,
        "equity": forward_cohort_equity(runs_root, cohort),
        "trades": forward_trades(runs_root, identities=members, limit=200),
    }


def forward_trades(
    runs_root: Path,
    *,
    identities: Iterable[str] | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Most recent closed trades, newest last, optionally filtered by book."""
    wanted = set(identities) if identities is not None else None
    trades: list[dict[str, Any]] = []
    for row in read_jsonl(_forward_root(runs_root) / "trades.jsonl"):
        identity = _text(row.get("strategy_revision_identity"))
        record = row.get("record")
        if not isinstance(record, dict):
            continue
        if wanted is not None and identity not in wanted:
            continue
        trades.append({"strategy_revision_identity": identity, **record})
    trades.sort(key=lambda t: (_text(t.get("exit_session")), _text(t.get("entry_session"))))
    return trades[-limit:]


def forward_open_positions(runs_root: Path) -> list[dict[str, Any]]:
    """Open positions read out of the state checkpoint, never recomputed."""
    positions: list[dict[str, Any]] = []
    for book in _books(forward_state(runs_root)):
        execution = book.get("execution")
        if not isinstance(execution, dict):
            continue
        for position in _rows(execution.get("positions")):
            positions.append(
                {
                    "strategy_revision_identity": _text(
                        book.get("strategy_revision_identity")
                    ),
                    "strategy_name": _text(book.get("strategy_name")),
                    **position,
                }
            )
    return positions


def forward_sessions(runs_root: Path, *, limit: int = 60) -> list[dict[str, Any]]:
    """Most recent immutable per-session packages, newest first."""
    sessions_dir = _forward_root(runs_root) / "sessions"
    try:
        entries = sorted((p for p in sessions_dir.iterdir() if p.is_dir()), reverse=True)
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for entry in entries[:limit]:
        manifest = read_json(entry / "manifest.json") or {}
        counts = manifest.get("record_counts")
        rows.append(
            {
                "session": entry.name,
                "session_identity": _text(manifest.get("session_identity")),
                "record_counts": counts if isinstance(counts, dict) else {},
                "complete": bool(manifest),
            }
        )
    return rows


def forward_overview(runs_root: Path) -> dict[str, Any]:
    """Run status, charter bindings, cohort summaries, and integrity."""
    charter = forward_charter(runs_root)
    state = forward_state(runs_root)
    root = _forward_root(runs_root)
    manifest = read_json(root / "manifest.json") or {}
    books = [_book_summary(book) for book in _books(state)]
    closed = [book["closed_trades"] for book in books]
    return {
        "run_id": _text(charter.get("run_id")) or FORWARD_RUN_ID,
        "present": bool(charter or state),
        "status": _text(state.get("status")),
        "as_of": _text(state.get("as_of")),
        "last_processed_session": state.get("last_processed_session"),
        "next_eligible_signal_session": state.get("next_eligible_signal_session"),
        "first_eligible_signal_session": _text(charter.get("first_eligible_signal_session")),
        "no_backfill": charter.get("no_backfill") is True,
        "paper_only": charter.get("paper_only") is True,
        "decision_readiness": _text(state.get("decision_readiness")),
        "evidence_thresholds": charter.get("evidence_thresholds") or {},
        "forward_eligible_cohorts": charter.get("forward_eligible_cohorts") or [],
        "identities": {
            "forward_identity": _text(manifest.get("forward_identity")),
            "charter_identity": _text(charter.get("charter_identity")),
            "selection_identity": _text(charter.get("selection_identity")),
            "oos_seal_identity": _text(charter.get("oos_seal_identity")),
            "protocol_identity": _text(charter.get("protocol_identity")),
            "input_manifest_identity": _text(charter.get("input_manifest_identity")),
        },
        "strategy_count": len(books),
        "closed_trades": sum(closed),
        "minimum_closed_trades_per_revision": min(closed) if closed else 0,
        "open_positions": sum(book["open_positions"] for book in books),
        "session_count": len(forward_sessions(runs_root, limit=10_000)),
        "cohorts": forward_cohorts(runs_root),
        "books": books,
        "integrity": verify_manifest(root),
    }


# ---------------------------------------------------------------------------
# backtest evidence
# ---------------------------------------------------------------------------


def _backtest_root(runs_root: Path, window: str) -> Path:
    return Path(runs_root) / BACKTEST_ROOT_NAME / window


def strategy_names(window_root: Path) -> dict[str, str]:
    """identity -> strategy name for one screening window.

    Prefers the compact `strategy_names.json` written by
    `scripts/export_strategy_names.py`, because the full `strategies/`
    directory is hundreds of megabytes and is not shipped to the VM. Falls
    back to the directory when it is present, as it is on the local machine.
    """
    window_root = Path(window_root)
    compact = read_json(window_root / "strategy_names.json")
    rows = (compact or {}).get("strategies")
    if isinstance(rows, dict):
        return {str(k): _text(v) for k, v in rows.items() if isinstance(v, str)}

    names: dict[str, str] = {}
    try:
        paths = sorted((window_root / "strategies").glob("*.json"))
    except OSError:
        return names
    for path in paths:
        record = read_json(path) or {}
        strategy = record.get("strategy")
        identity = _text(record.get("strategy_identity")) or path.stem
        if isinstance(strategy, dict):
            names[identity] = _text(strategy.get("strategy_name"))
    return names


def _window_bounds(root: Path, window: str, manifest: dict[str, Any]) -> dict[str, str]:
    """Evidence boundaries for a window.

    The first development artifact predates the manifest carrying its own
    boundaries, so fall back to `selection.json` and then to the frozen split
    in `protocol.json`. Missing everywhere yields empty strings, not an error.
    """
    kind = _text(manifest.get("evidence_window")) or window.rsplit("-", 1)[0]
    bounds = {
        "evidence_window": kind,
        "evidence_start": _text(manifest.get("evidence_start")),
        "evidence_end_exclusive": _text(manifest.get("evidence_end_exclusive")),
        "outcome_end_exclusive": _text(manifest.get("outcome_end_exclusive")),
    }
    if bounds["evidence_start"] and bounds["evidence_end_exclusive"]:
        return bounds

    selection = (read_json(root / "selection.json") or {}).get("record")
    if isinstance(selection, dict):
        bounds["evidence_start"] = bounds["evidence_start"] or _text(selection.get("start"))
        bounds["evidence_end_exclusive"] = bounds["evidence_end_exclusive"] or _text(
            selection.get("end_exclusive")
        )
        bounds["outcome_end_exclusive"] = bounds["outcome_end_exclusive"] or _text(
            selection.get("outcome_end_exclusive")
        )
        if bounds["evidence_start"]:
            return bounds

    protocol = (read_json(root / "protocol.json") or {}).get("record")
    split = protocol.get("evaluation_split") if isinstance(protocol, dict) else None
    pane = split.get(kind) if isinstance(split, dict) else None
    if isinstance(pane, dict):
        bounds["evidence_start"] = bounds["evidence_start"] or _text(pane.get("start"))
        bounds["evidence_end_exclusive"] = bounds["evidence_end_exclusive"] or _text(
            pane.get("end_exclusive")
        )
    return bounds


def backtest_windows(runs_root: Path) -> list[dict[str, Any]]:
    """One row per screening window, present or not."""
    rows: list[dict[str, Any]] = []
    for window in BACKTEST_WINDOWS:
        root = _backtest_root(runs_root, window)
        manifest = read_json(root / "manifest.json") or {}
        counts = manifest.get("record_counts")
        rows.append(
            {
                "window": window,
                "present": bool(manifest),
                "evidence_label": _text(manifest.get("evidence_label")),
                **_window_bounds(root, window, manifest),
                "artifact_identity": _text(manifest.get("artifact_identity")),
                "strategy_count": len(manifest.get("strategy_identities") or []),
                "record_counts": counts if isinstance(counts, dict) else {},
            }
        )
    return rows


def _ranked_entries(
    ranking: dict[str, Any],
    axis: str,
    names: dict[str, str],
    top: int,
) -> list[dict[str, Any]]:
    record = ranking.get("record")
    entries = _rows((record or {}).get(axis)) if isinstance(record, dict) else []
    rows: list[dict[str, Any]] = []
    for position, entry in enumerate(entries[:top], start=1):
        metrics = _strip_metrics(entry.get("metrics"))
        identity = _text(entry.get("strategy_revision_identity")) or _text(
            metrics.get("strategy_revision_identity")
        )
        rows.append(
            {
                "rank": position,
                "strategy_revision_identity": identity,
                "strategy_name": names.get(identity, ""),
                "gross_profit": _text(metrics.get("gross_profit")),
                "gross_return": _text(metrics.get("gross_return")),
                "maximum_drawdown": _text(metrics.get("maximum_drawdown")),
                "profit_drawdown": _text(metrics.get("profit_drawdown")),
                "profit_drawdown_status": _text(metrics.get("profit_drawdown_status")),
                "trade_count": metrics.get("trade_count"),
                "turnover": _text(metrics.get("turnover")),
                "break_even_proportional_cost": _text(
                    metrics.get("break_even_proportional_cost")
                ),
            }
        )
    return rows


def backtest_window(runs_root: Path, window: str, *, top: int = 5) -> dict[str, Any] | None:
    """One screening window: three independent top-N rankings and its report.

    The three axes are returned separately and never merged into a composite
    score; that separation is the point of the ranking artifact.
    """
    if window not in BACKTEST_WINDOWS:
        return None
    root = _backtest_root(runs_root, window)
    manifest = read_json(root / "manifest.json") or {}
    ranking = read_json(root / "ranking.json") or {}
    names = strategy_names(root)
    summary = next(
        (row for row in backtest_windows(runs_root) if row["window"] == window),
        None,
    )
    try:
        report = (root / "report.md").read_text()
    except (OSError, UnicodeDecodeError):
        report = ""
    limitations = _rows(manifest.get("limitations"))
    return {
        "window": window,
        "summary": summary,
        "present": bool(manifest or ranking),
        "rankings": {
            axis: _ranked_entries(ranking, axis, names, top) for axis in RANKING_AXES
        },
        "ranking_identity": _text(ranking.get("artifact_identity")),
        "limitations": limitations,
        "source_hashes": manifest.get("source_hashes") or {},
        "report": report,
        "integrity": verify_manifest(root),
    }


def cohort_comparison(runs_root: Path) -> dict[str, Any]:
    """The sealed OOS cohort analysis: the backtest evidence behind the mix.

    Its equity is OOS equity. It is returned under its own key and is never
    concatenated with the forward curve.
    """
    root = Path(runs_root) / BACKTEST_ROOT_NAME / COHORT_COMPARISON_DIR
    manifest = read_json(root / "manifest.json") or {}
    cohort_metrics = read_json(root / "cohort_metrics.json") or {}
    strategy_metrics = read_json(root / "strategy_metrics.json") or {}
    chart_map = read_json(root / "chart_map.json") or {}
    try:
        report = (root / "report.md").read_text()
    except (OSError, UnicodeDecodeError):
        report = ""
    return {
        "present": bool(manifest or cohort_metrics),
        "source": manifest.get("source") or read_json(root / "source.json") or {},
        "analysis_identity": _text(manifest.get("analysis_identity")),
        "record_counts": manifest.get("record_counts") or {},
        "cohort_metrics": _rows(cohort_metrics.get("rows")),
        "strategy_metrics": _rows(strategy_metrics.get("rows")),
        "cohort_equity": read_jsonl(root / "cohort_equity.jsonl"),
        "leave_one_out": read_jsonl(root / "leave_one_out.jsonl"),
        "overlap": read_jsonl(root / "overlap.jsonl"),
        "charts": _rows(chart_map.get("charts")),
        "report": report,
        "integrity": verify_manifest(root),
    }


_COHORT_DESCRIPTIONS: dict[str, str] = {
    "VF9": (
        "Validation Frontier 9: every revision selected from the validation "
        "frontier. This is the broadest sealed cohort and contains MC5 plus FO4."
    ),
    "MC5": (
        "Multi-criterion 5: the five revisions that appeared in at least two "
        "validation top-five lists. This is one of the forward-eligible cohorts."
    ),
    "FO4": (
        "Frontier-only 4: the four VF9 revisions outside MC5. It is diagnostic "
        "OOS evidence, not a forward-eligible cohort."
    ),
}

_PRICE_INDICATORS = frozenset(
    {
        "daily_ema5",
        "daily_sma10",
        "daily_rolling_low10",
        "daily_rolling_low20",
        "daily_rolling_high20",
    }
)


def _read_strategy(window_root: Path, identity: str) -> dict[str, Any]:
    return read_json(window_root / "strategies" / f"{identity}.json") or {}


def _strategy_rules(strategy_file: dict[str, Any]) -> list[str]:
    strategy = strategy_file.get("strategy")
    rules = strategy.get("readable_rules") if isinstance(strategy, dict) else None
    if isinstance(rules, list):
        return [rule for rule in rules if isinstance(rule, str)]
    return []


def _strategy_program(strategy_file: dict[str, Any]) -> dict[str, Any]:
    strategy = strategy_file.get("strategy")
    parameters = strategy.get("parameters") if isinstance(strategy, dict) else None
    program = parameters.get("program") if isinstance(parameters, dict) else None
    return program if isinstance(program, dict) else {}


def _geometry_by_candidate(strategy_file: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        _text(row.get("candidate_identity")): row
        for row in _rows(strategy_file.get("geometries"))
        if _text(row.get("candidate_identity"))
    }


def _oos_candidates(window_root: Path) -> dict[str, dict[str, Any]]:
    return {
        _text(row.get("identity")): record
        for row in read_jsonl(window_root / "candidates.jsonl")
        for record in [row.get("record")]
        if _text(row.get("identity")) and isinstance(record, dict)
    }


def _oos_trades_by_strategy(window_root: Path) -> dict[str, list[dict[str, Any]]]:
    candidates = _oos_candidates(window_root)
    by_strategy: dict[str, list[dict[str, Any]]] = {}
    for row in read_jsonl(window_root / "trades.jsonl"):
        record = row.get("record")
        if not isinstance(record, dict):
            continue
        candidate = candidates.get(_text(record.get("candidate_identity")))
        if not candidate:
            continue
        identity = _text(candidate.get("strategy_revision_identity"))
        if not identity:
            continue
        by_strategy.setdefault(identity, []).append(
            {
                "trade_identity": _text(row.get("identity")),
                "strategy_revision_identity": identity,
                **record,
            }
        )
    for rows in by_strategy.values():
        rows.sort(key=lambda t: (_text(t.get("entry_session")), _text(t.get("exit_session"))))
    return by_strategy


def _float(value: object) -> float | None:
    decimal = _decimal(value)
    return float(decimal) if decimal is not None else None


def _format_decimal(value: object, places: int = 2) -> str:
    decimal = _decimal(value)
    if decimal is None:
        return ""
    return f"{decimal:.{places}f}"


def _selected_trade_examples(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not trades:
        return []
    winners = [trade for trade in trades if (_float(trade.get("gross_pnl")) or 0) > 0]
    losers = [trade for trade in trades if (_float(trade.get("gross_pnl")) or 0) < 0]
    examples: list[dict[str, Any]] = []
    if winners:
        examples.append(
            {
                "kind": "win",
                "fallback": False,
                "trade": max(winners, key=lambda t: _float(t.get("gross_pnl")) or 0),
            }
        )
    elif losers:
        examples.append(
            {
                "kind": "win",
                "fallback": True,
                "trade": min(losers, key=lambda t: _float(t.get("gross_pnl")) or 0),
            }
        )
    if losers:
        examples.append(
            {
                "kind": "loss",
                "fallback": False,
                "trade": min(losers, key=lambda t: _float(t.get("gross_pnl")) or 0),
            }
        )
    elif winners:
        examples.append(
            {
                "kind": "loss",
                "fallback": True,
                "trade": max(winners, key=lambda t: _float(t.get("gross_pnl")) or 0),
            }
        )
    return examples


def _feature_names(program: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for feature in _rows(program.get("features")):
        name = _text(feature.get("name"))
        if name:
            names.append(name)
    return names


def _strategy_provenance(metric: dict[str, Any], source: dict[str, Any]) -> dict[str, str]:
    membership = _text(metric.get("membership"))
    if membership == "MC5":
        why_chosen = (
            "Chosen for MC5 because this revision appeared in at least two "
            "validation top-five lists, then carried into VF9 and the "
            "pre-OOS forward-eligible cohorts."
        )
    elif membership == "FO4":
        why_chosen = (
            "Chosen for VF9 because it was on the validation frontier, then "
            "kept in FO4 as frontier-only diagnostic evidence outside the "
            "forward-eligible MC5 set."
        )
    else:
        why_chosen = (
            "Chosen by the sealed cohort-selection artifact before OOS was "
            "opened, using the validation evidence available at selection time."
        )

    evidence_start = _text(source.get("evidence_start"))
    evidence_end = _text(source.get("evidence_end_exclusive"))
    outcome_end = _text(source.get("outcome_end_exclusive"))
    if evidence_start and evidence_end and outcome_end:
        oos_window = (
            f" one-time OOS window {evidence_start} to {evidence_end} "
            f"with outcomes through {outcome_end}"
        )
    else:
        oos_window = " one-time OOS window"

    return {
        "why_chosen": why_chosen,
        "found_by": (
            "Found by the swing-ranking-v1 deterministic discovery grammar and "
            "study bundle, which generated readable monthly/weekly context, "
            "daily trigger, stop, and target combinations."
        ),
        "tested_by": (
            "Tested through sealed historical studies: discovery and validation "
            f"selected the revision before OOS, then the{oos_window} measured "
            "its trades without changing the rule."
        ),
    }


def _indicator_frame(frame: Any, names: list[str]) -> dict[str, Any]:
    indicators: dict[str, Any] = {}
    for name in names:
        if name == "daily_ema5":
            indicators[name] = frame["close"].ewm(span=5, adjust=False).mean()
        elif name == "daily_sma10":
            indicators[name] = frame["close"].rolling(10).mean()
        elif name == "daily_rolling_low10":
            indicators[name] = frame["low"].rolling(10).min()
        elif name == "daily_rolling_low20":
            indicators[name] = frame["low"].rolling(20).min()
        elif name == "daily_rolling_high20":
            indicators[name] = frame["high"].rolling(20).max()
    return indicators


def _ohlcv_window(
    repo_root: Path,
    trade: dict[str, Any],
    indicator_names: list[str],
    *,
    pad_sessions: int = 8,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Read a compact OHLCV chart window from the local parquet cache.

    Missing pandas, missing parquet, absent sessions, or unreadable data simply
    produce an empty candle list; the report still renders the trade stats.
    """
    symbol = _text(trade.get("symbol"))
    if not symbol:
        return [], []
    path = Path(repo_root) / "cache" / "study_frames" / f"{symbol.upper()}.parquet"
    if not path.is_file():
        return [], []
    try:
        import pandas as pd
        from pyarrow.lib import ArrowException

    except ImportError:
        return [], []
    try:
        frame = pd.read_parquet(path)
    except (OSError, ValueError, ArrowException):
        return [], []
    if frame.empty:
        return [], []

    try:
        entry = pd.Timestamp(_text(trade.get("entry_session")))
        exit_ = pd.Timestamp(_text(trade.get("exit_session")))
    except (TypeError, ValueError):
        return [], []

    index = list(frame.index)
    entry_positions = [i for i, value in enumerate(index) if value >= entry]
    exit_positions = [i for i, value in enumerate(index) if value <= exit_]
    if not entry_positions or not exit_positions:
        return [], []
    start = max(0, entry_positions[0] - pad_sessions)
    end = min(len(frame), exit_positions[-1] + pad_sessions + 1)
    chart_frame = frame.iloc[start:end].copy()
    indicators = _indicator_frame(frame.iloc[:end].copy(), indicator_names)
    plotted = [name for name in indicator_names if name in indicators]

    candles: list[dict[str, Any]] = []
    for session, row in chart_frame.iterrows():
        candle = {
            "session": session.date().isoformat(),
            "open": _format_decimal(row.open),
            "high": _format_decimal(row.high),
            "low": _format_decimal(row.low),
            "close": _format_decimal(row.close),
            "volume": int(row.volume),
            "indicators": {},
        }
        offset = frame.index.get_loc(session)
        for name in plotted:
            value = indicators[name].iloc[offset]
            if getattr(value, "__class__", None).__name__ == "NAType":
                continue
            if pd.isna(value):
                continue
            candle["indicators"][name] = _format_decimal(value)
        candles.append(candle)
    return candles, plotted


def _signal_facts(candidate: dict[str, Any]) -> dict[str, str]:
    facts: dict[str, str] = {}
    for name, fact in (candidate.get("signal_facts") or {}).items():
        if isinstance(fact, dict):
            facts[str(name)] = _text(fact.get("value"))
    return facts


def _trade_payload(
    repo_root: Path,
    example: dict[str, Any],
    candidate: dict[str, Any],
    geometry: dict[str, Any],
    indicator_names: list[str],
) -> dict[str, Any]:
    trade = example["trade"]
    candles, plotted = _ohlcv_window(repo_root, trade, indicator_names)
    return {
        "kind": example["kind"],
        "fallback": example["fallback"],
        "trade": {
            "trade_identity": _text(trade.get("trade_identity")),
            "candidate_identity": _text(trade.get("candidate_identity")),
            "symbol": _text(trade.get("symbol")),
            "permanent_id": _text(trade.get("permanent_id")),
            "entry_session": _text(trade.get("entry_session")),
            "exit_session": _text(trade.get("exit_session")),
            "entry_price": _text(trade.get("entry_price")),
            "exit_price": _text(trade.get("exit_price")),
            "quantity": _text(trade.get("quantity")),
            "gross_pnl": _text(trade.get("gross_pnl")),
            "exit_reason": _text(trade.get("exit_reason")),
        },
        "geometry": {
            "initial_stop_price": _text(geometry.get("initial_stop_price")),
            "target_price": _text(geometry.get("target_price")),
            "planned_hold_sessions": geometry.get("planned_hold_sessions"),
        },
        "signal": {
            "signal_session": _text(candidate.get("signal_session")),
            "signal_close": _text(candidate.get("signal_close")),
            "average_dollar_volume": _text(candidate.get("average_dollar_volume")),
            "priority_value": _text(candidate.get("priority_value")),
            "facts": _signal_facts(candidate),
        },
        "candles": candles,
        "plotted_indicators": plotted,
    }


def _strategy_report(
    repo_root: Path,
    window_root: Path,
    metric: dict[str, Any],
    trades: list[dict[str, Any]],
    candidates: dict[str, dict[str, Any]],
    source: dict[str, Any],
) -> dict[str, Any]:
    identity = _text(metric.get("strategy_revision_identity"))
    strategy_file = _read_strategy(window_root, identity)
    program = _strategy_program(strategy_file)
    feature_names = _feature_names(program)
    price_indicators = [name for name in feature_names if name in _PRICE_INDICATORS]
    geometries = _geometry_by_candidate(strategy_file)
    examples: list[dict[str, Any]] = []
    for selected in _selected_trade_examples(trades):
        trade = selected["trade"]
        candidate_identity = _text(trade.get("candidate_identity"))
        candidate = candidates.get(candidate_identity, {})
        examples.append(
            _trade_payload(
                repo_root,
                selected,
                candidate,
                geometries.get(candidate_identity, {}),
                price_indicators,
            )
        )
    wins = sum(1 for trade in trades if (_float(trade.get("gross_pnl")) or 0) > 0)
    losses = sum(1 for trade in trades if (_float(trade.get("gross_pnl")) or 0) < 0)
    flats = max(0, len(trades) - wins - losses)
    return {
        "strategy_revision_identity": identity,
        "strategy_name": _text(metric.get("strategy_name")),
        "display_name": _text(metric.get("display_name")),
        "membership": _text(metric.get("membership")),
        "description": " ".join(_strategy_rules(strategy_file)[:2]),
        "provenance": _strategy_provenance(metric, source),
        "rules": _strategy_rules(strategy_file),
        "features": feature_names,
        "stats": {
            "closed_trades": metric.get("closed_trades"),
            "wins": wins,
            "losses": losses,
            "flats": flats,
            "gross_profit": _text(metric.get("gross_profit")),
            "gross_return": _text(metric.get("gross_return")),
            "maximum_drawdown": _text(metric.get("maximum_drawdown")),
            "maximum_drawdown_dollars": _text(metric.get("maximum_drawdown_dollars")),
            "profit_drawdown": _text(metric.get("profit_drawdown")),
            "turnover": _text(metric.get("turnover")),
            "exposure_mean": _text(metric.get("exposure_mean")),
            "exposure_maximum": _text(metric.get("exposure_maximum")),
            "break_even_proportional_cost": metric.get("break_even_proportional_cost"),
        },
        "examples": examples,
    }


def project_report(runs_root: Path, repo_root: Path) -> dict[str, Any]:
    """Readable OOS report payload for the dashboard and standalone HTML."""
    comparison = cohort_comparison(runs_root)
    root = Path(runs_root) / BACKTEST_ROOT_NAME / "oos-v1"
    if not comparison.get("present") or not root.exists():
        return {"present": False}

    candidates = _oos_candidates(root)
    trades_by_strategy = _oos_trades_by_strategy(root)
    strategy_rows = sorted(
        comparison["strategy_metrics"],
        key=lambda row: _text(row.get("display_name")) or _text(row.get("strategy_name")),
    )
    source = comparison.get("source") if isinstance(comparison.get("source"), dict) else {}
    strategy_reports = {
        _text(row.get("strategy_revision_identity")): _strategy_report(
            repo_root,
            root,
            row,
            trades_by_strategy.get(_text(row.get("strategy_revision_identity")), []),
            candidates,
            source,
        )
        for row in strategy_rows
    }

    cohorts: list[dict[str, Any]] = []
    for metric in sorted(
        comparison["cohort_metrics"],
        key=lambda row: COHORT_ORDER.index(_text(row.get("cohort")))
        if _text(row.get("cohort")) in COHORT_ORDER
        else 99,
    ):
        cohort = _text(metric.get("cohort"))
        if cohort == "VF9":
            members = list(strategy_reports.values())
        else:
            members = [
                report
                for report in strategy_reports.values()
                if report["membership"] == cohort
            ]
        cohorts.append(
            {
                "cohort": cohort,
                "description": _COHORT_DESCRIPTIONS.get(cohort, ""),
                "metrics": metric,
                "strategies": members,
            }
        )

    positive = sum(1 for row in strategy_rows if (_float(row.get("gross_profit")) or 0) > 0)
    total = len(strategy_rows)
    return {
        "present": True,
        "title": "Swing Ranking V1 Project Report",
        "goal": (
            "Build a daily-data swing-trading engine that finds and paper-trades "
            "3-21 session moves in liquid US stocks using readable multi-timeframe "
            "setups, fixed entry risk, sealed historical studies, and a forward "
            "paper book as the final evidence."
        ),
        "conclusion": [
            "The sealed one-time OOS opening was weak: VF9, MC5, and FO4 all finished negative.",
            f"Only {positive} of {total} independent $100,000 strategy books were profitable.",
            "FO4 lost less than MC5, but it remains diagnostic because forward eligibility was fixed before OOS.",
            "The practical conclusion is to run the approved forward paper cohorts unchanged and judge them only after the chartered trade-count checkpoints.",
        ],
        "source": {
            "evidence_start": _text(source.get("evidence_start")),
            "evidence_end_exclusive": _text(source.get("evidence_end_exclusive")),
            "outcome_end_exclusive": _text(source.get("outcome_end_exclusive")),
            "oos_artifact_identity": _text(source.get("oos_artifact_identity")),
            "cohort_selection_identity": _text(source.get("cohort_selection_identity")),
            "analysis_identity": _text(comparison.get("analysis_identity")),
        },
        "cohort_equity": comparison["cohort_equity"],
        "cohorts": cohorts,
        "limitations": _rows((read_json(root / "manifest.json") or {}).get("limitations")),
        "integrity": comparison["integrity"],
    }


def seal(runs_root: Path) -> dict[str, Any]:
    """The cross-artifact OOS seal that binds the forward run to its evidence."""
    root = Path(runs_root) / BACKTEST_ROOT_NAME / SEAL_DIR
    record = read_json(root / "seal.json") or {}
    return {
        "present": bool(record),
        "status": _text(record.get("status")),
        "seal_identity": _text(record.get("seal_identity")),
        "selection_identity": _text(record.get("selection_identity")),
        "cohort_analysis_identity": _text(record.get("cohort_analysis_identity")),
        "oos_artifact_identity": _text(record.get("oos_artifact_identity")),
        "forward_eligibility": _text(record.get("forward_eligibility")),
        "forward_eligible_cohorts": record.get("forward_eligible_cohorts") or [],
        "sealed_on": _text(record.get("sealed_on")),
    }


def _iter_present(runs_root: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    for window in BACKTEST_WINDOWS:
        yield window, verify_manifest(_backtest_root(runs_root, window))
    yield COHORT_COMPARISON_DIR, verify_manifest(
        Path(runs_root) / BACKTEST_ROOT_NAME / COHORT_COMPARISON_DIR
    )
    yield FORWARD_RUN_ID, verify_manifest(_forward_root(runs_root))


def overview(runs_root: Path) -> dict[str, Any]:
    """The landing payload: forward status first, then backtest evidence."""
    integrity = dict(_iter_present(runs_root))
    return {
        "forward": forward_overview(runs_root),
        "backtests": backtest_windows(runs_root),
        "cohort_comparison_present": (
            Path(runs_root) / BACKTEST_ROOT_NAME / COHORT_COMPARISON_DIR / "manifest.json"
        ).is_file(),
        "seal": seal(runs_root),
        "integrity": integrity,
        # Only real hash divergence, never the expected curated-subset gaps.
        "degraded": sorted(
            name for name, report in integrity.items() if report["status"] == "degraded"
        ),
        "partial": sorted(
            name for name, report in integrity.items() if report["status"] == "partial"
        ),
    }
