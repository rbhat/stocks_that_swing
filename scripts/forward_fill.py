"""Open-fill job: fills today's queued candidates at the session open.

WHY: `forward_eod.py` (Task 7) queues `kind="candidate"` signals the night
before entry, sized against stale (prior-close) equity. This script runs
after the session opens (>=9:31 ET) and does the actual fill: fetch today's
session open via `StubPaperBroker`, re-anchor stop/target off the ACTUAL
fill price (not the provisional signal-bar geometry), re-check the book
charter at CURRENT state (another job may have opened positions since the
candidate was queued), and append the resulting `open` ledger row.

Idempotent by `entry_id` — `ledger.state()` is the single source of truth
for "already filled," so a killed or re-run job for the same session is a
safe no-op for candidates already opened, and simply resumes for any
candidate still missing its open row (e.g. one that hit the retry timeout
on a prior run).

SEQUENCE:
  1. env.load(); resolve asof (default today); refuse to run on a
     non-session (log, exit 0).
  2. Collect today's fillable candidates: kind="candidate" signals whose
     entry session (next trading session after signal_date) == asof and
     whose entry_id has no ledger row yet.
  3. Per candidate: retry-loop `StubPaperBroker.fill_entry` (open not yet
     published intraday is expected right after the bell) up to
     --max-wait-min (default 20, polled every 60s, injectable sleep for
     tests). No fill after the deadline -> log + leave the candidate
     unfilled (fillable again on a later run today).
  4. On fill: re-anchor sl/tp1 off the fill price, re-check
     BookState.can_enter + re-size against CURRENT book state, append
     either a `skip` signal (blocked/size_zero) or an `open` ledger row.
     Discord confirmation per fill.

Exit code 0 on success (including "nothing to fill" and "not a session"),
1 on any stage exception.
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

import pandas as pd  # noqa: E402

from sts import calendar, env, risk  # noqa: E402
from sts.data.fetch import fetch_daily  # noqa: E402
from sts.data.study_store import StudyStore  # noqa: E402
from sts.forward import alerts  # noqa: E402
from sts.forward.book import BookState  # noqa: E402
from sts.forward.broker import StubPaperBroker, cost_side  # noqa: E402
from sts.forward.ledger import SOURCES, Ledger, LedgerPaths  # noqa: E402

logger = logging.getLogger("forward_fill")

POLL_INTERVAL_SEC = 60
DEFAULT_MAX_WAIT_MIN = 20


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _get_open(store: StudyStore, symbol: str, date: dt.date) -> float | None:
    """Today's session open: cached StudyStore bar if present, else a live
    `fetch_daily` fallback (a yfinance partial row's `open` is final once
    the bell has rung, unlike its high/low/close)."""
    df = store.load(symbol)
    if df is not None and date in set(df.index.date):
        return float(df.loc[pd.Timestamp(date), "open"])
    try:
        fetched = fetch_daily(symbol, start=date)
    except Exception as exc:  # noqa: BLE001 — network/parse failure -> treat as unavailable
        logger.warning("forward_fill: fetch_daily(%s) failed: %s", symbol, exc)
        return None
    if fetched is None or fetched.empty or date not in set(fetched.index.date):
        return None
    return float(fetched.loc[pd.Timestamp(date), "open"])


def _entry_session(signal_date: dt.date) -> dt.date:
    upcoming = calendar.sessions_between(
        signal_date + dt.timedelta(days=1), signal_date + dt.timedelta(days=14)
    )
    return upcoming[0].date() if len(upcoming) else signal_date + dt.timedelta(days=1)


def _as_date(value: dt.date | str) -> dt.date:
    return dt.date.fromisoformat(value) if isinstance(value, str) else value


def _fillable_candidates(ledger: Ledger, asof: dt.date) -> list[dict]:
    filled = set(ledger.state().keys())
    out = []
    for rec in ledger.signals():
        if rec.get("kind") != "candidate":
            continue
        if rec["entry_id"] in filled:
            continue
        if _entry_session(_as_date(rec["signal_date"])) == asof:
            out.append(rec)
    return out


def _fill_with_retry(broker: StubPaperBroker, symbol: str, date: dt.date, qty: int,
                      max_wait_min: float, sleep_fn) -> dict | None:
    max_polls = max(1, int(round(max_wait_min * 60 / POLL_INTERVAL_SEC)))
    for attempt in range(1, max_polls + 1):
        fill = broker.fill_entry(symbol, date, qty)
        if fill is not None:
            return fill
        if attempt < max_polls:
            logger.info(
                "forward_fill: %s open not yet available (attempt %d/%d), sleeping %ds",
                symbol, attempt, max_polls, POLL_INTERVAL_SEC,
            )
            sleep_fn(POLL_INTERVAL_SEC)
    return None


def _marks_for_book(ledger: Ledger, store: StudyStore, book: str) -> dict[str, float]:
    marks: dict[str, float] = {}
    for r in ledger.open_rows(book=book):
        df = store.load(r["ticker"])
        if df is not None and not df.empty:
            marks[r["ticker"]] = float(df["close"].iloc[-1])
    return marks


def _shared_blocked(ledger: Ledger, book: str, family: str) -> set[str]:
    if book != "shared":
        return set()
    other_family = "h2" if family == "h1" else "h1"
    return {r["ticker"] for r in ledger.open_rows(book="shared") if r["family"] == other_family}


def _process_candidate(
    ledger: Ledger, store: StudyStore, broker: StubPaperBroker, cand: dict,
    asof: dt.date, max_wait_min: float, sleep_fn, alert_fn,
) -> str:
    """Returns one of: "filled", "skipped", "unavailable"."""
    symbol = cand["ticker"]
    book = cand["book"]
    family = cand["family"]
    eid = cand["entry_id"]
    queued_qty = cand["qty"]

    fill = _fill_with_retry(broker, symbol, asof, queued_qty, max_wait_min, sleep_fn)
    if fill is None:
        logger.warning(
            "forward_fill: %s (%s) no open available after %.0f min — deferring",
            symbol, eid, max_wait_min,
        )
        return "unavailable"

    fill_price = fill["price"]
    atr_sig = cand["atr_sig"]
    sl = risk.atr_stop(fill_price, atr_sig, 2.0)
    tp1 = risk.atr_target(fill_price, atr_sig, 2.0)

    marks = _marks_for_book(ledger, store, book)
    state = BookState.from_ledger(ledger, book, marks=marks)
    shared_blocked = _shared_blocked(ledger, book, family)

    reason = state.can_enter(symbol, fill_price * queued_qty, shared_blocked)
    qty = None
    if reason is None:
        qty = min(queued_qty, state.size(fill_price, sl))
        if qty <= 0:
            reason = "size_zero"

    if reason is not None:
        ledger.append_signal(
            {
                "kind": "skip",
                "book": book,
                "family": family,
                "entry_id": eid,
                "signal_date": asof.isoformat(),
                "ticker": symbol,
                "reason": reason,
            }
        )
        logger.info("forward_fill: %s (%s) skipped at fill time: %s", symbol, eid, reason)
        return "skipped"

    entry_fee = cost_side(fill_price, qty)
    row = {
        "entry_id": eid,
        "family": family,
        "source": SOURCES[book],
        "book": book,
        "ticker": symbol,
        "signal_date": cand["signal_date"],
        "timestamp": fill["timestamp"],
        "qty": qty,
        "entry_ref": fill_price,
        "entry_fill": fill_price,
        "entry_price_range": cand["entry_price_range"],
        "stop_initial": sl,
        "sl": sl,
        "tp1": tp1,
        "tp2": None,
        "status": "open",
        "usd_deployed": qty * fill_price,
        "exit_price": None,
        "exit_timestamp": None,
        "exit_reason": None,
        # Entry-side cost only, matching pipeline._close_row's convention
        # (BookState.from_ledger derives exit_fee = fees_total - entry_fee,
        # and pipeline.run_upkeep sets fees_total = entry_fee + exit_fee on
        # close) — see src/sts/forward/book.py module docstring.
        "fees_total": entry_fee,
        "pnl_usd": None,
        "r_net": None,
    }
    ledger.append_row(row)
    alert_fn(
        f"{symbol} FILLED @{fill_price:.2f} qty={qty}, SL={sl:.2f}, TP1={tp1:.2f} ({book})"
    )
    return "filled"


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--asof", default=None, help="YYYY-MM-DD; default today")
    parser.add_argument("--dry-run", action="store_true", help="no Discord")
    parser.add_argument("--no-discord", action="store_true")
    parser.add_argument("--ledger-root", default="ledger")
    parser.add_argument("--max-wait-min", type=float, default=DEFAULT_MAX_WAIT_MIN)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    do_discord = not (args.dry_run or args.no_discord)

    def _alert(text: str) -> None:
        if do_discord:
            alerts.send(text)
        else:
            logger.info("forward_fill (alert suppressed): %s", text)

    try:
        env.load()
        asof = dt.date.fromisoformat(args.asof) if args.asof else dt.date.today()

        if not calendar.is_session(asof):
            print(f"forward_fill: {asof} is not a trading session — nothing to do")
            return 0

        ledger = Ledger(LedgerPaths(root=Path(args.ledger_root)))
        store = StudyStore()
        broker = StubPaperBroker(get_open=lambda symbol, date: _get_open(store, symbol, date))

        candidates = _fillable_candidates(ledger, asof)
        print(f"forward_fill: {asof}: {len(candidates)} candidate(s) to fill")

        filled = skipped = unavailable = 0
        for i, cand in enumerate(candidates, 1):
            print(f"  [{i}/{len(candidates)}] {cand['ticker']} ({cand['entry_id']})")
            outcome = _process_candidate(
                ledger, store, broker, cand, asof, args.max_wait_min, _sleep, _alert
            )
            if outcome == "filled":
                filled += 1
            elif outcome == "skipped":
                skipped += 1
            else:
                unavailable += 1

        print(f"forward_fill: {asof} done — {filled} filled, {skipped} skipped, "
              f"{unavailable} unavailable (resumable)")
        return 0

    except Exception:
        logger.error("forward_fill: fatal error\n%s", traceback.format_exc())
        try:
            if not args.dry_run and not args.no_discord:
                alerts.send(f"forward_fill FAILED: {traceback.format_exc()[-500:]}")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
