# Revision Selection Options — Source Notes

## Report contract

- Audience: product stakeholders
- Delivery mode: portable HTML
- Question: which transparent revision-selection rules are available before the one final study-OOS opening?
- Decision owner: user
- Evidence: immutable development and validation artifacts only
- OOS: closed; no OOS selection, data read, simulation, or result

## Required structure mapping

- Title: `Revision Selection Options`
- Executive summary: `Executive Summary`
- Key findings with visual evidence: rank persistence, top-20 continuity, and filled-trade overlap
- Recommended next steps: `Recommended next steps`
- Further questions: `Further questions`
- Caveats and assumptions: `Caveats and assumptions`

No KPI strip is used because this is a strategy memo, not a KPI or portfolio-status readout.

## Chart map

| Section | Question | Family / type | Fields | Supported claim | Palette |
|---|---|---|---|---|---|
| Rank persistence | Do ranks carry across windows? | Relationship / scatter | development rank, validation rank, metric | Full-field rank persistence is low and negative | Categorical, metric |
| Same-metric continuity | How much top-20 continuity remains? | Composition / 100% stacked bar | metric, continuity status, revision count | Only 1–3 of 20 leaders persist by metric | Two-root |
| Basket overlap | How similar are filled-trade signals within each option? | Comparison / grouped bar | option, window, mean Jaccard basis points | Option B has the lowest mean pairwise overlap | Two-root |

## Validation notes

- Development and validation identities align for all 144 revisions.
- `metrics.jsonl` and `ranking.json` hashes match both artifact manifests.
- Ranks use exact `Decimal` values and the locked SHA-256 tie-break.
- SQLite report queries reproduce option membership and rounded overlap summaries from the exact analysis.
- Filled-trade overlap is permanent-ID/session Jaccard, not portfolio return correlation.
- Options are not a composite ranking, gate, qualification, exclusion, or promotion.
- Canonical artifact validation and portable packaging passed.
- Portable verification is structural-only because no compatible installed Chromium was available; semantic chart tables remain embedded.
