"""H2 event collection: earnings-reaction drift (PEAD price-proxy), per
docs/preregs/2026-07-12_h2-pead.md. The surprise is proxied from price/volume
alone (no fundamentals): the first post-report session whose volume expands
>= 1.5x its trailing 20-session median is the reaction session R; its total
return close(R)/close(R-1) - 1 is the score. Events scoring in the causal
trailing-252-session top decile are traded long, entered after R (never
before), so the standing pre-earnings entry embargo is never in tension.

Entry-A (day2_open, primary) reuses `sts.study.h3_events._simulate_event`
verbatim (config_name "h2_pead") -- the identical ATR stop/target +
`risk.manage_bar` walk as H1/H3. Entry-B (pullback, descriptive only) is a
resting-limit variant implemented locally; see `_collect_pullback` for its
fill/abort rules and the descriptive-only intrabar-ambiguity caveat.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

from sts import risk
from sts.catalyst import CatalystCalendar
from sts.study.h1_events import _PARAM_DEFAULTS as _RISK_DEFAULTS
from sts.study.h1_events import cost_r
from sts.study.h3_events import _simulate_event

_PARAM_DEFAULTS = {
    "vol_multiple": 1.5,
    "median_window": 20,
    "decile_min_trailing": 100,
    "decile_pct": 10,
    "pullback_scan_sessions": 3,
    **_RISK_DEFAULTS,
}


def load_earnings_dates(path: Path, today: dt.date | None = None) -> dict[str, list[dt.date]]:
    """Past earnings dates only, from `cache/catalysts/earnings.json`'s
    `{"symbols": {SYM: {"dates": [...]}}}` shape. `today` defaults to the
    last completed session (future/estimated dates are never usable)."""
    if today is None:
        from sts.calendar import last_completed_session

        today = last_completed_session()
    path = Path(path)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    out: dict[str, list[dt.date]] = {}
    for symbol, entry in raw.get("symbols", {}).items():
        dates: list[dt.date] = []
        for d in entry.get("dates", []):
            try:
                dd = dt.date.fromisoformat(d)
            except ValueError:
                continue
            if dd <= today:
                dates.append(dd)
        if dates:
            out[symbol.upper()] = sorted(dates)
    return out


def build_reaction_events(
    prices: dict[str, pd.DataFrame],
    earnings_dates: dict[str, list[dt.date]],
    session_index: pd.DatetimeIndex | None,
    params: dict | None = None,
) -> list[dict]:
    """One event per (symbol, earnings date) that clears the reaction-session
    volume-expansion rule (prereg rule 1). `session_index` is the master
    session axis (e.g. SPY's index passed by the runner); it is used only as
    a defensive cross-check that the candidate reaction session lands on a
    recognized master session, guarding against a symbol-index that has
    drifted from the calendar. Candidates S0 (first symbol session >= d) and
    S1 (the next symbol session) are evaluated in that order; the first with
    volume >= `vol_multiple` x the median of the `median_window` sessions
    strictly before it wins as R. Requires >= `median_window` prior sessions
    to even attempt the check; if neither candidate qualifies, the report is
    dropped entirely (never emitted)."""
    p = {**_PARAM_DEFAULTS, **(params or {})}
    session_set = set(session_index.date) if session_index is not None else None

    events: list[dict] = []
    for symbol in sorted(earnings_dates):
        df = prices.get(symbol)
        if df is None or df.empty:
            continue
        idx = df.index
        vol = df["volume"]
        close = df["close"]
        openp = df["open"]
        n = len(idx)
        for d in earnings_dates[symbol]:
            pos0 = idx.searchsorted(pd.Timestamp(d), side="left")
            if pos0 >= n:
                continue
            candidates = [pos0] if pos0 + 1 >= n else [pos0, pos0 + 1]
            r_pos = None
            for c in candidates:
                if c < p["median_window"]:
                    continue
                trailing = vol.iloc[c - p["median_window"] : c]
                med = trailing.median()
                if med and med > 0 and vol.iloc[c] >= p["vol_multiple"] * med:
                    r_pos = c
                    break
            if r_pos is None or r_pos - 1 < 0:
                continue
            if session_set is not None and idx[r_pos].date() not in session_set:
                continue
            prior_close = float(close.iloc[r_pos - 1])
            r_close = float(close.iloc[r_pos])
            r_open = float(openp.iloc[r_pos])
            if prior_close <= 0 or r_open <= 0:
                continue
            trailing_vol = vol.iloc[r_pos - p["median_window"] : r_pos]
            med_vol = float(trailing_vol.median())
            events.append(
                {
                    "symbol": symbol,
                    "signal_date": idx[r_pos].date(),
                    "earnings_date": d,
                    "score": r_close / prior_close - 1.0,
                    "gap": r_open / prior_close - 1.0,
                    "intraday": r_close / r_open - 1.0,
                    "vol_ratio": float(vol.iloc[r_pos]) / med_vol if med_vol > 0 else None,
                }
            )
    events.sort(key=lambda e: (e["signal_date"], e["symbol"]))
    return events


def assign_deciles(
    events: list[dict], session_index: pd.DatetimeIndex, params: dict | None = None
) -> list[dict]:
    """Causal decile flagging: an event's comparison set is every event (any
    symbol) whose `signal_date` lies within the 252 sessions strictly before
    this event's own signal session, per `session_index` positions. Requires
    >= `decile_min_trailing` comparison events, else `decile_flag` is None
    (skipped -- no lookahead, no within-quarter peeking). `decile_flag` is
    "top" at/above the 90th percentile of the comparison scores, "bottom"
    at/below the 10th, else None."""
    p = {**_PARAM_DEFAULTS, **(params or {})}
    pos_by_date = {ts.date(): i for i, ts in enumerate(session_index)}

    positions = [pos_by_date.get(e["signal_date"]) for e in events]
    pool = sorted(
        ((pos, e["score"]) for pos, e in zip(positions, events) if pos is not None),
        key=lambda t: t[0],
    )
    pool_pos = np.array([t[0] for t in pool], dtype=float)
    pool_score = np.array([t[1] for t in pool], dtype=float)

    out: list[dict] = []
    for pos, e in zip(positions, events):
        row = dict(e)
        if pos is None:
            row["decile_flag"] = None
            row["n_trailing_comparison"] = 0
            out.append(row)
            continue
        lo, hi = pos - 252, pos - 1
        left = int(np.searchsorted(pool_pos, lo, side="left"))
        right = int(np.searchsorted(pool_pos, hi, side="right"))
        comparison = pool_score[left:right]
        n_comp = int(comparison.size)
        row["n_trailing_comparison"] = n_comp
        if n_comp < p["decile_min_trailing"]:
            row["decile_flag"] = None
        else:
            p90 = float(np.percentile(comparison, 100 - p["decile_pct"]))
            p10 = float(np.percentile(comparison, p["decile_pct"]))
            if e["score"] >= p90:
                row["decile_flag"] = "top"
            elif e["score"] <= p10:
                row["decile_flag"] = "bottom"
            else:
                row["decile_flag"] = None
        out.append(row)
    return out


def _collect_pullback(
    prices: dict[str, pd.DataFrame],
    events: list[dict],
    cost_arms: dict[str, tuple[float, float]],
    catalyst_calendar: CatalystCalendar,
    p: dict,
) -> list[dict]:
    """Entry-B, descriptive only: resting limit at close(R), scanned over the
    next `pullback_scan_sessions` sessions. Fill priority per session: open
    <= limit fills at the open; else low <= limit fills at the limit. The
    scan aborts (no event, not a loss) if a session CLOSES below low(R)
    before a fill. No fill within the window -> no event. On fill, stop/
    target come from the SIGNAL bar's ATR(14) anchored at the actual fill
    price, and the `risk.manage_bar` walk is run starting at the FILL bar
    itself (not the bar after) -- risk is treated as active from the entry
    bar per the h1/h3 convention, which here means the fill bar's own OHLC is
    also used for exit checks. This is a known intrabar-ambiguity
    simplification, descriptive-only, never used for the H2 verdict."""
    rows: list[dict] = []
    for ev in events:
        symbol = ev["symbol"]
        df = prices.get(symbol)
        if df is None or df.empty:
            continue
        idx = df.index
        iloc_of = {d: i for i, d in enumerate(idx.date)}
        r_pos = iloc_of.get(ev["signal_date"])
        if r_pos is None:
            continue
        atr_series = risk.atr(df, window=p["atr_window"])
        atr_value = atr_series.iloc[r_pos]
        if not np.isfinite(atr_value):
            continue
        low_r = float(df["low"].iloc[r_pos])
        limit = float(df["close"].iloc[r_pos])

        fill_pos, fill_price = None, None
        for s in range(r_pos + 1, min(r_pos + 1 + p["pullback_scan_sessions"], len(idx))):
            o, lo, cl = float(df["open"].iloc[s]), float(df["low"].iloc[s]), float(df["close"].iloc[s])
            if o <= limit:
                fill_pos, fill_price = s, o
                break
            if lo <= limit:
                fill_pos, fill_price = s, limit
                break
            if cl < low_r:
                break  # abort: closed below R's low before filling
        if fill_pos is None:
            continue

        stop = risk.atr_stop(fill_price, float(atr_value), p["atr_stop_multiple"])
        target = risk.atr_target(fill_price, float(atr_value), p["atr_target_multiple"])
        entry_date = idx[fill_pos].date()
        try:
            pos = risk.Position(
                symbol=symbol, entry=fill_price, shares=1, stop=stop, target=target,
                opened=entry_date, config="h2_pead_pullback",
            )
        except (ValueError, risk.RuleViolation):
            continue
        if catalyst_calendar.catalyst_within(symbol, entry_date, 2, "block_entry") is not None:
            continue

        j = fill_pos
        sim: dict | None = None
        while j < len(idx):
            row = df.iloc[j]
            exits = risk.manage_bar(
                pos, float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
            )
            if exits:
                reason, price, _shares = exits[0]
                r = risk.r_multiple(fill_price, price, stop)
                sim = {
                    "entry": fill_price, "stop": stop, "r_gross": r,
                    "hold_sessions": j - fill_pos, "censored": False,
                    "exit_reason": reason, "entry_date": entry_date,
                }
                break
            j += 1
        if sim is None:
            exit_price = float(df["close"].iloc[-1])
            r = risk.r_multiple(fill_price, exit_price, stop)
            sim = {
                "entry": fill_price, "stop": stop, "r_gross": r,
                "hold_sessions": len(idx) - 1 - fill_pos, "censored": True,
                "exit_reason": "censored", "entry_date": entry_date,
            }

        out = {"symbol": symbol, **{k: v for k, v in ev.items() if k not in ("symbol",)}, **sim}
        for arm_name, (bps, fee) in cost_arms.items():
            out[f"r_net_{arm_name}"] = sim["r_gross"] - cost_r(sim["entry"], sim["stop"], bps, fee)
        rows.append(out)
    return rows


def collect_events(
    prices: dict[str, pd.DataFrame],
    events: list[dict],
    start: dt.date,
    end: dt.date,
    cost_arms: dict[str, tuple[float, float]],
    catalyst_calendar: CatalystCalendar | None = None,
    entry_mode: str = "day2_open",
    risk_params: dict | None = None,
) -> list[dict]:
    """Per-event exit-simmed rows for one H2 cell's already-selected `events`
    (caller filters by decile tail; this function does not re-filter on
    `decile_flag`). Only `signal_date in [start, end)` is applied here.
    `entry_mode` "day2_open" (primary) reuses h3_events._simulate_event
    (config_name "h2_pead") -- entry = open of R+1, stop/target from ATR(14)
    at R. "pullback" (descriptive) is `_collect_pullback` above. Both apply
    the standard skip-not-loss 2-session pre-earnings entry embargo."""
    p = {**_PARAM_DEFAULTS, **(risk_params or {})}
    cal = catalyst_calendar if catalyst_calendar is not None else CatalystCalendar.load()
    windowed = [e for e in events if start <= e["signal_date"] < end]

    if entry_mode == "pullback":
        return _collect_pullback(prices, windowed, cost_arms, cal, p)
    if entry_mode != "day2_open":
        raise ValueError(f"unknown entry_mode {entry_mode!r}")

    rows: list[dict] = []
    for ev in windowed:
        symbol = ev["symbol"]
        df = prices.get(symbol)
        if df is None or df.empty:
            continue
        idx = df.index
        iloc_of = {d: i for i, d in enumerate(idx.date)}
        sig_iloc = iloc_of.get(ev["signal_date"])
        if sig_iloc is None:
            continue
        atr_series = risk.atr(df, window=p["atr_window"])
        sim = _simulate_event(symbol, df, sig_iloc, atr_series, p, "h2_pead")
        if sim is None:
            continue
        if cal.catalyst_within(symbol, sim["entry_date"], 2, "block_entry") is not None:
            continue
        row = {**{k: v for k, v in ev.items() if k != "symbol"}, "symbol": symbol, **sim}
        for arm_name, (bps, fee) in cost_arms.items():
            row[f"r_net_{arm_name}"] = sim["r_gross"] - cost_r(sim["entry"], sim["stop"], bps, fee)
        rows.append(row)
    return rows


def raw_forward_returns_from_events(
    prices: dict[str, pd.DataFrame], events: list[dict], horizons: tuple[int, ...] = (5, 10, 15)
) -> dict:
    """Layer (a): exit-free forward returns close(R+h)/close(R) - 1 for the
    given `events`, per horizon h. Events lacking h future bars are skipped
    for that horizon only. Empty-safe: n=0, mean/median=None when no
    observations exist for a horizon."""
    by_horizon: dict[int, list[float]] = {h: [] for h in horizons}
    for ev in events:
        df = prices.get(ev["symbol"])
        if df is None or df.empty:
            continue
        iloc_of = {d: i for i, d in enumerate(df.index.date)}
        sig_iloc = iloc_of.get(ev["signal_date"])
        if sig_iloc is None:
            continue
        close = df["close"]
        r0 = float(close.iloc[sig_iloc])
        if r0 <= 0:
            continue
        for h in horizons:
            target_iloc = sig_iloc + h
            if target_iloc >= len(df):
                continue
            by_horizon[h].append(float(close.iloc[target_iloc]) / r0 - 1.0)

    out = {}
    for h, vals in by_horizon.items():
        n = len(vals)
        arr = np.asarray(vals, dtype=float)
        out[h] = {
            "n": n,
            "mean_return": float(arr.mean()) if n else None,
            "median_return": float(np.median(arr)) if n else None,
        }
    return {"by_horizon": out}
