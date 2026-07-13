"""Hourly advisory monitor: intraday stop/target/move alerts, never fills.

WHY: the daily-bar engine (`forward_eod.py` upkeep) is the sole authority
for exits — this script exists only so a human sees an intraday stop/target
touch or an outsized pre/post-market move well before the next EOD run
closes the position. It NEVER writes a ledger row; its only side effect is
a Discord alert plus a `kind="monitor_alert"` journal record used purely
for same-day dedupe (a second run within the hour, or a re-run after a
crash, must not re-alert).

SEQUENCE:
  1. env.load(); load ledger; collect open rows across both books, deduped
     by symbol for the quote fetch (a symbol held in both books gets one
     quote lookup but is evaluated — and can alert — once per row).
  2. Per symbol: quote via injectable `_get_quote` (yfinance `fast_info`,
     wrapped so tests can substitute a fake). Missing quote -> log + skip
     that symbol, other symbols unaffected.
  3. Per row: stop-touched (`last <= sl`), target-touched (`last >= tp1`),
     and — only outside regular trading hours — a >3% move vs prior close.
  4. Per (entry_id, alert_type) not already recorded today
     (`ledger.signals(today)`): send the Discord alert, then append the
     `monitor_alert` journal record (send-then-record — a crash between the
     two just means a harmless duplicate alert next run, never a silently
     swallowed one).

Exit code 0 on success, 1 on any stage exception.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
import traceback
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sts import env  # noqa: E402
from sts.data.study_store import StudyStore  # noqa: E402
from sts.forward import alerts  # noqa: E402
from sts.forward.ledger import Ledger, LedgerPaths  # noqa: E402

logger = logging.getLogger("forward_monitor")

_ET = ZoneInfo("America/New_York")
_RTH_OPEN = dt.time(9, 30)
_RTH_CLOSE = dt.time(16, 0)
_MOVE_THRESHOLD = 0.03

_STOP_TOUCHED = "stop_touched"
_TARGET_TOUCHED = "target_touched"
_MOVE_WARN = "move_warn"


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _is_rth(now_utc: dt.datetime) -> bool:
    et = now_utc.astimezone(_ET)
    return et.weekday() < 5 and _RTH_OPEN <= et.time() <= _RTH_CLOSE


def _get_quote(symbol: str) -> dict | None:
    """Live quote via yfinance fast_info. Best-effort: any failure or a
    missing last price returns None (caller logs + skips)."""
    try:
        import yfinance as yf  # lazy: avoid import cost when monkeypatched in tests

        fi = yf.Ticker(symbol).fast_info
        last = fi.get("last_price") if hasattr(fi, "get") else fi["last_price"]
        prev_close = None
        for key in ("previous_close", "regular_market_previous_close"):
            try:
                prev_close = fi.get(key) if hasattr(fi, "get") else fi[key]
            except Exception:  # noqa: BLE001
                prev_close = None
            if prev_close is not None:
                break
        if last is None:
            return None
        return {"last": float(last), "prev_close": float(prev_close) if prev_close is not None else None}
    except Exception as exc:  # noqa: BLE001 — quote outage must not crash the run
        logger.warning("forward_monitor: quote fetch failed for %s: %s", symbol, exc)
        return None


def _prev_close_fallback(store: StudyStore, symbol: str) -> float | None:
    df = store.load(symbol)
    if df is None or df.empty:
        return None
    return float(df["close"].iloc[-1])


def _open_rows(ledger: Ledger) -> list[dict]:
    return ledger.open_rows(book="shared") + ledger.open_rows(book="h1solo")


def _alerts_for_row(row: dict, quote: dict, now_utc: dt.datetime) -> list[tuple[str, str]]:
    last = quote["last"]
    out: list[tuple[str, str]] = []
    if last <= row["sl"]:
        out.append((_STOP_TOUCHED, "STOP TOUCHED (advisory; daily-bar engine governs fills)"))
    if last >= row["tp1"]:
        out.append((_TARGET_TOUCHED, "TARGET TOUCHED (advisory)"))
    prev_close = quote.get("prev_close")
    if prev_close and not _is_rth(now_utc):
        move = abs(last / prev_close - 1)
        if move > _MOVE_THRESHOLD:
            out.append((_MOVE_WARN, f"PRE/POST MOVE {move * 100:.1f}% vs prior close (advisory)"))
    return out


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--asof", default=None, help="YYYY-MM-DD; default today (dedupe key)")
    parser.add_argument("--dry-run", action="store_true", help="no Discord")
    parser.add_argument("--no-discord", action="store_true")
    parser.add_argument("--ledger-root", default="ledger")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    do_discord = not (args.dry_run or args.no_discord)

    def _alert(text: str) -> None:
        if do_discord:
            alerts.send(text)
        else:
            logger.info("forward_monitor (alert suppressed): %s", text)

    try:
        env.load()
        today = dt.date.fromisoformat(args.asof) if args.asof else dt.date.today()
        now_utc = _now_utc()

        ledger = Ledger(LedgerPaths(root=Path(args.ledger_root)))
        store = StudyStore()

        rows = _open_rows(ledger)
        symbols = sorted({r["ticker"] for r in rows})
        print(f"forward_monitor: {today}: {len(rows)} open row(s), {len(symbols)} unique symbol(s)")

        quotes: dict[str, dict | None] = {}
        for sym in symbols:
            q = _get_quote(sym)
            if q is not None and q.get("prev_close") is None:
                q["prev_close"] = _prev_close_fallback(store, sym)
            quotes[sym] = q

        already = {r["entry_id"] for r in ledger.signals(today)}

        sent = 0
        for row in rows:
            quote = quotes.get(row["ticker"])
            if quote is None:
                logger.warning("forward_monitor: no quote for %s, skipping row %s",
                                row["ticker"], row["entry_id"])
                continue
            for alert_type, msg_suffix in _alerts_for_row(row, quote, now_utc):
                alert_eid = f"{row['entry_id']}#{alert_type}"
                if alert_eid in already:
                    continue
                text = f"{row['ticker']} {msg_suffix} last={quote['last']:.2f} ({row['book']})"
                _alert(text)
                ledger.append_signal(
                    {
                        "kind": "monitor_alert",
                        "book": row["book"],
                        "entry_id": alert_eid,
                        "signal_date": today.isoformat(),
                        "ticker": row["ticker"],
                        "alert_type": alert_type,
                        "last": quote["last"],
                    }
                )
                already.add(alert_eid)
                sent += 1

        print(f"forward_monitor: {today} done — {sent} alert(s) sent")
        return 0

    except Exception:
        logger.error("forward_monitor: fatal error\n%s", traceback.format_exc())
        try:
            if not args.dry_run and not args.no_discord:
                alerts.send(f"forward_monitor FAILED: {traceback.format_exc()[-500:]}")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
