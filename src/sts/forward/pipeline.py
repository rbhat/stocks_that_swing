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
  journals either a `candidate` or a `skip` record per candidate, and writes
  `signals_done` only after both deterministic walks finish. An interrupted
  walk resumes from its journaled prefix and reconstructs provisional state.
- `detect_missed_sessions`: finds sessions between the last `upkeep_done`
  and `asof` with no upkeep record — a job/webhook outage must show up as an
  explicit gap in the journal, never a silent hole (prereg "Known caveats").
"""

from __future__ import annotations

import datetime as dt
import math
import time
from copy import deepcopy

import pandas as pd

from sts import risk
from sts.calendar import sessions_between
from sts.catalyst import CatalystCalendar
from sts.forward.book import BookState, h1_throttle_room
from sts.forward.broker import cost_side
from sts.forward.ledger import Ledger, entry_id
from sts.study.h1_events import _PARAM_DEFAULTS as _H1_RISK_DEFAULTS
from sts.study.h4_candidates import selected_signals_for

_CONFIG_NAME = {"h1": "trend_pullback", "h2": "pead_day2_open"}
_LEGACY_GEOMETRY = {
    "h1": {"stop_atr_multiple": 2.0, "target_atr_multiple": 2.0},
    "h2": {"stop_atr_multiple": 2.0, "target_atr_multiple": 2.0},
}


def _version_fact(ledger: Ledger) -> dict:
    if ledger.strategy_version is None:
        return {}
    return {"strategy_version": ledger.strategy_version}


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
        ledger.append_equity_snapshot(
            state.snapshot(asof, strategy_version=ledger.strategy_version)
        )

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
            **_version_fact(ledger),
        }
    )

    return closed_rows


def _prices_through_asof(
    prices: dict[str, pd.DataFrame], asof: dt.date
) -> dict[str, pd.DataFrame]:
    return {
        symbol: (
            frame.loc[frame.index.date <= asof]
            if frame is not None and not frame.empty
            else frame
        )
        for symbol, frame in prices.items()
    }


def summarize_price_freshness(
    prices: dict[str, pd.DataFrame],
    symbols: list[str],
    asof: dt.date,
) -> dict:
    """Return a compact roster-level market-data health summary.

    ``fresh`` means the frame contains the requested completed session.
    ``stale`` includes the last cached session for each lagging symbol, and
    ``missing`` names roster symbols with no usable frame at all. The symbol
    lists are intentionally durable: an operator should not need raw logs to
    identify the stale input.
    """
    fresh: list[str] = []
    stale: list[dict[str, str]] = []
    missing: list[str] = []
    for symbol in sorted(set(symbols)):
        frame = prices.get(symbol)
        if frame is None or frame.empty:
            missing.append(symbol)
            continue
        dates = [date for date in frame.index.date if date <= asof]
        if not dates:
            missing.append(symbol)
            continue
        last_date = max(dates)
        if last_date == asof:
            fresh.append(symbol)
        else:
            stale.append({"symbol": symbol, "last_date": last_date.isoformat()})
    return {
        "counts": {
            "fresh": len(fresh),
            "stale": len(stale),
            "missing": len(missing),
        },
        "fresh_symbols": fresh,
        "stale_symbols": stale,
        "missing_symbols": missing,
    }


def classify_signal_outcome(counts: dict, *, complete: bool) -> str:
    """Classify the signal stage without collapsing distinct zero-trade cases."""
    if not complete:
        return "signal_stage_incomplete"
    selected = sum(family["selected"] for family in counts.values())
    queued = sum(family["queued"] for family in counts.values())
    embargoed = sum(family["embargoed"] for family in counts.values())
    book_blocked = sum(
        sum(family["skipped_by_reason"].values()) for family in counts.values()
    )
    if selected == 0:
        return "selected_zero"
    if queued:
        return "queued"
    if embargoed and not book_blocked:
        return "selected_embargoed"
    if book_blocked:
        return "selected_book_blocked"
    return "selected_data_rejected"


def _default_candidate_source(
    prices: dict[str, pd.DataFrame], asof: dt.date, catalyst: CatalystCalendar
) -> dict[str, list[dict]]:
    del catalyst
    oos_start = asof
    oos_end = asof + dt.timedelta(days=1)
    prices = _prices_through_asof(prices, asof)
    return {
        "h2": selected_signals_for("h2", prices, oos_start, oos_end),
        "h1": selected_signals_for("h1", prices, oos_start, oos_end),
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
    df: pd.DataFrame,
    asof: dt.date,
    atr_window: int,
    *,
    stop_atr_multiple: float,
    target_atr_multiple: float,
) -> tuple[float, float, float, float] | None:
    """close_sig, atr_sig, provisional stop/target anchored at the signal
    bar's own close+ATR (fill job re-anchors at the actual next-open fill
    with the candidate's explicit immutable multiples later)."""
    if asof not in set(df.index.date):
        return None
    atr_series = risk.atr(df, window=atr_window)
    idx = list(df.index.date).index(asof)
    close_sig = float(df["close"].iloc[idx])
    atr_sig = float(atr_series.iloc[idx])
    if not (math.isfinite(close_sig) and math.isfinite(atr_sig) and atr_sig > 0):
        return None
    stop = risk.atr_stop(close_sig, atr_sig, multiple=stop_atr_multiple)
    target = risk.atr_target(close_sig, atr_sig, multiple=target_atr_multiple)
    if not (math.isfinite(stop) and math.isfinite(target)):
        return None
    return close_sig, atr_sig, stop, target


