"""Portfolio simulator (Phase 4) — turns a uniform list of candidate entries
into a real book, driven daily through `sts.risk`'s per-position primitives
(`position_size`, `Position`, `manage_bar`).

This module is pure: no I/O, no prints, no RNG. It consumes pre-built
candidate-entry lists (one adapter per hypothesis family, see
`sts.study.h4_candidates`) and prices already truncated to whatever window
the caller wants simulated; it has no opinion on OOS walls, catalyst
embargoes, or study wiring beyond the shared cross-family slot-contention
rule below.

Candidate dict contract (see plan docs/superpowers/plans/2026-07-12-phase4-
portfolio.md): `{"symbol", "signal_date", "entry_date", "entry", "stop",
"target", "family"}`. `entry`/`stop`/`target` are already validated at
Phase-3 geometry by the adapter; this module re-validates via `risk.Position`
and skips violators (counted, never silently dropped).

Daily loop, in order, for every session date in the union of all `prices`
indices within `[start, end)`:
1. Exits first — every open position advances one bar via `risk.manage_bar`
   on its own symbol's bar (a symbol with no bar that day is simply skipped
   for that day); an exit books cash at `price*shares - cost`, cost =
   `notional * bps_per_side/10_000 + per_order`.
2. Entries second — candidates whose `entry_date == today`, processed in
   deterministic `(signal_date, symbol)` order; each sized via
   `risk.position_size(equity, entry, stop, deployed, cash, open_count)`
   using state updated candidate-by-candidate (so slot/cash/deployed caps
   bind realistically across a crowded day, not against a snapshot taken
   before the day's fills). Entry fills at the candidate's `entry` price
   (the adapter already set that to the session's open, matching eventsim's
   convention); entry cost is charged at fill. To match eventsim's
   entry-bar-managed convention, the new position's own entry bar is then
   run through `risk.manage_bar` immediately — a same-session stop/target
   can resolve on the entry bar itself, and the 15-session time-stop clock
   starts counting from the entry bar.
3. One open position per symbol at a time — a candidate for an
   already-held symbol is skipped, never queued.
4. Equity is marked at day close: cash + Σ shares×close, using each open
   symbol's last KNOWN close when today's bar is missing for that symbol.
5. If `end` is reached with positions still open, they are censored at
   their last known close (`exit_reason="censored"`), exit costs applied
   exactly as any other exit.

`r_net` per trade = `((exit_price - exit_cost_per_share) - (entry_price +
entry_cost_per_share)) / (entry_price - initial_stop)` — i.e. the R multiple
after charging both fills' cost pro-rata per share. `max_drawdown` is the
max peak-to-trough fraction on the daily equity series. `avg_deployed` is the
mean, over every marked session, of (Σ shares×close)/equity that session.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from sts import risk


def _cost(notional: float, bps_per_side: float, per_order: float) -> float:
    return notional * bps_per_side / 10_000 + per_order


def simulate_portfolio(
    prices: dict[str, pd.DataFrame],
    candidates: list[dict],
    start: dt.date,
    end: dt.date,
    bps_per_side: float = 5.0,
    per_order: float = 1.0,
    start_capital: float = risk.START_CAPITAL,
) -> dict:
    """Drive `candidates` through a daily portfolio loop over `prices` in the
    session window `[start, end)`. See module docstring for full semantics.
    Returns `{"equity", "trades", "summary"}` per the plan's contract.
    """
    # Per-symbol date -> row-position index, built once (avoids repeated
    # index scans across a potentially long simulation).
    iloc_of: dict[str, dict[dt.date, int]] = {
        sym: {ts.date(): i for i, ts in enumerate(df.index)} for sym, df in prices.items()
    }

    session_dates = sorted(
        {ts.date() for df in prices.values() for ts in df.index if start <= ts.date() < end}
    )

    candidates_by_entry_date: dict[dt.date, list[dict]] = {}
    for cand in candidates:
        candidates_by_entry_date.setdefault(cand["entry_date"], []).append(cand)
    for lst in candidates_by_entry_date.values():
        lst.sort(key=lambda c: (c["signal_date"], c["symbol"]))

    cash = start_capital
    open_pos: dict[str, dict] = {}  # symbol -> {"pos": Position, "family", "signal_date", ...}
    last_close: dict[str, float] = {}
    equity: dict[str, float] = {}
    trades: list[dict] = []
    n_slot_skipped = 0
    n_invalid = 0
    n_dup_symbol = 0
    deployed_fracs: list[float] = []

    def get_row(symbol: str, date: dt.date):
        idx = iloc_of.get(symbol)
        if idx is None:
            return None
        i = idx.get(date)
        if i is None:
            return None
        row = prices[symbol].iloc[i]
        return float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])

    def deployed_value() -> float:
        return sum(
            rec["pos"].shares * last_close.get(sym, rec["entry"]) for sym, rec in open_pos.items()
        )

    def close_position(symbol: str, reason: str, price: float, shares: int, exit_date: dt.date) -> None:
        nonlocal cash
        rec = open_pos.pop(symbol)
        notional = price * shares
        exit_cost = _cost(notional, bps_per_side, per_order)
        cash += notional - exit_cost
        entry = rec["entry"]
        stop = rec["initial_stop"]
        entry_cost = rec["entry_cost"]
        r_gross = risk.r_multiple(entry, price, stop)
        entry_cost_per_share = entry_cost / shares
        exit_cost_per_share = exit_cost / shares
        r_net = ((price - exit_cost_per_share) - (entry + entry_cost_per_share)) / (entry - stop)
        pnl_net = (notional - exit_cost) - (entry * shares + entry_cost)
        trades.append(
            {
                "symbol": symbol,
                "family": rec["family"],
                "entry_date": rec["entry_date"],
                "exit_date": exit_date,
                "entry": entry,
                "exit": price,
                "shares": shares,
                "stop": stop,
                "target": rec["initial_target"],
                "exit_reason": reason,
                "r_gross": r_gross,
                "r_net": r_net,
                "pnl_net": pnl_net,
            }
        )
        last_close[symbol] = price

    for today in session_dates:
        # 1. Exits first.
        for symbol in list(open_pos.keys()):
            row = get_row(symbol, today)
            if row is None:
                continue
            o, h, l, c = row
            rec = open_pos[symbol]
            exits = risk.manage_bar(rec["pos"], o, h, l, c)
            last_close[symbol] = c
            if exits:
                reason, price, shares = exits[0]
                close_position(symbol, reason, price, shares, today)

        # 2. Entries second, deterministic priority order.
        for cand in candidates_by_entry_date.get(today, []):
            symbol = cand["symbol"]
            if symbol in open_pos:
                n_dup_symbol += 1
                continue

            deployed = deployed_value()
            equity_now = cash + deployed
            open_count = len(open_pos)
            entry, stop, target = cand["entry"], cand["stop"], cand.get("target")

            try:
                shares = risk.position_size(equity_now, entry, stop, deployed, cash, open_count)
            except ValueError:
                n_invalid += 1
                continue
            if shares <= 0:
                n_slot_skipped += 1
                continue
            try:
                pos = risk.Position(
                    symbol=symbol,
                    entry=entry,
                    shares=shares,
                    stop=stop,
                    target=target,
                    opened=today,
                    config=cand["family"],
                )
            except risk.RuleViolation:
                n_invalid += 1
                continue

            notional = entry * shares
            entry_cost = _cost(notional, bps_per_side, per_order)
            cash -= notional + entry_cost
            open_pos[symbol] = {
                "pos": pos,
                "family": cand["family"],
                "signal_date": cand["signal_date"],
                "entry_date": today,
                "entry": entry,
                "initial_stop": stop,
                "initial_target": target,
                "entry_cost": entry_cost,
            }
            last_close[symbol] = entry

            # Entry-bar management, same convention as eventsim: risk is live
            # from the entry bar itself, so a same-session stop/target can
            # resolve immediately and the time-stop clock starts here.
            row = get_row(symbol, today)
            if row is not None:
                o, h, l, c = row
                exits = risk.manage_bar(pos, o, h, l, c)
                last_close[symbol] = c
                if exits:
                    reason, price, shares2 = exits[0]
                    close_position(symbol, reason, price, shares2, today)

        # 3. Mark equity at close.
        deployed_today = deployed_value()
        equity_today = cash + deployed_today
        equity[today.isoformat()] = equity_today
        deployed_fracs.append(deployed_today / equity_today if equity_today else 0.0)

    # 4. Censor anything still open at `end`.
    if session_dates:
        censor_date = session_dates[-1]
        for symbol in list(open_pos.keys()):
            rec = open_pos[symbol]
            price = last_close.get(symbol, rec["entry"])
            shares = rec["pos"].shares
            close_position(symbol, "censored", price, shares, censor_date)
        # Re-mark the final session's equity after censoring so the equity
        # series and summary agree with the closed-out book.
        equity[censor_date.isoformat()] = cash + deployed_value()

    net_return = (
        (equity[session_dates[-1].isoformat()] - start_capital) / start_capital
        if session_dates
        else 0.0
    )
    max_drawdown = _max_drawdown(list(equity.values()))
    avg_deployed = sum(deployed_fracs) / len(deployed_fracs) if deployed_fracs else 0.0
    n_trades = len(trades)
    expectancy_r_net = sum(t["r_net"] for t in trades) / n_trades if n_trades else 0.0

    friction_share = _friction_share(trades, bps_per_side, per_order)

    by_year: dict[str, dict] = {}
    for t in trades:
        yr = str(t["exit_date"].year)
        by_year.setdefault(yr, []).append(t)
    by_year_summary = {}
    for yr, ts in sorted(by_year.items()):
        n = len(ts)
        by_year_summary[yr] = {
            "n": n,
            "expectancy_r_net": sum(t["r_net"] for t in ts) / n,
            "net_return": sum(t["pnl_net"] for t in ts) / start_capital,
        }

    summary = {
        "net_return": net_return,
        "max_drawdown": max_drawdown,
        "avg_deployed": avg_deployed,
        "n_trades": n_trades,
        "expectancy_r_net": expectancy_r_net,
        "friction_share": friction_share,
        "by_year": by_year_summary,
        "n_slot_skipped": n_slot_skipped,
        "n_invalid": n_invalid,
        "n_dup_symbol": n_dup_symbol,
    }

    return {"equity": equity, "trades": trades, "summary": summary}


def _max_drawdown(values: list[float]) -> float:
    if not values:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak)
    return max_dd


def _friction_share(trades: list[dict], bps_per_side: float, per_order: float) -> float:
    """Sigma-costs / Sigma-|gross pnl| across trades, recovering per-trade
    entry+exit cost from the stored fill prices/shares (costs aren't stored
    directly on the trade dict, so they're recomputed identically to how
    they were charged)."""
    total_costs = 0.0
    total_abs_gross = 0.0
    for t in trades:
        entry_notional = t["entry"] * t["shares"]
        exit_notional = t["exit"] * t["shares"]
        entry_cost = _cost(entry_notional, bps_per_side, per_order)
        exit_cost = _cost(exit_notional, bps_per_side, per_order)
        total_costs += entry_cost + exit_cost
        total_abs_gross += abs(t["exit"] - t["entry"]) * t["shares"]
    if total_abs_gross == 0:
        return 0.0
    return total_costs / total_abs_gross
