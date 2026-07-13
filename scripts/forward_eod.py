"""Nightly EOD job: fetch -> upkeep -> signals -> missed-session check -> sync.

WHY: glues the merged forward-paper modules (sts.forward.pipeline/ledger/
alerts, sts.data.study_store/fetch, sts.catalyst) into the single script a
cron job runs once per completed session. Every stage is resumable: the
ledger IS the state (upkeep_done + signals per asof), so a killed or re-run
job for the same `asof` is a safe no-op rather than a double-fire.

SEQUENCE (see .superpowers/sdd/task-7-brief.md):
  1. env.load(); resolve asof; if upkeep_done AND signals already recorded
     for asof, skip stages 2-5 but still run sync (stage 6) then exit 0 —
     a crash between signal gen and sync must not strand the date unsynced.
  2. Incremental fetch of the study roster (skipped by --no-fetch/--dry-run).
  3. run_upkeep -> Discord exit_alert per closed row.
  4. generate_signals -> Discord entry_alert per queued candidate + a
     book_status line; explicit "no candidates" message when the queue is
     empty (silence must be distinguishable from outage).
  5. detect_missed_sessions -> Discord warning if any gap found.
  6. sync.run_daily_sync() (Task 9) — ImportError-guarded so this script
     runs standalone until Task 9 lands the sync module.

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

import yaml  # noqa: E402

from sts import calendar, env  # noqa: E402
from sts.catalyst import CatalystCalendar, refresh_earnings  # noqa: E402
from sts.data.fetch import fetch_daily  # noqa: E402
from sts.data.study_store import StudyStore  # noqa: E402
from sts.forward import alerts  # noqa: E402
from sts.forward.ledger import Ledger, LedgerPaths  # noqa: E402
from sts.forward.pipeline import (  # noqa: E402
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
    age_days = (dt.datetime.now(dt.timezone.utc)
                - dt.datetime.fromtimestamp(EARNINGS_PATH.stat().st_mtime, tz=dt.timezone.utc)).days
    if age_days <= EARNINGS_STALE_DAYS:
        return
    print(f"  earnings cache is {age_days}d old (>{EARNINGS_STALE_DAYS}d) — refreshing")
    refresh_earnings(symbols, path=EARNINGS_PATH)


def _already_done(ledger: Ledger, asof: dt.date) -> bool:
    return asof in ledger.processed_upkeep_dates() and bool(ledger.signals(asof))


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

    def _alert(text: str) -> None:
        if do_discord:
            alerts.send(text)
        else:
            logger.info("forward_eod (alert suppressed): %s", text)

    try:
        env.load()
        asof = dt.date.fromisoformat(args.asof) if args.asof else calendar.last_completed_session()

        ledger = Ledger(LedgerPaths(root=Path(args.ledger_root)))

        if _already_done(ledger, asof):
            # Stages 2-5 are ledger-idempotent and already recorded, but a
            # crash between signal gen and sync would leave the date marked
            # done with sync never run — so a no-op re-run still attempts
            # the sync stage (idempotent/merge-only) before exiting.
            print(f"forward_eod: {asof} already processed (upkeep_done + signals "
                  f"present) — skipping stages 1-5; running sync only")
            _run_sync(do_sync)
            return 0

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
        print(f"[2/6] loaded {len(prices)} symbols in {_fmt_eta(time.time() - t0)}")

        # [3/6] upkeep
        print("[3/6] run_upkeep...")
        t0 = time.time()
        closed_rows = run_upkeep(ledger, prices, asof)
        for row in closed_rows:
            _alert(alerts.exit_alert(row))
        print(f"[3/6] upkeep done: {len(closed_rows)} closed in {_fmt_eta(time.time() - t0)}")

        # [4/6] signals
        print("[4/6] generate_signals...")
        t0 = time.time()
        catalyst = CatalystCalendar.load()
        result = generate_signals(ledger, prices, asof, catalyst)
        queued = result["queued"]
        for cand in queued:
            _alert(alerts.entry_alert(cand))
        if not queued:
            _alert(f"No candidates for {asof.isoformat()}")
        # Book status goes out every night regardless of queue state —
        # silence must be distinguishable from outage (prereg caveat).
        snapshots = [ledger.equity_series(book)[-1] for book in ("shared", "h1solo")
                     if ledger.equity_series(book)]
        if snapshots:
            _alert(alerts.book_status(snapshots))
        print(f"[4/6] signals done: {len(queued)} queued, {len(result['skipped'])} skipped "
              f"in {_fmt_eta(time.time() - t0)}")

        # [5/6] missed sessions
        print("[5/6] detect_missed_sessions...")
        missed = detect_missed_sessions(ledger, asof)
        if missed:
            dates_str = ", ".join(d.isoformat() for d in missed)
            _alert(f"WARNING: missed upkeep sessions detected: {dates_str}")
        print(f"[5/6] {len(missed)} missed session(s)")

        # [6/6] sync
        _run_sync(do_sync)

        print(f"forward_eod: {asof} complete in {_fmt_eta(time.time() - t_start)}")
        return 0

    except Exception:
        logger.error("forward_eod: fatal error\n%s", traceback.format_exc())
        try:
            if not args.dry_run and not args.no_discord:
                alerts.send(f"forward_eod FAILED: {traceback.format_exc()[-500:]}")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
