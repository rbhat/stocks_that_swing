# Swing strategy discovery index

## Read order

1. `VISION.md` — user-owned swing-trading scope and charter.
2. `PLAN.md` — sole active discovery and ranking plan.
3. `../decisions.md` — active decision record.
4. `RUN_REFERENCE.md` — guarded implementation boundary and required inputs.

## Current authority

Planning is complete for open discovery within the Vision's explicit charter.
No strategy family, behavior, indicator, target method, model, parameter
range, fold design, or composite weighting is preselected.

The isolated `sts.swing_ranking` implementation includes strict configuration,
causal daily/weekly/monthly candidates, declared entry geometry, the
Decimal-only zero-cost event simulator, metrics, independent leaderboards,
fail-closed preflight, and atomic artifacts. See `RUN_REFERENCE.md`.

No real-cache preflight or screening run has started. A candidate grammar and
strategy bundle still require user direction, and the local source inventory
must satisfy preflight. Retrospective rankings, user selection, and forward
paper testing remain incomplete. No live-money trading is authorized.
