"""Watchlist management.

Hard rules (tested):
- Seeds are immutable to code — only the human edits them in universe.yaml.
- Hard cap of MAX_SYMBOLS total names.
- When full, rotation evicts the weakest *discovered* name, never a seed.
- Every add/removal is appended to universe_changes.log with a reason.
- Save before log: the yaml is the source of truth, so a mutation is
  persisted before it's logged — a crash never leaves the log claiming a
  change the yaml doesn't have.
"""

from __future__ import annotations

import datetime as dt
import os
import tempfile
from pathlib import Path

import yaml

MAX_SYMBOLS = 100
DEFAULT_PATH = Path("universe.yaml")
DEFAULT_LOG = Path("universe_changes.log")


class Universe:
    def __init__(self, path: Path | str = DEFAULT_PATH, log_path: Path | str = DEFAULT_LOG):
        self.path = Path(path)
        self.log_path = Path(log_path)
        data = yaml.safe_load(self.path.read_text())
        seeds = [s.upper() for s in data["seeds"]]
        discovered_syms = [e["symbol"].upper() for e in data.get("discovered", [])]
        all_syms = seeds + discovered_syms
        if len(all_syms) != len(set(all_syms)):
            raise ValueError("duplicate symbol across seeds/discovered")
        if len(all_syms) > MAX_SYMBOLS:
            raise ValueError(f"universe has {len(all_syms)} symbols, over MAX_SYMBOLS={MAX_SYMBOLS}")
        self.seeds: list[str] = seeds
        self.discovered: dict[str, dict] = {
            e["symbol"].upper(): e for e in data.get("discovered", [])
        }

    @property
    def symbols(self) -> list[str]:
        return self.seeds + list(self.discovered)

    def _save(self) -> None:
        data = {"seeds": self.seeds, "discovered": list(self.discovered.values())}
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".yaml.tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(yaml.safe_dump(data, sort_keys=False))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
            dir_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _log(self, action: str, symbol: str, reason: str) -> None:
        line = f"{dt.datetime.now().isoformat(timespec='seconds')} {action} {symbol} — {reason}\n"
        with open(self.log_path, "a") as f:
            f.write(line)

    def add_discovered(self, symbol: str, reason: str, weakness: dict[str, float] | None = None) -> bool:
        """Add a discovered name. `weakness` maps discovered symbol -> score
        (higher = weaker); required to rotate when the list is full — it
        must cover every discovered symbol, or an unscored name could be
        silently immune (or silently evicted).
        Returns True if added."""
        symbol = symbol.upper()
        if symbol in self.symbols:
            return False
        victim = None
        if len(self.symbols) >= MAX_SYMBOLS:
            if not self.discovered:
                raise RuntimeError("universe full of seeds; cannot rotate")
            missing = set(self.discovered) - set(weakness or {})
            if weakness is None or missing:
                raise ValueError(f"rotation requires weakness scores for all discovered symbols; missing {sorted(missing)}")
            victim = max(self.discovered, key=lambda s: weakness[s])
            del self.discovered[victim]
        self.discovered[symbol] = {
            "symbol": symbol,
            "added": dt.date.today().isoformat(),
            "reason": reason,
        }
        self._save()
        if victim is not None:
            self._log("ROTATE-OUT", victim, f"weakest discovered (making room for {symbol})")
        self._log("ADD", symbol, reason)
        return True

    def remove_discovered(self, symbol: str, reason: str) -> None:
        symbol = symbol.upper()
        if symbol in self.seeds:
            raise ValueError(f"{symbol} is a seed — code never removes seeds")
        if symbol in self.discovered:
            del self.discovered[symbol]
            self._save()
            self._log("REMOVE", symbol, reason)
