"""Daily-bar backtest engine.

Replays `stm.signals.detect_all` signals through the exact same risk rules
used live (`stm.risk`: caps, stops, targets, `manage_bar`) — nothing here
reimplements sizing or exit math. Frictions (commission + slippage) and a
strict next-bar-fill rule keep the simulation honest:

- Signals fire on session `d`; the fill happens at session `d+1`'s open.
- A position opened at session `t` is first managed (stop/target checks) at
  `t+1` — a same-day stop/target hit is a documented conservatism, not a bug.
- Exits are checked before entries on every session, so a symbol that closes
  out mid-loop can, in principle, re-enter the same day on a fresh signal.
- Everything is deterministic: no randomness in the core loop (the `seed` is
  recorded for Monte Carlo work in a later phase, unused here).

Phase 9 catalyst guard (optional, parity with stm.forward.ForwardEngine):
when `run_backtest` is given a `catalyst_calendar` and a signal's `params`
carry a `catalyst_guard` dict, entries within `entry_embargo_sessions` of a
known catalyst are skipped (fail-open: no calendar, or no guard on the
config, behaves exactly as before), and open positions carrying a guard are
flattened at the slipped open — reason `"catalyst"` — once a catalyst falls
within `exit_before_sessions`, in place of that bar's normal `manage_bar`
check. See CLAUDE.md for the hard rules this engine must uphold.

§7 vol-scaled sizing study (optional, backtest-only): when `run_backtest` is
given a `position_sizer` callable, it is combined via `min()` with the
existing fixed-cap share count at the sizing site only, signature
`(symbol, fill_price, session_date, equity) -> max_shares_allowed`. It can
only ever shrink the fixed-cap share count, never grow it. This is a
study-only hook for the volatility-scaled position sizing A/B
(next_signals.md §7); `stm.forward.ForwardEngine` has NO equivalent — the
forward/config surface is that study's PROCEED deliverable, behind its own
independent review — and `stm.risk` sizing (MAX_POSITION_PCT/
MAX_DEPLOYED_PCT) is untouched. Inert when omitted (default None):
byte-identical to today for every existing caller.

Swing redeploy study (optional, backtest-only): when `run_backtest` is given
a `time_exit` dict `{"max_sessions": N}`, a position still open N engine
sessions after entry is flattened in full at that session's slipped open,
reason "time" — in place of that bar's `manage_bar`, the same "exit takes the
whole bar" precedence as the catalyst pre-event exit (checked AFTER the
catalyst exit, BEFORE manage_bar). Fail-open: a non-dict, empty dict, or
non-positive `max_sessions` applies no cap. Per-config override (same
precedent as `catalyst_guard`): a signal's config `params` may carry its own
`time_exit` dict; a valid per-config value overrides the run-level kwarg for
that config's positions, while an absent or malformed (fail-open) per-config
value falls back to the run-level cap. This is the study hook for the
swing capital-velocity A/B (swing_next_signals.md Study 0 → redeploy gate);
like `position_sizer` it has NO `stm.forward.ForwardEngine` equivalent (forward
parity is a later Phase-1 concern gated on the study's PROCEED) and `stm.risk`
is untouched. Inert by default: no registry config carries `time_exit` and the
run-level kwarg defaults to None, so behavior is byte-identical to today for
every existing caller.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from sts import risk
from sts.models import new_trade_record
from sts.signals import detect_all

logger = logging.getLogger(__name__)


@dataclass
class BacktestParams:
    start: dt.date | None = None
    end: dt.date | None = None
    commission_per_order: float = 1.0      # deducted from cash per fill (entry and each exit slice)
    slippage_bps: float = 5.0              # buys fill at price*(1+bps/1e4), sells at price*(1-bps/1e4)
    seed: int = 42                          # reserved for Monte Carlo (Phase 3); core engine uses NO randomness
    min_notional: float = 500.0             # skip entries smaller than this; fixed commissions must not dominate a position
    stop_pct: float = 0.30
    runner_fraction: float = 0.5
    fib_ratios: tuple = (1.272, 1.618)
    min_target_r: float = 1.0              # threaded into risk.fib_targets; see its docstring


@dataclass
class BacktestResult:
    trades: list[dict]          # models.TRADE_FIELDS-complete, mode="backtest", source=f"backtest:seed={seed}"
    equity_curve: pd.Series     # daily mark-to-market at close, indexed by session
    metrics: dict
    configs: dict               # exact configs used
    params: BacktestParams


def _slip_buy(price: float, bps: float) -> float:
    return price * (1 + bps / 1e4)


def _slip_sell(price: float, bps: float) -> float:
    return price * (1 - bps / 1e4)


def _parse_time_cap(obj) -> int | None:
    """Fail-open time_exit parse: {"max_sessions": N>0} -> int(N), anything
    else -> None."""
    if not isinstance(obj, dict):
        return None
    mc = obj.get("max_sessions")
    if isinstance(mc, (int, float)) and not isinstance(mc, bool) and mc > 0:
        return int(mc)
    return None


def _empty_metrics(
    total_return_pct: float = 0.0, catalyst_blocks: int = 0, catalyst_exits: int = 0
) -> dict:
    return {
        "n_trades": 0,
        "win_rate": 0.0,
        "expectancy_usd": 0.0,
        "expectancy_r": 0.0,
        "avg_r_win": 0.0,
        "avg_r_loss": 0.0,
        "max_drawdown_pct": 0.0,
        "total_return_pct": total_return_pct,
        "avg_holding_days": 0.0,
        "exposure_avg": 0.0,
        "catalyst_blocks": catalyst_blocks,
        "catalyst_exits": catalyst_exits,
    }


def _max_drawdown_pct(eq: pd.Series) -> float:
    if eq.empty:
        return 0.0
    running_max = eq.cummax()
    dd = (running_max - eq) / running_max
    return float(dd.max() * 100.0)


def _compute_metrics(
    trades: list[dict],
    eq: pd.Series,
    exposure_samples: list[float],
    catalyst_blocks: int = 0,
    catalyst_exits: int = 0,
) -> dict:
    total_return_pct = (
        (eq.iloc[-1] / risk.START_CAPITAL - 1.0) * 100.0 if not eq.empty else 0.0
    )
    if not trades:
        return _empty_metrics(total_return_pct, catalyst_blocks, catalyst_exits)

    n = len(trades)
    pnl = [t["pnl_usd"] for t in trades]
    r = [t["r_multiple"] for t in trades]
    wins_mask = [p > 0 for p in pnl]
    win_r = [rr for rr, w in zip(r, wins_mask) if w]
    loss_r = [rr for rr, w in zip(r, wins_mask) if not w]

    return {
        "n_trades": n,
        "win_rate": sum(wins_mask) / n,
        "expectancy_usd": sum(pnl) / n,
        "expectancy_r": sum(r) / n,
        "avg_r_win": (sum(win_r) / len(win_r)) if win_r else 0.0,
        "avg_r_loss": (sum(loss_r) / len(loss_r)) if loss_r else 0.0,
        "max_drawdown_pct": _max_drawdown_pct(eq),
        "total_return_pct": total_return_pct,
        "avg_holding_days": sum(t["holding_days"] for t in trades) / n,
        "exposure_avg": (sum(exposure_samples) / len(exposure_samples)) if exposure_samples else 0.0,
        "catalyst_blocks": catalyst_blocks,
        "catalyst_exits": catalyst_exits,
    }


def _precompute_signals(
    prices: dict[str, pd.DataFrame], configs: dict[str, dict], start: dt.date | None, end: dt.date | None
) -> dict[dt.date, list]:
    """Run detect_all per symbol on the full frame (truncated only at `end`
    for warmup efficiency), then keep events whose fire date falls in
    [start, end]. Detectors are already no-lookahead, so pre-start bars are
    legal warmup context. Returns events grouped by fire date."""
    signals_by_date: dict[dt.date, list] = {}
    for symbol, df in prices.items():
        df_for_detect = df if end is None else df[df.index.date <= end]
        events = detect_all(symbol, df_for_detect, configs)
        for e in events:
            if start is not None and e.date < start:
                continue
            if end is not None and e.date > end:
                continue
            signals_by_date.setdefault(e.date, []).append(e)
    return signals_by_date


def _session_universe(
    prices: dict[str, pd.DataFrame], start: dt.date | None, end: dt.date | None
) -> list[pd.Timestamp]:
    sessions: set[pd.Timestamp] = set()
    for df in prices.values():
        for ts in df.index:
            d = ts.date()
            if start is not None and d < start:
                continue
            if end is not None and d > end:
                continue
            sessions.add(ts)
    return sorted(sessions)


def run_backtest(
    prices: dict[str, pd.DataFrame],
    configs: dict[str, dict],
    params: BacktestParams,
    catalyst_calendar=None,
    position_sizer: Callable[[str, float, dt.date, float], int] | None = None,
    time_exit: dict | None = None,
) -> BacktestResult:
    """`catalyst_calendar` (stm.catalyst.CatalystCalendar or None, default
    None): when present, and a fired signal's `params` carry a
    `catalyst_guard` dict, gates entries and pre-event exits per the Phase 9
    parity contract (see module docstring). Omitting it reproduces today's
    behavior exactly for every existing caller.

    `position_sizer` (optional, default None): a backtest-only sizing hook
    for the §7 vol-sizing study, signature `(symbol, fill_price,
    session_date, equity) -> max_shares_allowed`. When given, its return
    value is combined via `min()` with the existing fixed-cap share count at
    the sizing site only — every downstream step (the `shares <= 0` guard,
    the min_notional check, `orig_shares`, the cash-overdraw refund) then
    uses the final, already-capped `shares`. Inert when None: byte-identical
    to today for every existing caller. `stm.forward.ForwardEngine` has NO
    equivalent hook — the forward/config surface is this study's PROCEED
    deliverable, gated behind its own independent review; `stm.risk` sizing
    is untouched, this hook sits strictly under it.

    `time_exit` (optional dict, default None): the swing redeploy-study hook,
    `{"max_sessions": N}` — flatten a position N engine sessions after entry at
    the slipped open (reason "time"), checked after the catalyst exit and before
    manage_bar (see module docstring). Fail-open on a bad/empty dict. A signal's
    config `params` may carry its own `time_exit` dict (same precedent as
    `catalyst_guard`): a valid per-config value overrides this kwarg for that
    config's positions, falling back to it when the per-config value is absent
    or malformed. Inert when None and no config carries the key:
    byte-identical to today for every existing caller."""
    start, end = params.start, params.end

    # Swing redeploy hook: parse the run-level `time_exit` once, fail-open
    # (see module docstring). A per-config `time_exit` in a signal's params
    # is parsed the same way at position-open time (below, `open_meta[...
    # ]["time_cap"]`) and overrides this run-level cap for that position;
    # absent/malformed per-config values fall back to it. None here with no
    # config override => byte-identical to today (the `elif` below is dead
    # and open_meta["entry_i"] is written but never read).
    time_cap_sessions = _parse_time_cap(time_exit)

    signals_by_date = _precompute_signals(prices, configs, start, end)
    sessions = _session_universe(prices, start, end)

    if not sessions:
        return BacktestResult(
            trades=[], equity_curve=pd.Series(dtype=float), metrics=_empty_metrics(),
            configs=configs, params=params,
        )

    portfolio = risk.Portfolio()
    last_close: dict[str, float] = {}
    open_meta: dict[str, dict] = {}
    closed_trades: list[dict] = []
    equity_curve: dict[pd.Timestamp, float] = {}
    exposure_samples: list[float] = []
    catalyst_blocks = 0
    catalyst_exits = 0

    def _finalize(symbol: str) -> dict:
        meta = open_meta.pop(symbol)
        entry = meta["entry_price"]
        size = meta["orig_shares"]
        slices = meta["exit_slices"]
        total_shares = sum(s["shares"] for s in slices)
        exit_avg = sum(s["price"] * s["shares"] for s in slices) / total_shares
        exit_reason = slices[-1]["reason"]
        gross_pnl = sum((s["price"] - entry) * s["shares"] for s in slices)
        pnl_usd = gross_pnl - meta["commissions"]
        pnl_pct = pnl_usd / (entry * size)
        r_mult = risk.r_multiple(entry, exit_avg, meta["initial_stop"])
        holding_days = (slices[-1]["date"] - meta["entry_date"]).days
        # pnl_pct is net of commissions (matches what actually landed in
        # cash); r_multiple is gross-of-commission, computed on slipped
        # prices only — that's the 1:2 reward:risk audit basis fib_targets
        # is sized against, and commissions shouldn't move the risk goalpost.
        return new_trade_record(
            mode="backtest",
            source=f"backtest:seed={params.seed}",
            config=meta["config"],
            symbol=symbol,
            direction="long",
            entry_date=meta["entry_date"].isoformat(),
            exit_date=slices[-1]["date"].isoformat(),
            entry=entry,
            size=size,
            stop=meta["initial_stop"],
            targets=meta["targets"],
            exit=exit_avg,
            exit_reason=exit_reason,
            pnl_usd=pnl_usd,
            pnl_pct=pnl_pct,
            r_multiple=r_mult,
            holding_days=holding_days,
        )

    for i, t in enumerate(sessions):
        t_date = t.date()
        prev_t = sessions[i - 1] if i > 0 else None

        # -- a. Exits first, for positions opened before t. --------------
        for symbol in list(portfolio.positions.keys()):
            df = prices[symbol]
            if t not in df.index:
                continue  # halted: skip management, mark uses last known close
            bar = df.loc[t]
            pos = portfolio.positions[symbol]
            meta = open_meta[symbol]
            cap = meta["time_cap"]

            # Pre-event catalyst exit takes priority over manage_bar this
            # bar entirely (parity contract with stm.forward): a guarded
            # position with a catalyst inside exit_before_sessions flattens
            # in full at the slipped open, reason "catalyst".
            guard = meta.get("catalyst_guard")
            catalyst_event = None
            if guard and catalyst_calendar is not None:
                catalyst_event = catalyst_calendar.catalyst_within(
                    symbol, t_date, guard.get("exit_before_sessions", 0), "exit_before"
                )

            if catalyst_event is not None:
                slipped = _slip_sell(float(bar["open"]), params.slippage_bps)
                shares = pos.shares
                portfolio.cash += slipped * shares
                portfolio.cash -= params.commission_per_order
                pos.shares -= shares
                meta["exit_slices"].append(
                    {"price": slipped, "shares": shares, "reason": "catalyst", "date": t_date}
                )
                meta["commissions"] += params.commission_per_order
                catalyst_exits += 1
            elif cap is not None and (i - meta["entry_i"]) >= cap:
                # Swing time-cap: flatten in full at the slipped open, reason
                # "time", in place of manage_bar this bar (catalyst exit still
                # wins above). Age is engine sessions since the fill bar, so
                # cap N flattens at entry_i+N — parity with the study's N-bar cap.
                slipped = _slip_sell(float(bar["open"]), params.slippage_bps)
                shares = pos.shares
                portfolio.cash += slipped * shares
                portfolio.cash -= params.commission_per_order
                pos.shares -= shares
                meta["exit_slices"].append(
                    {"price": slipped, "shares": shares, "reason": "time", "date": t_date}
                )
                meta["commissions"] += params.commission_per_order
            else:
                exits = risk.manage_bar(
                    pos, float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"])
                )
                for reason, price, shares in exits:
                    slipped = _slip_sell(price, params.slippage_bps)
                    portfolio.cash += slipped * shares
                    portfolio.cash -= params.commission_per_order
                    meta["exit_slices"].append(
                        {"price": slipped, "shares": shares, "reason": reason, "date": t_date}
                    )
                    meta["commissions"] += params.commission_per_order

            if pos.shares == 0 and symbol in portfolio.positions:
                del portfolio.positions[symbol]
                closed_trades.append(_finalize(symbol))

        # -- b. Entries: signals fired on the previous session. ----------
        candidates = []
        if prev_t is not None:
            prev_date = prev_t.date()
            todays_signals = sorted(
                signals_by_date.get(prev_date, []), key=lambda e: (e.config_name, e.symbol)
            )
            seen_symbols: set[str] = set()
            for e in todays_signals:
                if e.symbol in seen_symbols:
                    continue
                seen_symbols.add(e.symbol)
                candidates.append(e)

        for e in candidates:
            symbol = e.symbol
            if symbol in portfolio.positions:
                continue  # never average down / no adds
            df = prices[symbol]
            if t not in df.index:
                continue  # no bar to fill on

            guard = e.params.get("catalyst_guard")
            if guard and catalyst_calendar is not None:
                blocked_ev = catalyst_calendar.catalyst_within(
                    symbol, t_date, guard.get("entry_embargo_sessions", 0), "block_entry"
                )
                if blocked_ev is not None:
                    catalyst_blocks += 1
                    logger.debug(
                        "catalyst entry embargo: %s blocked on %s (config %s, event %s on %s)",
                        symbol, t_date, e.config_name, blocked_ev.type, blocked_ev.date,
                    )
                    continue

            raw_open = float(df.loc[t, "open"])
            fill = _slip_buy(raw_open, params.slippage_bps)

            marks = {s: last_close[s] for s in portfolio.positions}
            marks[symbol] = fill
            shares = portfolio.max_affordable_shares(fill, marks)
            if position_sizer is not None:
                equity = portfolio.equity(marks)
                shares = min(shares, max(0, int(position_sizer(symbol, fill, t_date, equity))))
            if shares <= 0:
                logger.debug("zero affordable shares, skipping entry: %s on %s", symbol, t_date)
                continue
            if shares * fill < params.min_notional:
                # A position so small that fixed commissions dominate it is
                # noise, not a trade: a $0.36 notional fill turns a +2R win
                # into pnl_pct ~ -490%, which then poisons every pnl_pct
                # consumer downstream (bootstrap paths, expectancy).
                logger.debug(
                    "notional %.2f below min_notional %.2f, skipping entry: %s on %s",
                    shares * fill, params.min_notional, symbol, t_date,
                )
                continue

            stop = risk.initial_stop(fill, params.stop_pct)
            swing_low = e.trigger_values["swing_low"]
            swing_high = e.trigger_values["swing_high"]
            targets = risk.fib_targets(
                swing_low, swing_high, fill, params.fib_ratios, params.stop_pct, params.min_target_r
            )

            portfolio.open_position(
                symbol, fill, shares, stop, stop, targets,
                opened=t_date, config=e.config_name,
                runner_fraction=params.runner_fraction, prices=marks,
            )
            portfolio.cash -= params.commission_per_order
            if portfolio.cash < -1e-9:
                # Commission would overdraw cash: undo this entry entirely.
                portfolio.cash += params.commission_per_order
                portfolio.cash += fill * shares
                del portfolio.positions[symbol]
                logger.debug(
                    "entry commission would overdraw cash, skipping: %s on %s", symbol, t_date
                )
                continue
            portfolio.cash = max(portfolio.cash, 0.0)

            last_close[symbol] = fill
            # Per-config time_exit override (same precedent as catalyst_guard):
            # a valid config-level cap wins for this position; otherwise fall
            # back to the run-level cap (see module docstring).
            cfg_cap = _parse_time_cap(e.params.get("time_exit"))
            time_cap = cfg_cap if cfg_cap is not None else time_cap_sessions
            open_meta[symbol] = {
                "entry_price": fill,
                "orig_shares": shares,
                "entry_date": t_date,
                "initial_stop": stop,
                "targets": targets,
                "config": e.config_name,
                "exit_slices": [],
                "commissions": params.commission_per_order,
                "catalyst_guard": guard,
                "entry_i": i,   # session index at fill; read only by the time_exit hook
                "time_cap": time_cap,   # per-position cap: config override or run-level fallback
            }

        # -- c. Mark to market at t's close. ------------------------------
        for symbol in portfolio.positions:
            df = prices[symbol]
            if t in df.index:
                last_close[symbol] = float(df.loc[t, "close"])
        marks_close = {s: last_close[s] for s in portfolio.positions}
        eq_t = portfolio.equity(marks_close)
        equity_curve[t] = eq_t
        exposure_samples.append(portfolio.deployed() / eq_t if eq_t > 0 else 0.0)

    # -- Force-close remaining positions at the final bar's close. -------
    # A symbol halted before `end` (no bar at final_t) force-closes here at
    # its last known close via `last_close`, which may be stale by however
    # many sessions the halt has run — same "mark, don't drop" tradeoff as
    # the mark-to-market loop above.
    final_t = sessions[-1]
    final_date = final_t.date()
    for symbol in list(portfolio.positions.keys()):
        pos = portfolio.positions[symbol]
        price = last_close[symbol]
        slipped = _slip_sell(price, params.slippage_bps)
        shares = pos.shares
        portfolio.cash += slipped * shares
        portfolio.cash -= params.commission_per_order
        pos.shares = 0
        meta = open_meta[symbol]
        meta["exit_slices"].append(
            {"price": slipped, "shares": shares, "reason": "end_of_test", "date": final_date}
        )
        meta["commissions"] += params.commission_per_order
        del portfolio.positions[symbol]
        closed_trades.append(_finalize(symbol))

    equity_curve[final_t] = portfolio.cash  # no positions remain after forced close

    eq_series = pd.Series(equity_curve).sort_index()
    metrics = _compute_metrics(
        closed_trades, eq_series, exposure_samples, catalyst_blocks, catalyst_exits
    )

    return BacktestResult(
        trades=closed_trades, equity_curve=eq_series, metrics=metrics, configs=configs, params=params
    )
