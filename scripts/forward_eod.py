"""Nightly EOD job: fetch -> upkeep -> signals -> missed-session check -> sync.

WHY: glues the merged forward-paper modules (sts.forward.pipeline/ledger/
alerts, sts.data.study_store/fetch, sts.catalyst) into the single script a
cron job runs once per completed session. Every stage is resumable: the
ledger IS the state (`upkeep_done`, `signals_done`, and
`notifications_done`), so a killed or re-run job resumes the incomplete
stage without changing the deterministic signal walk.

SEQUENCE (see .superpowers/sdd/task-7-brief.md):
  1. env.load(); resolve asof; if all three stage records exist, skip stages
     2-5. If signals are done but notifications are not, rebuild the nightly
     signal notifications from the ledger.
  2. Incremental fetch of the study roster (skipped by --no-fetch/--dry-run).
  3. run_upkeep -> Discord exit_alert per closed row.
  4. generate_signals -> durable `signals_done` after both book walks.
  5. detect_missed_sessions, then send ledger-rebuilt candidate/no-candidate
     and book-status notifications; append `notifications_done` afterward.
  6. sync.run_daily_sync() on every invocation, including failed retries.

Exit code 0 on success, 1 on any stage exception (traceback logged; a
best-effort Discord failure alert is attempted before exiting).
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml

from sts import calendar, env
from sts.catalyst import CatalystCalendar, refresh_earnings
from sts.data.fetch import fetch_daily
from sts.data.study_store import StudyStore
from sts.forward import alerts
from sts.forward.freeze import LEGACY_ENTRY_FREEZE_WALL, legacy_entries_frozen
from sts.forward.ledger import Ledger, LedgerPaths
from sts.forward.pipeline import (
    classify_signal_outcome,
    detect_missed_sessions,
    generate_signals,
    run_upkeep,
    summarize_price_freshness,
)

logger = logging.getLogger("forward_eod")

STUDY_ROSTER_YAML = ROOT / "configs" / "study_roster.yaml"
EARNINGS_PATH = ROOT / "cache" / "catalysts" / "earnings.json"
EARNINGS_STALE_DAYS = 3
DEFAULT_ZERO_STREAK_WARNING = 5
OHLC = ["open", "high", "low", "close"]


def _fmt_eta(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


def _roster_symbols() -> list[str]:
    if not STUDY_ROSTER_YAML.exists():
        logger.warning("forward_eod: %s not found, roster is empty", STUDY_ROSTER_YAML)
        return []
    data = yaml.safe_load(STUDY_ROSTER_YAML.read_text()) or {}
    return list(data.get("symbols", []))


def _clean(df):
    ohlc = df[OHLC]
    return df[~(ohlc.isna().any(axis=1) | (ohlc <= 0).any(axis=1))]


def _incremental_fetch(store: StudyStore, symbols: list[str], asof: dt.date) -> None:
    """Top up every roster symbol whose cached frame lags `asof`. Budgeted,
    resumable (a killed run just leaves the store at whatever it reached;
    re-running recomputes what's still stale), per-symbol failures logged
    and skipped rather than fatal."""
    stale = [s for s in symbols if (store.last_date(s) or dt.date.min) < asof]
    print(f"[1/6] fetch: {len(symbols)} symbols, {len(stale)} stale, ETA pending...")
    t0 = time.time()
    ok = failed = 0
    for i, sym in enumerate(stale, 1):
        last = store.last_date(sym)
        start = last + dt.timedelta(days=1) if last else None
        try:
            new = _clean(fetch_daily(sym, start=start))
            if new.empty:
                continue
            existing = store.load(sym)
            merged = new if existing is None else _clean(existing).combine_first(new)
            store.write(sym, merged.sort_index())
            ok += 1
        except Exception as e:  # noqa: BLE001 — fetch or quality-gate failure -> log & continue
            logger.warning("forward_eod: fetch failed for %s: %s", sym, e)
            failed += 1
        elapsed = time.time() - t0
        eta = (elapsed / i) * (len(stale) - i) if i else 0.0
        print(f"  [{i}/{len(stale)}] {sym:<6} elapsed {_fmt_eta(elapsed)} · ETA {_fmt_eta(eta)}")
    print(f"[1/6] fetch done: {ok} updated, {failed} failed, {len(symbols) - len(stale)} already fresh")

    _refresh_earnings_if_stale(symbols)


def _refresh_earnings_if_stale(symbols: list[str]) -> None:
    if not EARNINGS_PATH.exists():
        logger.warning(
            "forward_eod: %s missing — earnings refresh is manual (run "
            "sts.catalyst.refresh_earnings directly)", EARNINGS_PATH,
        )
        return
    age_days = (dt.datetime.now(dt.UTC)
                - dt.datetime.fromtimestamp(EARNINGS_PATH.stat().st_mtime, tz=dt.UTC)).days
    if age_days <= EARNINGS_STALE_DAYS:
        return
    print(f"  earnings cache is {age_days}d old (>{EARNINGS_STALE_DAYS}d) — refreshing")
    refresh_earnings(symbols, path=EARNINGS_PATH)


def _already_done(ledger: Ledger, asof: dt.date) -> bool:
    return (
        asof in ledger.processed_upkeep_dates()
        and asof in ledger.processed_signal_dates()
        and asof in ledger.processed_notification_dates()
    )


def _signals_done_record(ledger: Ledger, asof: dt.date) -> dict | None:
    return next(
        (
            rec
            for rec in ledger.signals(asof)
            if rec.get("kind") == "signals_done"
        ),
        None,
    )


def _record_legacy_freeze(
    ledger: Ledger,
    asof: dt.date,
    *,
    market_data: dict,
    runtime_seconds: dict[str, float],
) -> dict:
    """Durably complete the signal stage without running a legacy detector."""
    family_counts = {
        family: {
            "detected": 0,
            "selected": 0,
            "missing_signal_bar": 0,
            "stale_signal_bar": 0,
            "invalid_geometry": 0,
            "embargoed": 0,
            "queued": 0,
            "skipped_by_reason": {"legacy_entry_freeze": 1},
        }
        for family in ("h2", "h1")
    }
    summary = {
        "families": family_counts,
        "market_data": market_data,
        "runtime_seconds": {**runtime_seconds, "signals": 0.0},
        "legacy_entry_freeze": {
            "active": True,
            "wall": LEGACY_ENTRY_FREEZE_WALL.isoformat(),
        },
    }
    ledger.append_signal(
        {
            "kind": "signals_done",
            "book": "shared",
            "entry_id": None,
            "signal_date": asof.isoformat(),
            "date": asof.isoformat(),
            "summary": summary,
        }
    )
    return {"queued": [], "skipped": []}


def _previous_session(value: dt.date) -> dt.date | None:
    sessions = calendar.sessions_between(value - dt.timedelta(days=14), value)
    prior = [stamp.date() for stamp in sessions if stamp.date() < value]
    return prior[-1] if prior else None


def _consecutive_selected_zero_sessions(ledger: Ledger, asof: dt.date) -> int:
    """Count completed, adjacent sessions ending at ``asof`` with no selection."""
    summaries = {
        dt.date.fromisoformat(str(rec["signal_date"])): rec.get("summary", {})
        for rec in ledger.signals()
        if rec.get("kind") == "signals_done"
    }
    streak = 0
    current: dt.date | None = asof
    while current is not None:
        summary = summaries.get(current)
        families = summary.get("families") if summary else None
        if not families:
            break
        if sum(family.get("selected", 0) for family in families.values()) != 0:
            break
        streak += 1
        current = _previous_session(current)
    return streak


def _nightly_summary(
    ledger: Ledger,
    asof: dt.date,
    *,
    zero_streak_warning: int,
    notification_seconds: float = 0.0,
) -> dict:
    signal_record = _signals_done_record(ledger, asof)
    signal_summary = dict(signal_record.get("summary", {})) if signal_record else {}
    families = signal_summary.get("families", {})
    runtimes = dict(signal_summary.get("runtime_seconds", {}))
    runtimes["notifications"] = round(notification_seconds, 6)
    zero_streak = _consecutive_selected_zero_sessions(ledger, asof)
    warning = zero_streak_warning > 0 and zero_streak >= zero_streak_warning
    complete = signal_record is not None
    return {
        **signal_summary,
        "asof": asof.isoformat(),
        "families": families,
        "signal_outcome": (
            "legacy_entry_frozen"
            if signal_summary.get("legacy_entry_freeze", {}).get("active")
            else classify_signal_outcome(families, complete=complete)
        ),
        "stage_completion": {
            "upkeep_done": asof in ledger.processed_upkeep_dates(),
            "signals_done": complete,
            # This summary is appended as the notifications_done record only
            # after every notification below succeeds.
            "notifications_done": True,
        },
        "runtime_seconds": runtimes,
        "consecutive_selected_zero_sessions": zero_streak,
        "zero_streak_warning_threshold": zero_streak_warning,
        "health_warning": (
            f"selected=0 for {zero_streak} consecutive completed sessions"
            if warning
            else None
        ),
    }


def _format_nightly_summary(summary: dict) -> str:
    data_counts = summary.get("market_data", {}).get("counts", {})
    families = summary.get("families", {})
    family_parts = []
    for family in ("h2", "h1"):
        counts = families.get(family, {})
        skips = sum(counts.get("skipped_by_reason", {}).values())
        family_parts.append(
            f"{family.upper()} detected={counts.get('detected', 0)} "
            f"selected={counts.get('selected', 0)} "
            f"queued={counts.get('queued', 0)} "
            f"embargoed={counts.get('embargoed', 0)} skips={skips}"
        )
    stages = summary["stage_completion"]
    runtimes = ", ".join(
        f"{stage}={seconds:.3f}s"
        for stage, seconds in summary.get("runtime_seconds", {}).items()
    )
    lines = [
        f"Nightly status {summary['asof']}: {summary['signal_outcome']}",
        (
            "Data "
            f"fresh={data_counts.get('fresh', 0)} "
            f"stale={data_counts.get('stale', 0)} "
            f"missing={data_counts.get('missing', 0)}"
        ),
        *family_parts,
        (
            "Stages "
            f"upkeep_done={stages['upkeep_done']} "
            f"signals_done={stages['signals_done']} "
            f"notifications_done={stages['notifications_done']}"
        ),
        f"Runtime {runtimes or 'unavailable'}",
    ]
    stale = summary.get("market_data", {}).get("stale_symbols", [])
    missing = summary.get("market_data", {}).get("missing_symbols", [])
    if stale:
        lines.append(
            "Stale symbols "
            + ", ".join(f"{item['symbol']}({item['last_date']})" for item in stale)
        )
    if missing:
        lines.append("Missing symbols " + ", ".join(missing))
    if summary.get("health_warning"):
        lines.append("WARNING " + summary["health_warning"])
    return "\n".join(lines)


def _notification_messages(
    ledger: Ledger,
    asof: dt.date,
    nightly_summary: dict | None = None,
) -> list[str]:
    """Rebuild the complete nightly signal notification set from durable
    journals. A crash after any send but before `notifications_done` causes
    the whole set to be sent again, providing at-least-once delivery."""
    queued = [
        rec
        for rec in ledger.signals(asof)
        if rec.get("kind") == "candidate"
    ]
    messages = [alerts.entry_alert(cand) for cand in queued]
    if not queued:
        messages.append(f"No candidates for {asof.isoformat()}")

    snapshots = [
        snap
        for book in ("shared", "h1solo")
        for snap in ledger.equity_series(book)
        if str(snap.get("date")) == asof.isoformat()
    ]
    if snapshots:
        messages.append(alerts.book_status(snapshots))
    if nightly_summary is not None:
        messages.append(_format_nightly_summary(nightly_summary))
    return messages


def _send_signal_notifications(
    ledger: Ledger,
    asof: dt.date,
    notify,
    *,
    zero_streak_warning: int = DEFAULT_ZERO_STREAK_WARNING,
) -> None:
    if asof in ledger.processed_notification_dates():
        return
    started = time.perf_counter()
    summary = _nightly_summary(
        ledger,
        asof,
        zero_streak_warning=zero_streak_warning,
    )
    for message in _notification_messages(ledger, asof, summary):
        if notify(message) is False:
            raise RuntimeError("signal notification delivery failed")
    summary = _nightly_summary(
        ledger,
        asof,
        zero_streak_warning=zero_streak_warning,
        notification_seconds=time.perf_counter() - started,
    )
    ledger.append_signal(
        {
            "kind": "notifications_done",
            "book": "shared",
            "entry_id": None,
            "signal_date": asof.isoformat(),
            "date": asof.isoformat(),
            "summary": summary,
        }
    )
    print(_format_nightly_summary(summary))


def _run_sync(do_sync: bool) -> None:
    """Stage 6: ImportError-guarded sync hook. Runs on both the normal path
    and the already-done no-op path (sync is idempotent/merge-only)."""
    if not do_sync:
        print("[6/6] sync: skipped (--dry-run/--no-sync)")
        return
    print("[6/6] sync...")
    try:
        from sts.forward import sync  # TODO(Task 9): module doesn't exist yet
    except ImportError:
        logger.info("forward_eod: sts.forward.sync not available yet (Task 9) — skipping")
        print("[6/6] sync: skipped (module not yet implemented)")
        return
    sync.run_daily_sync()
    print("[6/6] sync done")


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--asof", default=None, help="YYYY-MM-DD; default last_completed_session()")
    parser.add_argument("--dry-run", action="store_true", help="no Discord, no sync, no fetch — cached bars only")
    parser.add_argument("--no-sync", action="store_true")
    parser.add_argument("--no-discord", action="store_true")
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--ledger-root", default="ledger")
    parser.add_argument(
        "--zero-streak-warning",
        type=int,
        default=DEFAULT_ZERO_STREAK_WARNING,
        metavar="N",
        help=(
            "warn after N adjacent completed sessions with selected=0 "
            f"(default: {DEFAULT_ZERO_STREAK_WARNING}; 0 disables)"
        ),
    )
    args = parser.parse_args(argv)
    if args.zero_streak_warning < 0:
        parser.error("--zero-streak-warning must be >= 0")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    do_fetch = not (args.dry_run or args.no_fetch)
    do_discord = not (args.dry_run or args.no_discord)
    do_sync = not (args.dry_run or args.no_sync)

    t_start = time.time()
    stage_runtimes: dict[str, float] = {}

    def _alert(text: str) -> bool:
        if do_discord:
            return alerts.send(text)
        logger.info("forward_eod (alert suppressed): %s", text)
        return True

    rc = 0
    try:
        env.load()
        asof = dt.date.fromisoformat(args.asof) if args.asof else calendar.last_completed_session()

        ledger = Ledger(LedgerPaths(root=Path(args.ledger_root)))

        if _already_done(ledger, asof):
            print(
                f"forward_eod: {asof} already processed (upkeep/signals/"
                "notifications done) — skipping stages 1-5; running sync only"
            )
        elif (
            asof in ledger.processed_upkeep_dates()
            and asof in ledger.processed_signal_dates()
        ):
            # No market data is needed to recover the notification stage:
            # candidates and same-date book snapshots are durable.
            print(
                f"forward_eod: {asof} signals complete; resuming notifications"
            )
            missed = detect_missed_sessions(ledger, asof)
            if missed:
                dates_str = ", ".join(d.isoformat() for d in missed)
                _alert(f"WARNING: missed upkeep sessions detected: {dates_str}")
            _send_signal_notifications(
                ledger,
                asof,
                _alert,
                zero_streak_warning=args.zero_streak_warning,
            )
        else:
            # [1/6] fetch
            roster = _roster_symbols()
            t0 = time.perf_counter()
            if do_fetch:
                store = StudyStore()
                _incremental_fetch(store, roster, asof)
            else:
                print("[1/6] fetch: skipped (--dry-run/--no-fetch)")
            stage_runtimes["fetch"] = round(time.perf_counter() - t0, 6)

            # [2/6] load prices
            print("[2/6] loading study store...")
            t0 = time.perf_counter()
            prices = StudyStore().load_all()
            stage_runtimes["load"] = round(time.perf_counter() - t0, 6)
            print(
                f"[2/6] loaded {len(prices)} symbols in "
                f"{_fmt_eta(stage_runtimes['load'])}"
            )
            market_data = summarize_price_freshness(prices, roster, asof)

            # [3/6] upkeep
            print("[3/6] run_upkeep...")
            t0 = time.perf_counter()
            closed_rows = run_upkeep(ledger, prices, asof)
            stage_runtimes["upkeep"] = round(time.perf_counter() - t0, 6)
            for row in closed_rows:
                _alert(alerts.exit_alert(row))
            print(
                f"[3/6] upkeep done: {len(closed_rows)} closed in "
                f"{_fmt_eta(stage_runtimes['upkeep'])}"
            )

            # [4/6] signals
            if legacy_entries_frozen(asof):
                print(
                    "[4/6] legacy entry freeze active "
                    f"(wall {LEGACY_ENTRY_FREEZE_WALL}) — detectors skipped"
                )
                result = _record_legacy_freeze(
                    ledger,
                    asof,
                    market_data=market_data,
                    runtime_seconds=stage_runtimes,
                )
            else:
                print("[4/6] generate_signals...")
                catalyst = CatalystCalendar.load()
                result = generate_signals(
                    ledger,
                    prices,
                    asof,
                    catalyst,
                    summary_context={
                        "market_data": market_data,
                        "runtime_seconds": stage_runtimes,
                    },
                )
            signal_record = _signals_done_record(ledger, asof)
            signal_runtime = (
                signal_record.get("summary", {})
                .get("runtime_seconds", {})
                .get("signals", 0.0)
                if signal_record
                else 0.0
            )
            print(
                f"[4/6] signals done: {len(result['queued'])} queued, "
                f"{len(result['skipped'])} skipped in "
                f"{_fmt_eta(signal_runtime)}"
            )

            # [5/6] missed sessions + signal notifications
            print("[5/6] detect_missed_sessions + notifications...")
            missed = detect_missed_sessions(ledger, asof)
            if missed:
                dates_str = ", ".join(d.isoformat() for d in missed)
                _alert(f"WARNING: missed upkeep sessions detected: {dates_str}")
            _send_signal_notifications(
                ledger,
                asof,
                _alert,
                zero_streak_warning=args.zero_streak_warning,
            )
            print(f"[5/6] {len(missed)} missed session(s); notifications done")

        print(f"forward_eod: {asof} complete in {_fmt_eta(time.time() - t_start)}")

    except Exception:  # noqa: BLE001 — top-level job boundary
        logger.error("forward_eod: fatal error\n%s", traceback.format_exc())
        try:
            if not args.dry_run and not args.no_discord:
                alerts.send(f"forward_eod FAILED: {traceback.format_exc()[-500:]}")
        except Exception:
            logger.exception("forward_eod: failure alert raised unexpectedly")
        rc = 1
    finally:
        # Merge-only sync is useful after both successful stages and partial
        # failures, and must never be stranded behind an early return.
        try:
            _run_sync(do_sync)
        except Exception:  # noqa: BLE001  # pragma: no cover
            logger.error("forward_eod: unexpected sync wrapper failure\n%s", traceback.format_exc())

    return rc


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
