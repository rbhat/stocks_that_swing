"""Phase 2.5 stage: grid-sweep each detector's parameters through eventsim on
IS-only data. Output is raw metrics per config — screening, not judging; no
PROCEED/PARK/STOP verdict is computed here (docs/PLAN.md Phase 2.5).

Note: `sts.eventsim.simulate_events` / `raw_forward_returns` take the whole
`prices` dict plus a `detector` callable override (they run detection
internally, per symbol) rather than a pre-built event list — see
src/sts/eventsim.py. This module passes `DETECTOR_FNS[detector]` in as that
override so the grid can sweep families eventsim doesn't have registered
configs for.
"""

from __future__ import annotations

import argparse
import itertools
import time
from pathlib import Path

from phase25_common import atomic_write_json, load_is_frames, setup_stage_logger
from sts import eventsim
from sts.signals import breakout, deep_pullback, markov, squeeze, sweep_reclaim

DETECTOR_GRIDS = {
    "breakout": {"lookback": [20, 55], "breakout_vol_ratio": [1.5, 2.0]},
    "deep_pullback": {"fib_deep": [0.5, 0.618], "surge_ratio": [1.5, 2.0]},
    "sweep_reclaim": {"fib_retrace": [0.5, 0.618]},
    "squeeze": {"squeeze_percentile": [0.15, 0.20], "expansion_ratio": [1.5, 2.0]},
    "markov": {"ret_band": [0.20, 0.25], "min_lift": [0.001, 0.002]},
}
DETECTOR_FNS = {
    "breakout": breakout.detect,
    "deep_pullback": deep_pullback.detect,
    "sweep_reclaim": sweep_reclaim.detect,
    "squeeze": squeeze.detect,
    "markov": markov.detect,
}


def _grid_configs(detector: str, max_configs: int) -> list[dict]:
    grid = DETECTOR_GRIDS[detector]
    keys = list(grid.keys())
    combos = list(itertools.product(*grid.values()))
    configs = [dict(zip(keys, combo)) for combo in combos]
    return configs[:max_configs] if max_configs else configs


def run_sweep(run_dir: Path, detectors: list[str], max_configs: int = 0) -> None:
    logger = setup_stage_logger("sweep_signals", run_dir)
    frames = load_is_frames()
    logger.info("loaded %d IS-only frames", len(frames))

    results = []
    t0 = time.time()
    total = sum(len(_grid_configs(d, max_configs)) for d in detectors)
    done = 0
    for detector in detectors:
        fn = DETECTOR_FNS[detector]
        for params in _grid_configs(detector, max_configs):
            raw = eventsim.raw_forward_returns(
                frames, config_name=detector, params=params, detector=fn
            )
            sim = eventsim.simulate_events(
                frames, config_name=detector, params=params, detector=fn
            )
            by_h = raw["by_horizon"]
            results.append({
                "detector": detector,
                "params": params,
                "n_events": raw["n_events"],
                "raw_return_h5": by_h.get(5, {}).get("mean_return"),
                "raw_return_h10": by_h.get(10, {}).get("mean_return"),
                "raw_return_h15": by_h.get(15, {}).get("mean_return"),
                "expectancy_r": sim["expectancy_r"],
                "expectancy_r_lower90": sim["expectancy_r_lower90"],
            })
            done += 1
            elapsed = time.time() - t0
            eta = (total - done) * (elapsed / done)
            logger.info(
                "[%d/%d] %s %s -> %d events, ER=%.4f (elapsed %.0fs, ETA %.0fs)",
                done, total, detector, params, raw["n_events"], sim["expectancy_r"],
                elapsed, eta,
            )

    atomic_write_json(results, run_dir / "sweep_signals" / "results.json")
    logger.info("sweep_signals done: %d configs written", len(results))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--detectors", default=",".join(DETECTOR_FNS.keys()))
    ap.add_argument("--max-configs-per-detector", type=int, default=0)
    args = ap.parse_args()
    run_sweep(args.run_dir, args.detectors.split(","), args.max_configs_per_detector)


if __name__ == "__main__":
    main()
