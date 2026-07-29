"""Guarded launcher for swing-ranking-v1 discovery."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class ExecutionUnavailable(RuntimeError):
    """The guarded CLI was asked to execute before an evaluator was wired in."""


PreflightRunner = Callable[[str], Mapping[str, Any]]
ExecutionRunner = Callable[[str, Path], Mapping[str, Any]]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--synthetic-fixture",
        action="store_true",
        help="use only an injected synthetic fixture; its artifacts cannot be under runs/",
    )
    source.add_argument(
        "--real-cache",
        action="store_true",
        help="select the local cache; this does not read it unless execution is enabled",
    )
    parser.add_argument("--dry-run", action="store_true", help="parse and preflight only; never write output")
    parser.add_argument("--execute", action="store_true", help="explicitly permit evaluation and artifact writes")
    parser.add_argument("--output", help="explicit artifact directory for execution")
    parser.add_argument("--bundle", help="strict study-bundle JSON; required for the built-in real-cache path")
    parser.add_argument("--paths", help="explicit preflight-paths JSON; required for the built-in real-cache path")
    return parser


def run(
    argv: list[str],
    *,
    preflight_runner: PreflightRunner | None = None,
    execution_runner: ExecutionRunner | None = None,
) -> int:
    """Parse a guarded invocation, with injectable preflight and execution seams."""
    parser = _parser()
    args = parser.parse_args(argv)
    source_mode = "synthetic_fixture" if args.synthetic_fixture else "real_cache"
    output = Path(args.output) if args.output is not None else None
    if args.dry_run and args.execute:
        parser.error("--dry-run and --execute are mutually exclusive")
    if (
        args.synthetic_fixture
        and output is not None
        and "runs" in output.resolve().parts
    ):
        parser.error("synthetic artifacts are refused under runs/")
    if args.synthetic_fixture and (args.bundle is not None or args.paths is not None):
        parser.error("--bundle and --paths are real-cache inputs")
    if not args.dry_run and not args.execute:
        parser.error("execution is disabled; pass --execute after reviewing the dry-run")

    configured_execution: ExecutionRunner | None = execution_runner
    if preflight_runner is not None:
        summary = dict(preflight_runner(source_mode))
    elif args.real_cache:
        if args.bundle is None or args.paths is None:
            parser.error("--bundle and --paths are required for built-in real-cache preflight")
        from sts.swing_ranking.config import load_preflight_paths, load_study_bundle
        from sts.swing_ranking.preflight import resolve_inputs
        from sts.swing_ranking.runner import evaluate_study

        study = load_study_bundle(Path(args.bundle))
        paths = load_preflight_paths(Path(args.paths))
        resolved = resolve_inputs(study.protocol, paths)
        summary = {
            "preflight": "passed",
            "protocol_identity": study.protocol.identity,
            "resolved_inputs_identity": resolved.identity,
            "security_count": len(resolved.securities),
            "strategy_count": len(study.strategies),
        }

        def built_in_execution(mode: str, destination: Path) -> Mapping[str, Any]:
            if mode != "real_cache":
                raise ExecutionUnavailable("built-in evaluation accepts real_cache only")
            result = evaluate_study(
                study=study,
                resolved=resolved,
                paths=paths,
                output=destination,
            )
            return {
                "artifact_identity": result.artifact.identity,
                "artifact_path": str(result.artifact.path),
                "created": result.artifact.created,
                "strategy_count": len(result.evaluations),
            }

        if configured_execution is None:
            configured_execution = built_in_execution
    else:
        parser.error("synthetic fixtures are available only through the test injection seam")
    print(
        "source=" + source_mode + " preflight=" + str(summary) + " output=" + str(output),
        flush=True,
    )
    if args.dry_run:
        print("dry-run: no execution and no output writes", flush=True)
        return 0
    if output is None:
        parser.error("--output is required with --execute")
    if configured_execution is None:
        raise ExecutionUnavailable("no swing-ranking evaluator is wired into this launcher")
    result = configured_execution(source_mode, output)
    print("execution=" + str(dict(result)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
