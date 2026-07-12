# Swing Project — kickoff pack

Seed folder for a **new, standalone swing-trading project**, written 2026-07-11 from inside
`stocks_that_move` (the parent repo). Copy this folder to a fresh repo; everything here is
self-contained — no doc assumes the parent is present.

## Why a separate project (the one-paragraph case)

The parent parked its swing vertical twice (2026-07-08, 2026-07-10) — but both attempts tested
the same narrow object: the parent's *long-hold* entries with a time cap bolted on, measured in
a risk geometry (30% stop, ≥2R fib targets) where 1R = a +30% price move that almost nothing
achieves in 15 sessions. Swing-native entries (trend-conditioned pullbacks, earnings drift),
swing-native risk (ATR-scale stops, structure targets), and the multi-timeframe stack the user
keeps pointing at were **never actually tested** — the one designed study of weekly→daily
timeframes (parent Study 3) never ran. Meanwhile the parent's own data showed short-horizon
signal: positive raw forward returns at 5/10/21 sessions on every entry family, and an
avwap-252 condition predictive at every horizon. A swing system deserves its own bones — its
own risk rules, its own gates calibrated to a 5–15 session cadence, its own charter — not a
third round of retrofit-and-relitigate inside a long-hold codebase whose hard rules are
(correctly, for it) welded against exactly these changes.

## Read order

1. **VISION.md** — what this project is, success criteria, and the PROPOSED charter rules
   (you ratify/edit them in Phase 0; nothing is locked yet).
2. **PLAN.md** — the phased plan, gates, and the Phase-0 decision list.
3. **HYPOTHESES.md** — what to try: ranked setup families with the external evidence and the
   internal priors behind each.
4. **LESSONS.md** — everything the parent project learned that transfers: findings, method
   discipline, pitfalls, and the exact list of parent files worth copying.

## How to kick off the new repo

1. Copy this folder's contents to the new repo root (suggested name: `stocks_that_swing`).
2. First session prompt, roughly: *"Read README, VISION, PLAN, HYPOTHESES, LESSONS. Walk me
   through the Phase-0 decision list in PLAN.md one item at a time; record my answers in a new
   decisions.md (append-only, newest first); then mark the VISION charter rules ratified and
   start Phase 1."*
3. Phase 1 ports the battle-tested data layer from the parent (file list in LESSONS §7) —
   copy files, don't share a library; the projects will diverge.

## Status

- Charter: **PROPOSED, not ratified** — every number in VISION.md is a starting proposal.
- Parent repo: its swing vertical stays PARKED; its ledgers (`swing_decisions.md`,
  `replan_swing.md`) remain the executed record of what was tried there. This project is not
  "swing reopened under looser gates" — it is a different hypothesis object (new entries, new
  geometry) judged by its own pre-registered bars.
