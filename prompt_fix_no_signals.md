# Context-clear kickoff prompt

Read `report_why_no_signals.md` and `plan_fix_no_signals.md` completely, then implement the plan end to end with full permissions.
Work localhost-first and do not call `gcloud` until every local gate passes; preserve existing user changes and all strategy/ledger invariants.
After every phase, save its evidence, run its acceptance gate, and create a focused commit before starting the next phase.
Do not stop at a partial fix: close the loop through causal replay, crash/retry parity, docs, safe deployment, and production verification.
