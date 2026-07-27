# Success-v2 Phase 3 — IS-only candidate discovery

- Completed: 2026-07-26 (America/Los_Angeles)
- Starting commit: `433895b` (`feat: isolate success-v2 strategy boundary`)
- Screen config: `configs/success_v2_phase3.yaml`
- Config SHA-256:
  `33c1ee43371d0f6c6dd7530187556ade377a52693e4b17c974cbdaad06d0959a`
- Artifact: `runs/success-v2/phase3/discovery.json`
- Artifact SHA-256:
  `5fb4a968f2e8494c48c515378c522800d051b7c850afd19ff01245e9d738c450`

## Data wall and inputs

The discovery loader used parquet predicate filters for
`2010-01-01 <= date < 2024-01-01` and then independently rejected any
returned index outside that interval. It has no fetch or network fallback.

- 235 price frames passed the 300-row floor: 767,028 filtered rows,
  2010-01-04 through 2023-12-29.
- Five recent listings lacked adequate IS history: `ALAB` (0 rows), `ARM`
  (75), `CRWV` (0), `GEHC` (261), and `GEV` (0).
- Every loaded frame has a filtered-content hash in the artifact.
- Post-wall rows seen by discovery: **0**.
- `cache/catalysts/earnings.json` was absent. Post-earnings drift is
  `not_run_input_failure: catalyst_cache_missing`, not a zero-event result.
- No 2024–2026 bar, old OOS report, or locked historical artifact selected a
  detector, rank, geometry, throttle, or parameter.

## Fixed screen

The small mechanism-led set was fixed before the run:

- trend-conditioned pullback: three RSI/reclaim neighborhoods;
- covered-catalyst post-earnings drift: one cell, conditional on coverage;
- volatility-compression breakout: three squeeze/expansion neighborhoods;
- no exploratory fourth family.

All evaluated cells used the same explicit geometry: 14-session ATR,
2×ATR stop, 4×ATR target (2R before the charter stop clamp), and hard
15-session time stop. Entry was the actual next-session open. Each event
was simulated independently with base and 2× both-side friction. Reports
include raw h=15 returns, net profit, count, MAE, hold, year, SPY-200d
regime, exit reason, and a deterministic symbol-matched random-session
control.

Selection required the success event gate, superiority to the matched
random control at 2× costs, and at least two passing neighbor cells. This
prevents a positive bull-market drift shared by arbitrary entries from
being mislabeled as detector edge.

## Results

| Cell | Closed n | Raw h15 | Random raw h15 | Mean 2× net/event | Random mean 2× |
|---|---:|---:|---:|---:|---:|
| `tp-rsi6-w5` | 7,626 | +0.946% | +0.950% | +$38.91 | +$40.67 |
| `tp-rsi10-w7` | 14,910 | +0.946% | +1.038% | +$40.79 | +$46.25 |
| `tp-rsi14-w10` | 22,225 | +0.940% | +1.042% | +$39.87 | +$51.46 |
| `vc-tight` | 2,476 | +0.581% | +1.086% | +$18.05 | +$61.81 |
| `vc-core` | 6,994 | +0.685% | +0.888% | +$17.16 | +$39.22 |
| `vc-broad` | 17,323 | +0.685% | +1.032% | +$17.19 | +$49.48 |

Every evaluated cell passed the nominal event bars: valid >1.5R geometry,
adequate n, positive raw h=15, positive base and 2× net profit, and median
hold within 15 sessions. None beat its symbol-matched random control on
raw h=15 or mean 2× net profit. The volatility cells were also negative at
base and 2× costs in the SPY-at/below-200d slice for the core and broad
neighborhoods.

This is evidence of broad long-equity drift, not incremental detector
selection. Forcing any cell through would violate the fixed
selection-quality gate.

## Prior exposure and limitations

- The repository previously studied trend pullbacks, PEAD proxies, and
  volatility squeezes on consumed windows. These mechanisms are declared
  priors only. Phase 3 used newly named cells and pre-2024 data exclusively.
- The roster was assembled in 2026, so survivorship/constituent-selection
  bias remains. The matched symbol control reduces, but does not remove,
  that limitation.
- Catalyst coverage was unavailable, so no post-earnings candidate was
  judged.

## Verification evidence

- Focused discovery/wall suite: `5 passed`.
- Discovery-adjacent focused suite: `69 passed`.
- Full repository suite: `401 passed`.
- New discovery code and tests: targeted `ruff check` passed.
- Full repository lint remained below the Phase-0 baseline.
- `git diff --check` passed.
- Two complete runs produced byte-identical artifact SHA-256
  `5fb4a968...d738c450`.

## Phase gate

**STOP.** Candidate count is zero. Phase 3 therefore ends at its explicit
honest-STOP gate. Phase 4 is not authorized: there is no selected exact
candidate to preregister, hash, or expose to post-2026-07-27 evidence.
No collection or deployment was attempted.
