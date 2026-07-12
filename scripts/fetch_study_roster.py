"""Idempotent study-roster fetcher — builds the wide backtest cache (~250 names).

WHY: event-level studies (HYPOTHESES.md) need statistical power across a wide,
liquid roster, not just the 12 universe.yaml seeds. This fetches/tops-up the
roster to --target-total names so sparse slices (year, regime, symbol-liquidity
tercile) clear their adequacy floors.

WHAT IT WRITES: ONLY cache/study_frames/{SYM}.parquet. This is a RESEARCH
roster, deliberately NOT the price store:
  - never touches cache/ohlcv/ (the source of truth), universe.yaml, or last_run.json;
  - none of the store's hard rules apply here (validate-before-write, the last_run
    signal gate, the 100-name universe cap all govern the store, not the study roster);
  - cache/ is gitignored by design — these frames are large and fully reproducible
    by re-running this script, so they live on disk but not in git. This directory IS
    the persistent study cache; the existing frames already live here and every study
    loader reads it directly (see src/sts/data/study_store.py).

SEEDS + ANCHORS ARE MUST-HAVES: the universe.yaml seeds and the SPY/QQQ regime
anchors are guaranteed in the roster — fetched even if that pushes past --target-total.
In practice all seeds already live in cache/ohlcv/ (the gated store, which every
study loader reads first), so they are normally counted as already-present; this is the
belt-and-suspenders that also covers a seed newly added to universe.yaml but not yet
in the store.

ADJUSTMENT-BASIS PARITY: reuses sts.data.fetch.fetch_daily (auto_adjust=True, total-
return split+div-adjusted) so these frames share the store's exact basis and can be
pooled with the gated cache/ohlcv symbols in a single study without mixing bases.

IDEMPOTENT / RESUMABLE / RATE-LIMITED (long-running-script hard rule):
  - Skips any symbol already available fresh: in cache/ohlcv/ (the store, always), OR a
    study frame whose last bar is in year >= --min-end-year.
  - Fetches all missing must-haves, then only enough NEW names to bring the total roster
    (gated + fresh study frames) up to --target-total; a re-run after success is a no-op.
  - A killed run leaves whole, valid parquets (atomic temp + os.replace); the next run
    recomputes the smaller remaining need and continues.
  - Sleeps --sleep seconds (+jitter) between symbols; fetch_daily already retries with
    exponential backoff. Dead/empty symbols are recorded to a sidecar and skipped on
    re-runs (use --retry-failed to re-attempt).
  - Prints per-symbol progress with elapsed + ETA.

ROSTER SOURCE: cache/scan/constituents.json (S&P 500 + Nasdaq-100). Fill names are
taken in listed order, skipping any already cached, until the target total is reached
— so the new names are mostly modern-history constituents, which is exactly where the
OOS slice and the sparse cells need bodies.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import signal
import sys
import time
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sts.data.fetch import FetchError, fetch_daily  # noqa: E402

STUDY_FRAMES_DIR = ROOT / "cache" / "study_frames"
STORE_DIR = ROOT / "cache" / "ohlcv"
CONSTITUENTS = ROOT / "cache" / "scan" / "constituents.json"
UNIVERSE = ROOT / "universe.yaml"
FAILURES_SIDECAR = STUDY_FRAMES_DIR / ".fetch_failures.json"
OHLC = ["open", "high", "low", "close"]

# Regime/market anchors the study loaders expect present (regime_by_year reads SPY).
ANCHORS = ["SPY", "QQQ"]
MIN_BARS = 300  # a frame with fewer total bars is too short to be a study symbol


def _store_symbols() -> set[str]:
    return {p.stem for p in STORE_DIR.glob("*.parquet")}


def _seed_symbols() -> list[str]:
    return list(yaml.safe_load(UNIVERSE.read_text()).get("seeds", []))


def _fresh_scratch_symbols(min_end_year: int) -> set[str]:
    """Study frames whose last bar is in year >= min_end_year (index-only read)."""
    fresh: set[str] = set()
    for p in STUDY_FRAMES_DIR.glob("*.parquet"):
        try:
            idx = pd.read_parquet(p, columns=[]).index
            if len(idx) and pd.DatetimeIndex(idx).max().year >= min_end_year:
                fresh.add(p.stem)
        except Exception:
            continue  # unreadable -> treat as not-fresh, it will be re-fetched
    return fresh


def _load_failures() -> set[str]:
    if FAILURES_SIDECAR.exists():
        try:
            return set(json.loads(FAILURES_SIDECAR.read_text()))
        except Exception:
            return set()
    return set()


def _save_failures(failures: set[str]) -> None:
    tmp = FAILURES_SIDECAR.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sorted(failures)))
    os.replace(tmp, FAILURES_SIDECAR)


def _atomic_write_parquet(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_suffix(f".parquet.tmp.{os.getpid()}")  # not matched by glob('*.parquet')
    df.to_parquet(tmp)
    os.replace(tmp, path)


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with NaN or non-positive OHLC — the same light hygiene the study
    loaders apply before use (NOT the full store quality gate, which is tuned for the
    source-of-truth store, not a deep-history research frame)."""
    ohlc = df[OHLC]
    return df[~(ohlc.isna().any(axis=1) | (ohlc <= 0).any(axis=1))]


