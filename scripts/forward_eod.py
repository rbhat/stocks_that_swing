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
from sts.forward.ledger import Ledger, LedgerPaths
from sts.forward.pipeline import (
    detect_missed_sessions,
    generate_signals,
    run_upkeep,
)

logger = logging.getLogger("forward_eod")

STUDY_ROSTER_YAML = ROOT / "configs" / "study_roster.yaml"
EARNINGS_PATH = ROOT / "cache" / "catalysts" / "earnings.json"
EARNINGS_STALE_DAYS = 3
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


def _notification_messages(ledger: Ledger, asof: dt.date) -> list[str]:
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
    return messages


def _send_signal_notifications(
    ledger: Ledger,
    asof: dt.date,
    notify,
) -> None:
    if asof in ledger.processed_notification_dates():
        return
    for message in _notification_messages(ledger, asof):
        if notify(message) is False:
            raise RuntimeError("signal notification delivery failed")
    ledger.append_signal(
        {
            "kind": "notifications_done",
            "book": "shared",
            "entry_id": None,
            "signal_date": asof.isoformat(),
            "date": asof.isoformat(),
        }
    )


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
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    do_fetch = not (args.dry_run or args.no_fetch)
    do_discord = not (args.dry_run or args.no_discord)
    do_sync = not (args.dry_run or args.no_sync)

    t_start = time.time()

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
            _send_signal_notifications(ledger, asof, _alert)
        else:
            # [1/6] fetch
            if do_fetch:
                store = StudyStore()
                _incremental_fetch(store, _roster_symbols(), asof)
            else:
                print("[1/6] fetch: skipped (--dry-run/--no-fetch)")

            # [2/6] load prices
            print("[2/6] loading study store...")
            t0 = time.time()
            prices = StudyStore().load_all()
            print(
                f"[2/6] loaded {len(prices)} symbols in "
                f"{_fmt_eta(time.time() - t0)}"
            )

            # [3/6] upkeep
            print("[3/6] run_upkeep...")
            t0 = time.time()
            closed_rows = run_upkeep(ledger, prices, asof)
            for row in closed_rows:
                _alert(alerts.exit_alert(row))
            print(
                f"[3/6] upkeep done: {len(closed_rows)} closed in "
                f"{_fmt_eta(time.time() - t0)}"
            )

            # [4/6] signals
            print("[4/6] generate_signals...")
            t0 = time.time()
            catalyst = CatalystCalendar.load()
            result = generate_signals(ledger, prices, asof, catalyst)
            print(
                f"[4/6] signals done: {len(result['queued'])} queued, "
                f"{len(result['skipped'])} skipped in "
                f"{_fmt_eta(time.time() - t0)}"
            )

            # [5/6] missed sessions + signal notifications
            print("[5/6] detect_missed_sessions + notifications...")
            missed = detect_missed_sessions(ledger, asof)
            if missed:
                dates_str = ", ".join(d.isoformat() for d in missed)
                _alert(f"WARNING: missed upkeep sessions detected: {dates_str}")
            _send_signal_notifications(ledger, asof, _alert)
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
