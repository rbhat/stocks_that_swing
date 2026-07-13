"""EOD pipeline core: exit upkeep + signal generation.

Two daily jobs, both idempotent/resume-capable, state lives entirely in the
`Ledger` (never in process memory):

- `run_upkeep`: replays `risk.manage_bar` over every open position's unseen
  session bars, closing positions that hit stop/target/time, then stamps a
  per-book equity snapshot and a single `upkeep_done` control record for
  `asof`.
- `generate_signals`: builds the ranked H2-then-H1 entry queue for `asof`
  (the signal date; next-session-open entry per the backtested convention),
  walks it once per book (`shared` then `h1solo`) applying charter checks,
  and journals either a `candidate` or a `skip` record per candidate.
- `detect_missed_sessions`: finds sessions between the last `upkeep_done`
  and `asof` with no upkeep record — a job/webhook outage must show up as an
  explicit gap in the journal, never a silent hole (prereg "Known caveats").
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from sts import risk
from sts.calendar import sessions_between
from sts.catalyst import CatalystCalendar
from sts.forward.book import BookState, h1_throttle_room
from sts.forward.broker import cost_side
from sts.forward.ledger import Ledger, entry_id
from sts.study.h1_events import _PARAM_DEFAULTS as _H1_RISK_DEFAULTS
from sts.study.h4_candidates import candidates_for

_CONFIG_NAME = {"h1": "trend_pullback", "h2": "pead_day2_open"}


def _as_date(value: dt.date | str) -> dt.date:
    return dt.date.fromisoformat(value) if isinstance(value, str) else value


def _entry_session(row: dict) -> dt.date:
    """`opened` for the rebuilt `risk.Position`: the row's `timestamp` is the
    entry fill moment, whose date is the entry session."""
    ts = row["timestamp"]
    if isinstance(ts, str):
        ts = dt.datetime.fromisoformat(ts)
    return ts.date()


def run_upkeep(ledger: Ledger, prices: dict[str, pd.DataFrame], asof: dt.date) -> list[dict]:
    if asof in ledger.processed_upkeep_dates():
        return []

    processed = ledger.processed_upkeep_dates()
    last_processed = max(processed) if processed else None

    closed_rows: list[dict] = []
    for row in ledger.open_rows():
        symbol = row["ticker"]
        df = prices.get(symbol)
        if df is None or df.empty:
            continue

        pos = risk.Position(
            symbol=symbol,
            entry=row["entry_fill"],
            shares=row["qty"],
            stop=row["sl"],
            target=row["tp1"],
            opened=_entry_session(row),
            config=row["family"],
        )
        all_dates = sorted({d for d in df.index.date if d > pos.opened and d <= asof})
        if last_processed is not None:
            # Bars already replayed by prior upkeep runs still count toward
            # the 15-session time stop: carry bars_held across incremental
            # invocations, else daily operation would reset it every run and
            # the time stop would never fire.
            pos.bars_held = len([d for d in all_dates if d <= last_processed])
            bar_dates = [d for d in all_dates if d > last_processed]
        else:
            pos.bars_held = 0
            bar_dates = all_dates

        for bar_date in bar_dates:
            bar = df.loc[pd.Timestamp(bar_date)]
            exits = risk.manage_bar(
                pos,
                bar_open=float(bar["open"]),
                bar_high=float(bar["high"]),
                bar_low=float(bar["low"]),
                bar_close=float(bar["close"]),
            )
            if not exits:
                continue
            reason, price, shares = exits[0]

            entry_fee = cost_side(row["entry_fill"], row["qty"])
            exit_fee = cost_side(price, shares)
            fees_total = entry_fee + exit_fee
            pnl_usd = shares * (price - row["entry_fill"]) - fees_total
            stop_initial = row["stop_initial"]
            r_net = (
                price - row["entry_fill"] - fees_total / shares
            ) / (row["entry_fill"] - stop_initial)

            closed = dict(row)
            closed["status"] = "closed"
            closed["exit_price"] = price
            closed["exit_timestamp"] = dt.datetime.combine(
                bar_date, dt.time(20, 0), tzinfo=dt.UTC
            ).isoformat()
            closed["exit_reason"] = reason
            closed["fees_total"] = fees_total
            closed["pnl_usd"] = pnl_usd
            closed["r_net"] = r_net

            ledger.append_row(closed)
            closed_rows.append(closed)
            break  # position is closed; no further bars processed for it

    for book in ("shared", "h1solo"):
        marks: dict[str, float] = {}
        for r in ledger.open_rows(book=book):
            df = prices.get(r["ticker"])
            if df is not None and not df.empty:
                marks[r["ticker"]] = float(df["close"].iloc[-1])
        state = BookState.from_ledger(ledger, book, marks=marks)
        ledger.append_equity_snapshot(state.snapshot(asof))

    ledger.append_signal(
        {
            "kind": "upkeep_done",
            # Carried on book "shared" by convention: this is a single
            # book-agnostic control record, not a per-book fact, but
            # append_signal/entry_id dedup keys require a book. "shared" is
            # arbitrary here — see module docstring.
            "book": "shared",
            "entry_id": None,
            "signal_date": asof.isoformat(),
            "date": asof.isoformat(),
        }
    )

    return closed_rows


def _default_candidate_source(
    prices: dict[str, pd.DataFrame], asof: dt.date, catalyst: CatalystCalendar
) -> dict[str, list[dict]]:
    oos_start = asof
    oos_end = asof + dt.timedelta(days=1)
    return {
        "h2": candidates_for("h2", prices, oos_start, oos_end, catalyst),
        "h1": candidates_for("h1", prices, oos_start, oos_end, catalyst),
    }


def _rank_key_h1(c: dict) -> tuple:
    return (
        not c["is_seed"],
        c["rsi2_at_trigger"],
        c["reclaim_wait_sessions"],
        c["signal_date"],
        c["symbol"],
    )


def _provisional_geometry(
    df: pd.DataFrame, asof: dt.date, atr_window: int
) -> tuple[float, float, float, float] | None:
    """close_sig, atr_sig, provisional stop/target anchored at the signal
    bar's own close+ATR (fill job re-anchors at the actual next-open fill
    with the same 2.0/2.0 multiples later)."""
    if asof not in set(df.index.date):
        return None
    atr_series = risk.atr(df, window=atr_window)
    idx = list(df.index.date).index(asof)
    close_sig = float(df["close"].iloc[idx])
    atr_sig = float(atr_series.iloc[idx])
    if not (atr_sig > 0):
        return None
    stop = risk.atr_stop(close_sig, atr_sig, multiple=2.0)
    target = risk.atr_target(close_sig, atr_sig, multiple=2.0)
    return close_sig, atr_sig, stop, target


def generate_signals(
    ledger: Ledger,
    prices,
    asof: dt.date,
    catalyst,
    candidate_source=_default_candidate_source,
) -> dict:
    raw = candidate_source(prices, asof, catalyst)
    h2_candidates = sorted(raw.get("h2", []), key=lambda c: (c["signal_date"], c["symbol"]))
    h1_candidates = sorted(raw.get("h1", []), key=_rank_key_h1)

    atr_window = _H1_RISK_DEFAULTS["atr_window"]

    session_dates = list(sessions_between(asof - dt.timedelta(days=30), asof).date)

    # Calendar-true next trading session (entry session), not asof+1 calendar
    # day — a Friday signal enters Monday, and the 2-session embargo must be
    # anchored to the actual entry session.
    upcoming = sessions_between(asof + dt.timedelta(days=1), asof + dt.timedelta(days=14))
    next_session = upcoming[0].date() if len(upcoming) else asof + dt.timedelta(days=1)

    # NOTE (same-day re-run): generate_signals is idempotent at the ledger
    # level — append_signal dedups on (signal_date, book, entry_id), so a
    # re-run for an already-processed asof never writes duplicate records.
    # However, the RETURNED payload of a re-run can be misleading: candidates
    # queued in the first run are now counted by h1_throttle_room, so a
    # re-run may report them as "throttle" skips (the skip append is then a
    # dedup no-op, but the in-memory return value still lists them). Callers
    # alerting from the return value should not re-run for the same asof;
    # ledger integrity holds regardless. Chosen over an early-return guard to
    # keep this function stateless w.r.t. "was this asof already signalled".

    queued: list[dict] = []
    skipped: list[dict] = []

    def _geom(cand: dict) -> tuple[float, float, float, float] | None:
        df = prices.get(cand["symbol"])
        if df is None or df.empty:
            return None
        return _provisional_geometry(df, asof, atr_window)

    def _walk(book: str, queue: list[dict], enforce_throttle: bool) -> None:
        marks: dict[str, float] = {}
        for r in ledger.open_rows(book=book):
            df = prices.get(r["ticker"])
            if df is not None and not df.empty:
                marks[r["ticker"]] = float(df["close"].iloc[-1])
        state = BookState.from_ledger(ledger, book, marks=marks)

        # Local provisional overlay: candidates queued earlier in this same
        # walk aren't in the ledger yet but must still count against
        # slots/notional/throttle for subsequent candidates.
        provisional_open: list[dict] = []
        provisional_notional = 0.0

        for cand in queue:
            symbol = cand["symbol"]
            family = cand["family"]
            signal_date = _as_date(cand["signal_date"])
            eid = entry_id(book, family, symbol, signal_date)

            if catalyst.catalyst_within(symbol, next_session, 2, "block_entry") is not None:
                skipped.append(
                    _append_skip(ledger, book, family, eid, asof, symbol, "embargo")
                )
                continue

            geom = _geom(cand)
            if geom is None:
                skipped.append(
                    _append_skip(ledger, book, family, eid, asof, symbol, "size_zero")
                )
                continue
            close_sig, atr_sig, stop, target = geom

            shared_blocked: set[str] = set()
            if book == "shared":
                other_family = "h2" if family == "h1" else "h1"
                shared_blocked = {
                    r["ticker"]
                    for r in ledger.open_rows(book="shared")
                    if r["family"] == other_family
                } | {
                    p["symbol"] for p in provisional_open if p["family"] == other_family
                }

            held_now = {r["ticker"] for r in state.open_rows} | {
                p["symbol"] for p in provisional_open
            }
            open_count_now = len(state.open_rows) + len(provisional_open)
            deployed_now = state.deployed_usd() + provisional_notional

            reason = None
            if symbol in held_now or symbol in shared_blocked:
                reason = "dup_symbol"
            elif open_count_now >= risk.MAX_POSITIONS:
                reason = "slot"

            provisional_qty = None
            if reason is None:
                provisional_qty = risk.position_size(
                    state.equity,
                    close_sig,
                    stop,
                    deployed=deployed_now,
                    cash=state.cash - provisional_notional,
                    open_positions=open_count_now,
                )
                notional = provisional_qty * close_sig if provisional_qty else 0.0
                # NOTE: position_size already sizes DOWN against the 80%
                # deploy cap (its by_deployed term), matching
                # simulate_portfolio's live behavior — so when deploy room is
                # tight the candidate is queued at reduced size (or falls to
                # size_zero when no room at all) rather than rejected here.
                # This branch is therefore normally unreachable and is kept
                # only defensively (e.g. float-edge rounding).
                if provisional_qty > 0 and deployed_now + notional > risk.MAX_DEPLOYED_PCT * state.equity:
                    reason = "deploy_cap"

            if reason is None and family == "h1" and enforce_throttle:
                # h1_throttle_room reads directly from the ledger, which
                # already reflects every candidate queued earlier in this
                # same walk (append_signal is synchronous per iteration) —
                # no separate provisional overlay needed here.
                room = h1_throttle_room(ledger, book, session_dates)
                if room <= 0:
                    reason = "throttle"

            if reason is None and (provisional_qty is None or provisional_qty <= 0):
                reason = "size_zero"

            if reason is not None:
                skipped.append(
                    _append_skip(ledger, book, family, eid, asof, symbol, reason)
                )
                continue

            qty = provisional_qty
            rec = {
                "kind": "candidate",
                "book": book,
                "family": family,
                "entry_id": eid,
                "signal_date": asof.isoformat(),
                "ticker": symbol,
                "qty": qty,
                "entry_price_range": [
                    round(close_sig - 0.25 * atr_sig, 2),
                    round(close_sig + 0.25 * atr_sig, 2),
                ],
                "sl": stop,
                "tp1": target,
                "atr_sig": atr_sig,
                "close_sig": close_sig,
                "config_name": _CONFIG_NAME[family],
            }
            if family == "h1":
                rec["is_seed"] = cand["is_seed"]
                rec["rsi2_at_trigger"] = cand["rsi2_at_trigger"]
                rec["reclaim_wait_sessions"] = cand["reclaim_wait_sessions"]

            ledger.append_signal(rec)
            queued.append(rec)

            provisional_open.append({"symbol": symbol, "family": family})
            provisional_notional += qty * close_sig

    _walk("shared", h2_candidates + h1_candidates, enforce_throttle=True)
    _walk("h1solo", h1_candidates, enforce_throttle=True)

    return {"queued": queued, "skipped": skipped}


def _append_skip(
    ledger: Ledger, book: str, family: str, eid: str, asof: dt.date, symbol: str, reason: str
) -> dict:
    rec = {
        "kind": "skip",
        "book": book,
        "family": family,
        "entry_id": eid,
        "signal_date": asof.isoformat(),
        "ticker": symbol,
        "reason": reason,
    }
    ledger.append_signal(rec)
    return rec


def detect_missed_sessions(ledger: Ledger, asof: dt.date) -> list[dt.date]:
    processed = ledger.processed_upkeep_dates()
    if not processed:
        return []
    last = max(processed)
    if last >= asof:
        return []

    candidates = [d for d in sessions_between(last, asof).date if last < d < asof]
    missing = [d for d in candidates if d not in processed]

    for d in missing:
        ledger.append_signal(
            {
                "kind": "missed_session",
                "book": "shared",
                "entry_id": f"missed:{d.isoformat()}",
                "signal_date": d.isoformat(),
                "date": d.isoformat(),
            }
        )

    return missing
