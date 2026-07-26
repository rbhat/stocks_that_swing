# Phase 0 — baseline and workspace protection

- Date: 2026-07-26
- Baseline SHA: `511e15f`
- Initial worktree: clean
- Protected files: `docs/VISION.md`, `deploy/open_remote.sh`
- Environment: CPython 3.12.3, local `.venv`
- Baseline gate: `343 passed in 14.25s`
- Machine-readable test result: `.scratch/baseline/pytest-baseline.xml`
- Local cache: 240/250 frames fetched through the local roster path; ten
  long-history downloads failed the existing missing-session quality gate.
- Production access: none; no `gcloud` call was made.

The causal failure is independently established in
`report_why_no_signals.md`: a final-bar detector event is discarded by
`entry_geometry()` because `signal_iloc + 1` is outside the truncated frame.
The initial broad local replay was stopped because the existing adapter
recomputed full detector history for every symbol/session; Phase 6 replaces
that ad-hoc run with the bounded audit runner required by the repair plan.
