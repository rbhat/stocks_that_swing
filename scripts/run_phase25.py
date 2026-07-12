"""Phase 2.5 exploration orchestrator — single entrypoint for the exploratory
discovery pass (docs/PLAN.md Phase 2.5). Runs sweep_signals, screen_features,
summarize_candidates as subprocesses against a FIXED run directory
(runs/phase25/), so re-invoking with the same config resumes/no-ops instead of
piling up duplicate timestamped runs (long-running-script convention, see
scripts/fetch_study_roster.py).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
RUN_DIR = REPO_ROOT / "runs" / "phase25"
MANIFEST = RUN_DIR / "manifest.json"

STAGE_SCRIPTS = {
    "sweep_signals": ROOT / "phase25_sweep_signals.py",
    "screen_features": ROOT / "phase25_screen_features.py",
    "summarize_candidates": ROOT / "phase25_summarize_candidates.py",
}


class ConfigChangedError(RuntimeError):
    pass


def config_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def _load_manifest(run_dir: Path) -> dict | None:
    p = run_dir / "manifest.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _write_manifest(run_dir: Path, manifest: dict) -> None:
    p = run_dir / "manifest.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    os.replace(tmp, p)


def plan_stages(run_dir: Path, config: dict, force_clean: bool = False,
                 non_interactive: bool = False) -> list[str]:
    """Returns the ordered list of stage names still to run. Raises
    ConfigChangedError if a prior run exists with a DIFFERENT config and
    neither force_clean nor an interactive confirmation authorizes wiping it."""
    existing = _load_manifest(run_dir)
    new_hash = config_hash(config)

    if existing is None:
        manifest = {"config_hash": new_hash, "config": config,
                     "stages": {s: {"status": "pending"} for s in config["stages"]}}
        _write_manifest(run_dir, manifest)
        return list(config["stages"])

    if existing["config_hash"] == new_hash:
        return [s for s in config["stages"]
                if existing["stages"].get(s, {}).get("status") != "done"]

    # Config changed: must wipe or abort.
    if not force_clean:
        if non_interactive:
            raise ConfigChangedError(
                f"runs/phase25 has results from a different config; pass "
                f"--force-clean to delete and restart, or --resume is not "
                f"possible across a config change.")
        answer = input(
            f"Existing Phase 2.5 run at {run_dir} used a different config. "
            f"Delete all existing logs/results and start fresh? [y/N] "
        ).strip().lower()
        if answer != "y":
            raise ConfigChangedError("user declined to delete existing results — aborting.")

    import shutil
    shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    manifest = {"config_hash": new_hash, "config": config,
                 "stages": {s: {"status": "pending"} for s in config["stages"]}}
    _write_manifest(run_dir, manifest)
    return list(config["stages"])


class StageFailedError(RuntimeError):
    def __init__(self, stage: str, returncode: int):
        super().__init__(f"stage {stage!r} failed with exit code {returncode}")
        self.stage = stage
        self.returncode = returncode


def _run_stage_subprocess(name: str, run_dir: Path, config: dict,
                           logger: logging.Logger) -> None:
    script = STAGE_SCRIPTS[name]
    cmd = [sys.executable, str(script), "--run-dir", str(run_dir)]
    if name == "sweep_signals":
        cmd += ["--detectors", ",".join(config["detectors"]),
                "--max-configs-per-detector", str(config["max_configs_per_detector"])]
    elif name == "screen_features":
        cmd += ["--detectors", ",".join(config["detectors"])]

    env = dict(os.environ)
    extra_paths = [str(ROOT), str(REPO_ROOT / "src")]
    env["PYTHONPATH"] = os.pathsep.join(extra_paths + [env.get("PYTHONPATH", "")]).rstrip(os.pathsep)

    logger.info("=== starting stage %s: %s ===", name, " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=False, env=env)
    if proc.returncode != 0:
        raise StageFailedError(name, proc.returncode)
    logger.info("=== stage %s finished ok ===", name)


def execute(run_dir: Path, config: dict, force_clean: bool, non_interactive: bool) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    to_run = plan_stages(run_dir, config, force_clean=force_clean,
                          non_interactive=non_interactive)

    logger = logging.getLogger("phase25.orchestrator")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fh = logging.FileHandler(run_dir / "combined.log")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("[orchestrator] %(message)s"))
    logger.addHandler(sh)

    if not to_run:
        logger.info("all requested stages already done — no-op. See %s/candidates.md",
                     run_dir)
        return

    logger.info("plan: %s", to_run)
    t0 = time.time()
    for i, stage in enumerate(to_run, 1):
        manifest = _load_manifest(run_dir)
        manifest["stages"].setdefault(stage, {})
        manifest["stages"][stage] = {"status": "running",
                                      "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        _write_manifest(run_dir, manifest)
        stage_t0 = time.time()
        try:
            _run_stage_subprocess(stage, run_dir, config, logger)
        except StageFailedError:
            manifest = _load_manifest(run_dir)
            manifest["stages"][stage]["status"] = "failed"
            _write_manifest(run_dir, manifest)
            raise
        manifest = _load_manifest(run_dir)
        manifest["stages"][stage] = {
            "status": "done",
            "started_at": manifest["stages"][stage]["started_at"],
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "duration_s": round(time.time() - stage_t0, 1),
        }
        _write_manifest(run_dir, manifest)
        elapsed = time.time() - t0
        eta = (len(to_run) - i) * (elapsed / i)
        logger.info("[%d/%d] %s done — elapsed %.0fs, ETA %.0fs", i, len(to_run), stage,
                    elapsed, eta)

    logger.info("Phase 2.5 run complete. Candidates: %s/candidates.md — "
                "candidates, not evidence (docs/PLAN.md Phase 2.5).", run_dir)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stages", default="sweep_signals,screen_features,summarize_candidates")
    ap.add_argument("--detectors", default="breakout,deep_pullback,sweep_reclaim,squeeze,markov")
    ap.add_argument("--max-configs-per-detector", type=int, default=0)
    ap.add_argument("--run-dir", type=Path, default=RUN_DIR)
    ap.add_argument("--force-clean", action="store_true",
                     help="delete existing runs/phase25 results if config changed, no prompt")
    ap.add_argument("--yes", action="store_true",
                     help="non-interactive: never prompt, fail instead if a prompt would occur")
    args = ap.parse_args()

    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    if "summarize_candidates" in stages:
        stages = [s for s in stages if s != "summarize_candidates"] + ["summarize_candidates"]
    config = {"stages": stages, "detectors": args.detectors.split(","),
              "max_configs_per_detector": args.max_configs_per_detector}

    sys.stdout.reconfigure(line_buffering=True)
    try:
        execute(args.run_dir, config, force_clean=args.force_clean,
                non_interactive=args.yes)
    except ConfigChangedError as e:
        print(f"aborted: {e}")
        sys.exit(1)
    except StageFailedError as e:
        print(f"aborted: {e}. Fix the issue and re-run — completed stages will be skipped.")
        sys.exit(1)


if __name__ == "__main__":
    main()
