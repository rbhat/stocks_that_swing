"""Per-book state replay + charter checks (max positions, deploy cap,
dup-symbol, H1 throttle).

`BookState.from_ledger` reconstructs cash/equity for a single book purely
from the ledger's latest-row-per-entry_id view (`Ledger.state()`) — it does
NOT replay the two separate open/closed journal events for a position.
Each entry_id contributes exactly one cash effect, derived from its latest
row:

  - status == "open":   cash -= usd_deployed + entry_fee
  - status == "closed": cash -= usd_deployed + entry_fee
                         cash += qty * exit_price - exit_fee

where entry_fee = broker.cost_side(entry_fill, qty) (one-sided execution
cost) and, for a closed row, fees_total is the TOTAL of both sides, so
exit_fee = fees_total - entry_fee. Rows are processed in `seq` order for
determinism, though the arithmetic is order-independent (each entry_id
contributes exactly once).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sts.forward.broker import cost_side
from sts.forward.ledger import Ledger
from sts.risk import MAX_DEPLOYED_PCT, MAX_POSITIONS, position_size

START_EQUITY = 100_000.0
H1_THROTTLE_MAX = 4
H1_THROTTLE_WINDOW = 5


@dataclass
class BookState:
    book: str
    equity: float
    cash: float
    open_rows: list[dict]

    @classmethod
    def from_ledger(cls, ledger: Ledger, book: str, marks: dict[str, float]) -> "BookState":
        rows = [r for r in ledger.state().values() if r["book"] == book]
        rows.sort(key=lambda r: r["seq"])

        cash = START_EQUITY
        open_rows: list[dict] = []
        for r in rows:
            qty = r["qty"]
            entry_fee = cost_side(r["entry_fill"], qty)
            cash -= r["usd_deployed"] + entry_fee
            if r["status"] == "closed":
                exit_fee = r["fees_total"] - entry_fee
                cash += qty * r["exit_price"] - exit_fee
            else:
                open_rows.append(r)

        equity = cash + sum(
            r["qty"] * marks.get(r["ticker"], r["entry_fill"]) for r in open_rows
        )
        return cls(book=book, equity=equity, cash=cash, open_rows=open_rows)

    def deployed_usd(self) -> float:
        return sum(r["usd_deployed"] for r in self.open_rows)

    def deployed_frac(self) -> float:
        if self.equity <= 0:
            return 0.0
        return self.deployed_usd() / self.equity

    def open_count(self) -> int:
        return len(self.open_rows)

    def can_enter(self, symbol: str, notional: float, shared_blocked: set[str]) -> str | None:
        """First applicable skip reason, checked in order: dup_symbol, slot,
        deploy_cap. `shared_blocked` is the set of symbols held by the
        *other* family in a shared book (cross-family one-symbol rule)."""
        held = {r["ticker"] for r in self.open_rows}
        if symbol in held or symbol in shared_blocked:
            return "dup_symbol"
        if self.open_count() >= MAX_POSITIONS:
            return "slot"
        if self.deployed_usd() + notional > MAX_DEPLOYED_PCT * self.equity:
            return "deploy_cap"
        return None

    def size(self, entry: float, stop: float) -> int:
        """Charter sizing (0.75% risk, 15% notional cap, 80% deploy cap,
        cash, open-position-count) — all owned by `sts.risk.position_size`."""
        return position_size(
            self.equity,
            entry,
            stop,
            deployed=self.deployed_usd(),
            cash=self.cash,
            open_positions=self.open_count(),
        )

    def snapshot(self, date: dt.date) -> dict:
        return {
            "date": date.isoformat(),
            "book": self.book,
            "equity": self.equity,
            "cash": self.cash,
            "usd_deployed": self.deployed_usd(),
            "open_count": self.open_count(),
        }


def _as_date(value: dt.date | str) -> dt.date:
    return dt.date.fromisoformat(value) if isinstance(value, str) else value


def h1_throttle_room(ledger: Ledger, book: str, session_dates: list[dt.date]) -> int:
    """4 minus the number of distinct H1 entries (queued candidates or
    filled/opened rows) for `book` whose signal_date falls in the trailing
    5-session window (the last 5 of `session_dates`, including today),
    floored at 0. Candidates and their corresponding filled rows share an
    entry_id, so they are deduped rather than double-counted."""
    window = set(session_dates[-H1_THROTTLE_WINDOW:])
    seen: set[str] = set()

    for rec in ledger.signals():
        if rec.get("kind") != "candidate":
            continue
        if rec.get("book") != book or rec.get("family") != "h1":
            continue
        if _as_date(rec["signal_date"]) in window:
            seen.add(rec["entry_id"])

    for r in ledger.state().values():
        if r["book"] != book or r["family"] != "h1":
            continue
        if _as_date(r["signal_date"]) in window:
            seen.add(r["entry_id"])

    return max(0, H1_THROTTLE_MAX - len(seen))