def _fmt_eta(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


def _dedup(seq) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in seq:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target-total", type=int, default=250,
                    help="desired TOTAL roster size (gated + fresh study frames); default 250")
    ap.add_argument("--sleep", type=float, default=2.0,
                    help="base seconds between symbols (+/-25%% jitter); default 2.0")
    ap.add_argument("--min-end-year", type=int, default=2024,
                    help="a study frame is 'fresh' if its last bar year >= this; default 2024")
    ap.add_argument("--refresh", action="store_true",
                    help="re-fetch every target even if a fresh study frame exists")
    ap.add_argument("--retry-failed", action="store_true",
                    help="re-attempt symbols recorded in the dead-symbol sidecar")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and exit without fetching")
    args = ap.parse_args()

    # Progress must be visible when redirected to a log: Python block-buffers a
    # non-TTY stdout by default, so a long run looks "hung" (prints sit in an 8KB
    # buffer until it fills or the process exits). Line-buffer so `tail -f` works.
    sys.stdout.reconfigure(line_buffering=True)

    def _on_sigint(_signum, _frame):
        print("\ninterrupted — frames already fetched are saved (atomic); "
              "re-run to continue (idempotent).")
        sys.exit(0)
    signal.signal(signal.SIGINT, _on_sigint)

    STUDY_FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    for stale in STUDY_FRAMES_DIR.glob("*.parquet.tmp.*"):
        stale.unlink(missing_ok=True)  # leftover temp from a killed prior run
    constituents = json.loads(CONSTITUENTS.read_text()).get("symbols", [])
    seeds = _seed_symbols()

    store = _store_symbols()
    fresh_scratch = set() if args.refresh else _fresh_scratch_symbols(args.min_end_year)
    have = store | fresh_scratch  # symbols already covered fresh
    failures = _load_failures()
    skip_failed = failures if not args.retry_failed else set()

    # Must-haves: seeds + regime anchors, guaranteed present (fetched even past target).
    must_have = _dedup(ANCHORS + seeds)
    must_fetch = [s for s in must_have if s not in have and s not in skip_failed]
    seeds_covered = [s for s in seeds if s in have]

    # Fill pool: constituents in listed order, minus anything covered/must/dead.
    fill_pool = [s for s in _dedup(constituents)
                 if s not in have and s not in must_fetch and s not in skip_failed]
    need_fill = max(0, args.target_total - len(have) - len(must_fetch))

    print(f"roster status: {len(have)} already fresh ({len(store)} gated store + "
          f"{len(fresh_scratch)} study frames), target total {args.target_total}")
    print(f"  seeds: {len(seeds_covered)}/{len(seeds)} already present"
          + (f"; will fetch missing seeds/anchors: {[s for s in must_fetch if s in must_have]}"
             if must_fetch else "; all seeds + anchors present"))
    print(f"  plan: {len(must_fetch)} must-have + up to {need_fill} fill "
          f"(fill pool {len(fill_pool)} names; {len(failures)} known-dead "
          f"{'INCLUDED' if args.retry_failed else 'skipped'})")
    if args.refresh:
        print("  --refresh: existing study frames will be overwritten")

    if not must_fetch and need_fill == 0:
        print("target already met and all must-haves present — nothing to fetch (no-op).")
        return

    if args.dry_run:
        preview = must_fetch + fill_pool[:need_fill]
        print(f"\nDRY RUN — would fetch {len(preview)} symbols:")
        if must_fetch:
            print(f"  must-have ({len(must_fetch)}): {' '.join(must_fetch)}")
        print(f"  fill ({min(need_fill, len(fill_pool))}): "
              + " ".join(fill_pool[:need_fill]) + (" ..." if len(fill_pool) > need_fill else ""))
        return

    # Phase 1 fetches every must-have; phase 2 fills until the roster hits target-total,
    # continuing past fill failures so dead names don't leave us short.
    queue = [("must", s) for s in must_fetch] + [("fill", s) for s in fill_pool]
    fetched = 0
    attempts = 0
    t0 = time.time()
    for kind, sym in queue:
        if kind == "fill" and len(have) + fetched >= args.target_total:
            break
        attempts += 1
        tag = "seed/anchor" if kind == "must" else "fill"
        try:
            df = _clean(fetch_daily(sym))
            if len(df) < MIN_BARS:
                print(f"  [{attempts}] {sym:<6} ({tag}) too short ({len(df)} bars) — skipped")
                failures.add(sym)
                _save_failures(failures)
            else:
                _atomic_write_parquet(df, STUDY_FRAMES_DIR / f"{sym}.parquet")
                fetched += 1
                y0, y1 = df.index.min().year, df.index.max().year
                elapsed = time.time() - t0
                eta = (max(0, need_fill + len(must_fetch) - fetched)) * (elapsed / max(1, fetched))
                print(f"  [{len(have) + fetched}/{args.target_total}] {sym:<6} ({tag}) ok  "
                      f"{len(df):>6} bars {y0}-{y1}   elapsed {_fmt_eta(elapsed)} · ETA {_fmt_eta(eta)}")
                failures.discard(sym) and _save_failures(failures)
        except (FetchError, Exception) as e:  # noqa: BLE001 — any fetch error -> record & continue
            print(f"  [{attempts}] {sym:<6} ({tag}) FAILED: {type(e).__name__}: {str(e)[:70]} — skipped")
            failures.add(sym)
            _save_failures(failures)

        remaining = (kind == "must") or (len(have) + fetched < args.target_total)
        if remaining:
            time.sleep(args.sleep * random.uniform(0.75, 1.25))

    total_now = len(have) + fetched
    missing_seeds = [s for s in seeds if s not in have and s not in _fresh_scratch_symbols(args.min_end_year)]
    print(f"\ndone: fetched {fetched} new ({attempts} attempted), roster now {total_now} symbols.")
    if missing_seeds:
        print(f"  *** WARNING: seeds still missing: {missing_seeds} (fetch failed — --retry-failed) ***")
    if total_now < args.target_total:
        print(f"  below target by {args.target_total - total_now}: pool exhausted or too many dead "
              f"symbols. Re-run with --retry-failed, or accept the current roster.")
    print(f"  dead-symbol sidecar: {FAILURES_SIDECAR} ({len(failures)} names)")
    print("  re-running this script now is a no-op (idempotent).")


if __name__ == "__main__":
    main()
