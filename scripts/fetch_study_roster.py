"""Build the validated current-roster parquet cache.

The job is idempotent, resumable, rate-limited, and prints elapsed time plus
ETA. It preserves the configured roster, adds SPY/QQQ anchors, fills from the
local constituent scan, validates every frame, and writes atomically.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
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

from sts import calendar
from sts.data.fetch import FetchError, fetch_daily
from sts.data.study_store import StudyStore

STUDY_FRAMES_DIR = ROOT / "cache" / "study_frames"
CONSTITUENTS = ROOT / "cache" / "scan" / "constituents.json"
FAILURES_SIDECAR = STUDY_FRAMES_DIR / ".fetch_failures.json"
CONFIGS_DIR = ROOT / "configs"
ROSTER_YAML = CONFIGS_DIR / "study_roster.yaml"
ROSTER_MANIFEST = CONFIGS_DIR / "study_roster_manifest.json"
OHLC = ["open", "high", "low", "close"]

_STORE: StudyStore | None = None


def _store() -> StudyStore:
    global _STORE
    if _STORE is None:
        _STORE = StudyStore(root=STUDY_FRAMES_DIR)
    return _STORE


def _write_frame(symbol: str, df: pd.DataFrame) -> None:
    """Clean, then route through StudyStore.write (quality gate + truncate + atomic+fsync)."""
    _store().write(symbol, _clean(df))

# Regime/market anchors the study loaders expect present (regime_by_year reads SPY).
ANCHORS = ["SPY", "QQQ"]
MIN_BARS = 300  # a frame with fewer total bars is too short to be a study symbol


def _configured_symbols() -> list[str]:
    if not ROSTER_YAML.is_file():
        return []
    return list(yaml.safe_load(ROSTER_YAML.read_text()).get("symbols", []))


STALENESS_SESSIONS = 5  # a frame up to 5 sessions behind "today" still counts as fresh
                         # (this script isn't run daily; a week-old frame is fine for a
                         # research roster, unlike the trade-facing PriceStore)


def _fresh_scratch_symbols() -> set[str]:
    """Frames within STALENESS_SESSIONS of the last completed session."""
    cutoff = calendar.last_completed_session() - dt.timedelta(days=STALENESS_SESSIONS * 2)
    fresh: set[str] = set()
    for sym in _store().symbols():
        last = _store().last_date(sym)
        if last is not None and last >= cutoff:
            fresh.add(sym)
    return fresh


def _load_failures() -> set[str]:
    if FAILURES_SIDECAR.exists():
        try:
            return set(json.loads(FAILURES_SIDECAR.read_text()))
        except (OSError, json.JSONDecodeError, TypeError):
            return set()
    return set()


def _save_failures(failures: set[str]) -> None:
    tmp = FAILURES_SIDECAR.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sorted(failures)))
    os.replace(tmp, FAILURES_SIDECAR)


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


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _write_roster_artifacts(anchors: list[str]) -> None:
    """Commit-worthy roster contract: exact membership + rationale (YAML) and a
    per-symbol data manifest (JSON) so the study population is reconstructable
    from git alone, without re-deriving it from the gitignored parquet cache."""
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    symbols = _store().symbols()

    roster = {
        "as_of": dt.datetime.now(dt.UTC).date().isoformat(),
        "source": "cache/scan/constituents.json (S&P 500 + Nasdaq-100)",
        "eligibility": {"min_price_usd": 5, "min_avg_dollar_vol_usd": 20_000_000},
        "anchors": sorted(anchors),
        "symbols": symbols,
        "count": len(symbols),
    }
    tmp = ROSTER_YAML.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(roster, sort_keys=False))
    os.replace(tmp, ROSTER_YAML)

    manifest = {
        "adjustment_basis": "split+dividend adjusted total return (auto_adjust=True)",
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "symbols": {},
    }
    for sym in symbols:
        df = _store().load(sym)
        path = _store().path(sym)
        manifest["symbols"][sym] = {
            "first_session": df.index.min().date().isoformat(),
            "last_session": df.index.max().date().isoformat(),
            "n_bars": len(df),
            "file_sha256": _file_sha256(path),
        }
    tmp = ROSTER_MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    os.replace(tmp, ROSTER_MANIFEST)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target-total", type=int, default=250,
                    help="desired TOTAL roster size (gated + fresh study frames); default 250")
    ap.add_argument("--sleep", type=float, default=2.0,
                    help="base seconds between symbols (+/-25%% jitter); default 2.0")
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
    configured = _configured_symbols()
    fresh_scratch = set() if args.refresh else _fresh_scratch_symbols()
    have = fresh_scratch
    failures = _load_failures()
    skip_failed = failures if not args.retry_failed else set()

    # Preserve the configured roster and the market anchors.
    must_have = _dedup(ANCHORS + configured)
    must_fetch = [s for s in must_have if s not in have and s not in skip_failed]

    # Fill pool: constituents in listed order, minus anything covered/must/dead.
    fill_pool = [s for s in _dedup(constituents)
                 if s not in have and s not in must_fetch and s not in skip_failed]
    need_fill = max(0, args.target_total - len(have) - len(must_fetch))

    print(f"roster status: {len(have)} fresh frames, target total {args.target_total}")
    print(
        f"  configured/anchor coverage: {len(must_have) - len(must_fetch)}/{len(must_have)}"
    )
    print(f"  plan: {len(must_fetch)} must-have + up to {need_fill} fill "
          f"(fill pool {len(fill_pool)} names; {len(failures)} known-dead "
          f"{'INCLUDED' if args.retry_failed else 'skipped'})")
    if args.refresh:
        print("  --refresh: existing study frames will be overwritten")

    if not must_fetch and need_fill == 0:
        print("target already met and all must-haves present — nothing to fetch (no-op).")
        if args.dry_run:
            print("  DRY RUN — skipping artifact write.")
            return
        _write_roster_artifacts(anchors=ANCHORS)
        print(f"  wrote {ROSTER_YAML.relative_to(ROOT)} + {ROSTER_MANIFEST.relative_to(ROOT)}")
        return

    if args.dry_run:
        preview = must_fetch + fill_pool[:need_fill]
        print(f"\nDRY RUN — would fetch {len(preview)} symbols:")
        if must_fetch:
            print(f"  must-have ({len(must_fetch)}): {' '.join(must_fetch)}")
        print(f"  fill ({min(need_fill, len(fill_pool))}): "
              + " ".join(fill_pool[:need_fill]) + (" ..." if len(fill_pool) > need_fill else ""))
        return

    # Fetch every must-have, then fill until the target is reached.
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
                _write_frame(sym, df)
                fetched += 1
                y0, y1 = df.index.min().year, df.index.max().year
                elapsed = time.time() - t0
                eta = (max(0, need_fill + len(must_fetch) - fetched)) * (elapsed / max(1, fetched))
                print(f"  [{len(have) + fetched}/{args.target_total}] {sym:<6} ({tag}) ok  "
                      f"{len(df):>6} bars {y0}-{y1}   elapsed {_fmt_eta(elapsed)} · ETA {_fmt_eta(eta)}")
                # Remove a recovered symbol from the failure sidecar.
                if sym in failures:
                    failures.discard(sym)
                    _save_failures(failures)
        except (FetchError, ValueError, Exception) as e:  # noqa: BLE001 — fetch or quality-gate failure -> record & continue
            print(f"  [{attempts}] {sym:<6} ({tag}) FAILED: {type(e).__name__}: {str(e)[:70]} — skipped")
            failures.add(sym)
            _save_failures(failures)

        remaining = (kind == "must") or (len(have) + fetched < args.target_total)
        if remaining:
            time.sleep(args.sleep * random.uniform(0.75, 1.25))

    total_now = len(have) + fetched
    current = _fresh_scratch_symbols()
    missing_required = [symbol for symbol in must_have if symbol not in current]
    print(f"\ndone: fetched {fetched} new ({attempts} attempted), roster now {total_now} symbols.")
    if missing_required:
        print(
            "  *** WARNING: required symbols still missing: "
            f"{missing_required} (fetch failed — --retry-failed) ***"
        )
    if total_now < args.target_total:
        print(f"  below target by {args.target_total - total_now}: pool exhausted or too many dead "
              f"symbols. Re-run with --retry-failed, or accept the current roster.")
    print(f"  dead-symbol sidecar: {FAILURES_SIDECAR} ({len(failures)} names)")
    print("  re-running this script now is a no-op (idempotent).")

    _write_roster_artifacts(anchors=ANCHORS)
    print(f"  wrote {ROSTER_YAML.relative_to(ROOT)} + {ROSTER_MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