def generate_signals(
    ledger: Ledger,
    prices,
    asof: dt.date,
    catalyst,
    candidate_source=_default_candidate_source,
    summary_context: dict | None = None,
    strategy_geometry: dict[str, dict[str, float]] | None = None,
) -> dict:
    signal_started = time.perf_counter()
    prices = _prices_through_asof(prices, asof)
    raw = candidate_source(prices, asof, catalyst)
    atr_window = _H1_RISK_DEFAULTS["atr_window"]
    if ledger.strategy_version is not None and strategy_geometry is None:
        raise ValueError(
            "success-v2 signal generation requires explicit strategy_geometry"
        )
    geometry = strategy_geometry if strategy_geometry is not None else _LEGACY_GEOMETRY
    for family in ("h2", "h1"):
        facts = geometry.get(family, {})
        if {
            "stop_atr_multiple",
            "target_atr_multiple",
        } - facts.keys():
            raise ValueError(f"{family} is missing explicit stop/target multiples")

    session_dates = list(sessions_between(asof - dt.timedelta(days=30), asof).date)

    # Calendar-true next trading session (entry session), not asof+1 calendar
    # day — a Friday signal enters Monday, and the 2-session embargo must be
    # anchored to the actual entry session.
    upcoming = sessions_between(asof + dt.timedelta(days=1), asof + dt.timedelta(days=14))
    next_session = upcoming[0].date() if len(upcoming) else asof + dt.timedelta(days=1)

    counts = {
        family: {
            "detected": len(raw.get(family, [])),
            "selected": len(raw.get(family, [])),
            "missing_signal_bar": 0,
            "stale_signal_bar": 0,
            "invalid_geometry": 0,
            "embargoed": 0,
            "queued": 0,
            "skipped_by_reason": {},
        }
        for family in ("h2", "h1")
    }

    def _validated(family: str) -> list[dict]:
        valid: list[dict] = []
        for cand in raw.get(family, []):
            signal_date = _as_date(cand["signal_date"])
            if signal_date != asof:
                counts[family]["stale_signal_bar"] += 1
                continue
            df = prices.get(cand["symbol"])
            if df is None or df.empty:
                counts[family]["missing_signal_bar"] += 1
                continue
            if asof not in set(df.index.date):
                counts[family]["stale_signal_bar"] += 1
                continue
            geom = _provisional_geometry(
                df,
                asof,
                atr_window,
                stop_atr_multiple=float(geometry[family]["stop_atr_multiple"]),
                target_atr_multiple=float(geometry[family]["target_atr_multiple"]),
            )
            if geom is None:
                counts[family]["invalid_geometry"] += 1
                continue
            valid.append({**cand, "_forward_geometry": geom})
        return valid

    h2_candidates = sorted(
        _validated("h2"), key=lambda c: (c["signal_date"], c["symbol"])
    )
    h1_candidates = sorted(_validated("h1"), key=_rank_key_h1)

    queued: list[dict] = []
    skipped: list[dict] = []
    embargoed_facts: set[tuple[str, str, dt.date]] = set()
    queues = {
        "shared": h2_candidates + h1_candidates,
        "h1solo": h1_candidates,
    }
    existing_by_book = {
        book: [
            rec
            for rec in ledger.signals(asof)
            if rec.get("book") == book
            and rec.get("kind") in {"candidate", "skip"}
        ]
        for book in queues
    }

    # A normal crash can only leave a prefix of each deterministic book walk.
    # Refuse to continue if the cache/source changed enough that the journal
    # no longer describes such a prefix; guessing would alter slot, sizing,
    # or throttle outcomes.
    for book, queue in queues.items():
        expected_ids = [
            entry_id(
                book,
                cand["family"],
                cand["symbol"],
                _as_date(cand["signal_date"]),
                strategy_version=ledger.strategy_version,
            )
            for cand in queue
        ]
        actual_ids = [rec["entry_id"] for rec in existing_by_book[book]]
        if actual_ids != expected_ids[: len(actual_ids)]:
            raise RuntimeError(
                f"cannot resume {book} signal walk for {asof}: "
                "journaled outcomes are not a deterministic queue prefix"
            )

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
        existing = {
            rec["entry_id"]: rec for rec in existing_by_book[book]
        }

        for cand in queue:
            symbol = cand["symbol"]
            family = cand["family"]
            signal_date = _as_date(cand["signal_date"])
            eid = entry_id(
                book,
                family,
                symbol,
                signal_date,
                strategy_version=ledger.strategy_version,
            )

            if eid in existing:
                rec = existing[eid]
                if rec["kind"] == "candidate":
                    queued.append(rec)
                    counts[family]["queued"] += 1
                    provisional_open.append({"symbol": symbol, "family": family})
                    provisional_notional += rec["qty"] * rec["close_sig"]
                else:
                    skipped.append(rec)
                    reason = rec["reason"]
                    if reason == "embargo":
                        fact_id = (family, symbol, signal_date)
                        if fact_id not in embargoed_facts:
                            counts[family]["embargoed"] += 1
                            embargoed_facts.add(fact_id)
                    else:
                        reasons = counts[family]["skipped_by_reason"]
                        reasons[reason] = reasons.get(reason, 0) + 1
                continue

            if catalyst.catalyst_within(symbol, next_session, 2, "block_entry") is not None:
                fact_id = (family, symbol, signal_date)
                if fact_id not in embargoed_facts:
                    counts[family]["embargoed"] += 1
                    embargoed_facts.add(fact_id)
                skipped.append(
                    _append_skip(ledger, book, family, eid, asof, symbol, "embargo")
                )
                continue

            close_sig, atr_sig, stop, target = cand["_forward_geometry"]

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
                reasons = counts[family]["skipped_by_reason"]
                reasons[reason] = reasons.get(reason, 0) + 1
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
                "stop_atr_multiple": float(
                    geometry[family]["stop_atr_multiple"]
                ),
                "target_atr_multiple": float(
                    geometry[family]["target_atr_multiple"]
                ),
                **_version_fact(ledger),
            }
            if family == "h1":
                rec["is_seed"] = cand["is_seed"]
                rec["rsi2_at_trigger"] = cand["rsi2_at_trigger"]
                rec["reclaim_wait_sessions"] = cand["reclaim_wait_sessions"]

            ledger.append_signal(rec)
            queued.append(rec)
            counts[family]["queued"] += 1

            provisional_open.append({"symbol": symbol, "family": family})
            provisional_notional += qty * close_sig

    _walk("shared", queues["shared"], enforce_throttle=True)
    _walk("h1solo", queues["h1solo"], enforce_throttle=True)

    summary = deepcopy(summary_context) if summary_context is not None else {}
    summary["families"] = counts
    summary["signal_outcome"] = classify_signal_outcome(counts, complete=True)
    if ledger.strategy_version is not None:
        summary["strategy_version"] = ledger.strategy_version
    if summary_context is not None:
        runtimes = summary.setdefault("runtime_seconds", {})
        runtimes["signals"] = round(time.perf_counter() - signal_started, 6)
    ledger.append_signal(
        {
            "kind": "signals_done",
            "book": "shared",
            "entry_id": None,
            "signal_date": asof.isoformat(),
            "date": asof.isoformat(),
            "summary": summary,
            **_version_fact(ledger),
        }
    )

    return {"queued": queued, "skipped": skipped, "counts": counts}


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
        **_version_fact(ledger),
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
                **_version_fact(ledger),
            }
        )

    return missing
