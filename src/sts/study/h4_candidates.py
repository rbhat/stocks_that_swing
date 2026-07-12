"""Phase-4 per-family candidate adapters: turn each hypothesis family's
Phase-3 study wiring into the uniform candidate-dict list
`sts.portfolio.simulate_portfolio` consumes.

Thin adapters only — every stop/target/entry geometry is imported from the
existing study modules (`sts.study.h1_events.entry_geometry`, extracted
there for exactly this reuse), never re-derived here. Detector calls and
decile/PEAD selection reuse `sts.study.h2_events` / `sts.signals` verbatim,
same as the Phase-3 runners.

`FAMILY_PARAMS` holds each family's LOCKED primary-cell params, copied
verbatim from the family's prereg / Phase-3 runner (never edit these without
also updating the cited prereg):

- H1: docs/preregs/2026-07-11_h1-trend-pullback.md primary cell
  ("trend_pullback"), params = `TREND_PULLBACK_DEFAULTS` (detector) +
  `sts.study.h1_events._PARAM_DEFAULTS` (ATR window 14, stop/target multiple
  2.0 each) — see `scripts/run_h1_study.py`.
- H3: docs/preregs/2026-07-12_h3-regeometried-breakout.md primary cell
  "avwap_squeeze_seed" — the `vol_squeeze` detector on `SQUEEZE_DEFAULTS`
  gated by `trend_filter="avwap_252_above"` — see
  `scripts/run_h3_study.py` `CELLS["avwap_squeeze_seed"]`.
- H2: docs/preregs/2026-07-12_h2-pead.md primary cell
  "top_decile_day2_open" — the day2_open entry mode on the top decile of
  the causal price/volume PEAD proxy — see `scripts/run_h2_study.py`
  `PRIMARY_CELL`.

Catalyst embargo: ALL THREE families apply the standing 2-session
pre-earnings entry embargo (`block_entry`), matching their Phase-3 event
collection exactly — H2's locked prereg (2026-07-12_h2-pead.md, "Catalyst
rule") locks the embargo for H2 too, and `h2_events` applies it at both
collection and simulation. An H2 entry sits ~a quarter away from the NEXT
earnings date, so the filter rarely binds, but Phase 4 must not diverge
from the locked family definition (independent-review finding F1,
2026-07-12).
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from sts import risk
from sts.catalyst import EARNINGS_PATH, CatalystCalendar
from sts.signals import resolve_detector
from sts.signals.squeeze import DEFAULTS as SQUEEZE_DEFAULTS
from sts.signals.trend_pullback import DEFAULTS as TREND_PULLBACK_DEFAULTS
from sts.signals.trend_pullback import detect as detect_trend_pullback
from sts.study.h1_events import _PARAM_DEFAULTS as _RISK_DEFAULTS
from sts.study.h1_events import entry_geometry
from sts.study.h2_events import _PARAM_DEFAULTS as _H2_PARAM_DEFAULTS
from sts.study.h2_events import assign_deciles, build_reaction_events, load_earnings_dates

FAMILY_PARAMS: dict[str, dict] = {
    "h1": {
        "config_name": "trend_pullback",
        "detector_params": dict(TREND_PULLBACK_DEFAULTS),
        "risk_params": dict(_RISK_DEFAULTS),
    },
    "h3": {
        "config_name": "vol_squeeze",
        "detector_params": {**SQUEEZE_DEFAULTS, "trend_filter": "avwap_252_above"},
        "risk_params": dict(_RISK_DEFAULTS),
    },
    "h2": {
        "entry_mode": "day2_open",
        "decile_flag": "top",
        "risk_params": dict(_H2_PARAM_DEFAULTS),
    },
}


def _candidate(symbol: str, family: str, signal_date: dt.date, geo: dict) -> dict:
    return {
        "symbol": symbol,
        "signal_date": signal_date,
        "entry_date": geo["entry_date"],
        "entry": geo["entry"],
        "stop": geo["stop"],
        "target": geo["target"],
        "family": family,
    }


def _h1_candidates(
    prices: dict[str, pd.DataFrame],
    oos_start: dt.date,
    oos_end: dt.date,
    catalyst: CatalystCalendar,
    risk_params: dict | None = None,
) -> list[dict]:
    detector_params = FAMILY_PARAMS["h1"]["detector_params"]
    p = risk_params if risk_params is not None else FAMILY_PARAMS["h1"]["risk_params"]
    out: list[dict] = []
    for symbol in sorted(prices):
        df = prices[symbol]
        if df is None or df.empty:
            continue
        iloc_of = {d: i for i, d in enumerate(df.index.date)}
        atr_series = risk.atr(df, window=p["atr_window"])
        for ev in detect_trend_pullback(symbol, df, detector_params, "trend_pullback"):
            if ev.date < oos_start or ev.date >= oos_end:
                continue
            sig_iloc = iloc_of.get(ev.date)
            if sig_iloc is None:
                continue
            geo = entry_geometry(df, sig_iloc, atr_series, p)
            if geo is None:
                continue
            if catalyst.catalyst_within(symbol, geo["entry_date"], 2, "block_entry") is not None:
                continue
            out.append(_candidate(symbol, "h1", ev.date, geo))
    return out


def _h3_candidates(
    prices: dict[str, pd.DataFrame],
    oos_start: dt.date,
    oos_end: dt.date,
    catalyst: CatalystCalendar,
    risk_params: dict | None = None,
) -> list[dict]:
    config_name = FAMILY_PARAMS["h3"]["config_name"]
    detector_params = FAMILY_PARAMS["h3"]["detector_params"]
    p = risk_params if risk_params is not None else FAMILY_PARAMS["h3"]["risk_params"]
    detect = resolve_detector(config_name)
    out: list[dict] = []
    for symbol in sorted(prices):
        df = prices[symbol]
        if df is None or df.empty:
            continue
        iloc_of = {d: i for i, d in enumerate(df.index.date)}
        atr_series = risk.atr(df, window=p["atr_window"])
        for ev in detect(symbol, df, detector_params, config_name):
            if ev.date < oos_start or ev.date >= oos_end:
                continue
            sig_iloc = iloc_of.get(ev.date)
            if sig_iloc is None:
                continue
            geo = entry_geometry(df, sig_iloc, atr_series, p)
            if geo is None:
                continue
            if catalyst.catalyst_within(symbol, geo["entry_date"], 2, "block_entry") is not None:
                continue
            out.append(_candidate(symbol, "h3", ev.date, geo))
    return out


def _h2_candidates(
    prices: dict[str, pd.DataFrame],
    oos_start: dt.date,
    oos_end: dt.date,
    catalyst: CatalystCalendar,
    risk_params: dict | None = None,
) -> list[dict]:
    p = risk_params if risk_params is not None else FAMILY_PARAMS["h2"]["risk_params"]
    spy_df = prices.get("SPY")
    session_index = spy_df.index if spy_df is not None and not spy_df.empty else None

    earnings_dates = load_earnings_dates(EARNINGS_PATH)
    events = build_reaction_events(prices, earnings_dates, session_index, p)
    if session_index is not None:
        events = assign_deciles(events, session_index, p)
    else:
        events = [{**e, "decile_flag": None} for e in events]

    wanted_flag = FAMILY_PARAMS["h2"]["decile_flag"]
    out: list[dict] = []
    for ev in events:
        if ev.get("decile_flag") != wanted_flag:
            continue
        if ev["signal_date"] < oos_start or ev["signal_date"] >= oos_end:
            continue
        symbol = ev["symbol"]
        df = prices.get(symbol)
        if df is None or df.empty:
            continue
        iloc_of = {d: i for i, d in enumerate(df.index.date)}
        sig_iloc = iloc_of.get(ev["signal_date"])
        if sig_iloc is None:
            continue
        atr_series = risk.atr(df, window=p["atr_window"])
        geo = entry_geometry(df, sig_iloc, atr_series, p)
        if geo is None:
            continue
        if catalyst.catalyst_within(symbol, geo["entry_date"], 2, "block_entry") is not None:
            continue
        out.append(_candidate(symbol, "h2", ev["signal_date"], geo))
    return out


_ADAPTERS = {"h1": _h1_candidates, "h3": _h3_candidates, "h2": _h2_candidates}


def candidates_for(
    family: str,
    prices: dict[str, pd.DataFrame],
    oos_start: dt.date,
    oos_end: dt.date,
    catalyst: CatalystCalendar | None = None,
    risk_params: dict | None = None,
) -> list[dict]:
    """Uniform Task-1 candidate dicts for `family` in {"h1", "h3", "h2"} over
    `prices`, event `signal_date` in `[oos_start, oos_end)`. `catalyst`
    defaults to `CatalystCalendar.load()`. `risk_params`, if given, overrides
    `FAMILY_PARAMS[family]["risk_params"]` for this call only — used by the
    Phase-4 runner's jitter arms; the detector params and decile/entry-mode
    selection stay locked regardless (jitter only ever perturbs the risk
    geometry, per the plan's jitter_grid scope)."""
    if family not in _ADAPTERS:
        raise ValueError(f"unknown family {family!r}, expected one of {sorted(_ADAPTERS)}")
    cal = catalyst if catalyst is not None else CatalystCalendar.load()
    return _ADAPTERS[family](prices, oos_start, oos_end, cal, risk_params)
