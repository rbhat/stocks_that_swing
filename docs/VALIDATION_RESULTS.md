# Swing Ranking V1 Validation Results

- Evidence window: validation, 2025-12-15 through 2026-02-10
- Outcome boundary: 2026-03-13 exclusive
- Artifact: `runs/swing-ranking-v1/validation-v1`
- Artifact identity:
  `25157f4ee3a913f066d49cd4287e1b5090f84bed5201ae7e7bca602944ebb98e`
- Scope: 250 current-roster securities and 144 frozen strategy revisions
- Records: 79,056 candidates/orders; 5,993 closed trades; 8,640 daily equity
  records; 93,689 events
- Costs: none assumed or deducted

All 154 manifest content hashes, record identities, event chains, accounting
totals, metric formulas, and rankings reconcile. Every strategy contains
exactly 60 equity sessions: 39 validation sessions plus the 21-session outcome
purge. No record reaches the study-OOS start on 2026-03-13.

These validation rankings inform revision selection only. They do not
automatically select, qualify, exclude, or promote a strategy. Study OOS
remains closed.

## Top five by gross profit

| Rank | Strategy | Gross profit | Max drawdown | Profit/drawdown | Trades | Median hold |
|---:|---|---:|---:|---:|---:|---:|
| 1 | `monthly-ema6-below__close-cross-sma10__atr14x1p5__target-risk2p5` | $10,418.13 | 3.4365% | 3.0316 | 26 | 12.5 |
| 2 | `monthly-ema6-below__close-cross-sma10__rolling-low10__target-risk1p75` | $9,740.49 | 3.7769% | 2.5790 | 30 | 11 |
| 3 | `monthly-ema6-below__close-cross-sma10__atr14x1p5__target-rolling-high20` | $9,014.92 | 1.9963% | 4.5158 | 37 | 5 |
| 4 | `weekly-ema13-below__close-cross-ema5__atr14x1__target-risk1p75` | $8,670.94 | 2.2161% | 3.9127 | 67 | 4 |
| 5 | `monthly-ema6-below__close-cross-sma10__rolling-low20__target-risk2p5` | $8,012.87 | 1.4765% | 5.4270 | 20 | 20.5 |

## Top five by lowest maximum drawdown

| Rank | Strategy | Gross profit | Max drawdown | Profit/drawdown | Trades | Median hold |
|---:|---|---:|---:|---:|---:|---:|
| 1 | `monthly-ema6-below__close-cross-sma10__rolling-low20__target-risk2p5` | $8,012.87 | 1.4765% | 5.4270 | 20 | 20.5 |
| 2 | `weekly-ema13-below__return5-cross-zero__rolling-low20__target-risk2p5` | $7,111.94 | 1.6101% | 4.4170 | 26 | 15.5 |
| 3 | `monthly-ema6-below__return5-cross-zero__rolling-low20__target-risk2p5` | $6,527.92 | 1.7097% | 3.8182 | 23 | 15 |
| 4 | `weekly-ema13-below__close-cross-sma10__atr14x1p5__target-risk1p75` | $3,906.28 | 1.7330% | 2.2540 | 41 | 7 |
| 5 | `monthly-ema6-above__return5-cross-zero__rolling-low20__target-risk1p75` | $7,055.16 | 1.7681% | 3.9903 | 21 | 21 |

## Top five by profit/drawdown

| Rank | Strategy | Gross profit | Max drawdown | Profit/drawdown | Trades | Median hold |
|---:|---|---:|---:|---:|---:|---:|
| 1 | `monthly-ema6-below__close-cross-sma10__rolling-low20__target-risk2p5` | $8,012.87 | 1.4765% | 5.4270 | 20 | 20.5 |
| 2 | `monthly-ema6-below__close-cross-sma10__atr14x1p5__target-rolling-high20` | $9,014.92 | 1.9963% | 4.5158 | 37 | 5 |
| 3 | `weekly-ema13-below__return5-cross-zero__rolling-low20__target-risk2p5` | $7,111.94 | 1.6101% | 4.4170 | 26 | 15.5 |
| 4 | `monthly-ema6-above__return5-cross-zero__rolling-low20__target-risk1p75` | $7,055.16 | 1.7681% | 3.9903 | 21 | 21 |
| 5 | `weekly-ema13-below__close-cross-ema5__atr14x1__target-risk1p75` | $8,670.94 | 2.2161% | 3.9127 | 67 | 4 |

## Cross-metric comparison

| Strategy | Gross profit | Profit rank | Max drawdown | Drawdown rank | Profit/drawdown | Ratio rank |
|---|---:|---:|---:|---:|---:|---:|
| `monthly-ema6-below__close-cross-sma10__rolling-low10__target-risk1p75` | $9,740.49 | 2 | 3.7769% | 82 | 2.5790 | 15 |
| `monthly-ema6-above__return5-cross-zero__rolling-low20__target-risk1p75` | $7,055.16 | 13 | 1.7681% | 5 | 3.9903 | 4 |
| `monthly-ema6-below__return5-cross-zero__rolling-low20__target-risk2p5` | $6,527.92 | 21 | 1.7097% | 3 | 3.8182 | 6 |
| `monthly-ema6-below__close-cross-sma10__atr14x1p5__target-risk2p5` | $10,418.13 | 1 | 3.4365% | 70 | 3.0316 | 11 |
| `monthly-ema6-below__close-cross-sma10__atr14x1p5__target-rolling-high20` | $9,014.92 | 3 | 1.9963% | 8 | 4.5158 | 2 |
| `weekly-ema13-below__close-cross-ema5__atr14x1__target-risk1p75` | $8,670.94 | 4 | 2.2161% | 20 | 3.9127 | 5 |
| `weekly-ema13-below__return5-cross-zero__rolling-low20__target-risk2p5` | $7,111.94 | 11 | 1.6101% | 2 | 4.4170 | 3 |
| `monthly-ema6-below__close-cross-sma10__rolling-low20__target-risk2p5` | $8,012.87 | 5 | 1.4765% | 1 | 5.4270 | 1 |
| `weekly-ema13-below__close-cross-sma10__atr14x1p5__target-risk1p75` | $3,906.28 | 58 | 1.7330% | 4 | 2.2540 | 24 |

## Validation assessment

- The validation artifact is ready for revision-selection review with the
  stated source limitations.
- The nine-strategy validation top-five union has no member in common with the
  nine-strategy development top-five union. This is observed rank instability,
  not an exclusion rule or a causal regime claim.
- The validation entry window contains 39 sessions. Leaderboard trade counts
  range from 20 to 67, so sample size and window sensitivity remain material
  diagnostics.

## Limitations

- The accepted current roster introduces survivorship, symbol-history, and
  delisting limitations; these are not untouched out-of-sample results.
- Historical earnings report sessions are known on the event session, so the
  two-session retrospective earnings blackout cannot be reconstructed.
- Yahoo adjusted history is tied to its recorded adjustment vintage.
- Study OOS remains closed.
