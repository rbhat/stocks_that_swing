# Swing Ranking V1 Development Results

- Evidence window: development, 2025-03-28 through 2025-11-12
- Artifact: `runs/swing-ranking-v1/development-v1`
- Artifact identity:
  `0a3d7a1a04bac3800af4ed663267d0c210784bb82aab1f0e37c1f6b9b1551340`
- Scope: 250 current-roster securities and 144 frozen strategy revisions
- Records: 313,404 candidates/orders; 19,241 closed trades; 43,200 daily
  equity records; 375,845 events
- Costs: none assumed or deducted

All manifest content hashes and record counts reconcile. These are development
rankings, not validation or study-OOS results. They do not select, qualify,
exclude, or promote a strategy.

## Top five by gross profit

| Rank | Strategy | Gross profit | Max drawdown | Profit/drawdown | Trades | Median hold |
|---:|---|---:|---:|---:|---:|---:|
| 1 | `monthly-ema6-above__close-cross-ema5__atr14x1__target-risk1p75` | $32,868.84 | 6.9018% | 4.7623 | 217 | 4 |
| 2 | `monthly-ema6-above__return5-cross-zero__atr14x1__target-rolling-high20` | $29,218.37 | 4.3743% | 6.6796 | 164 | 5 |
| 3 | `monthly-ema6-above__close-cross-sma10__atr14x1__target-rolling-high20` | $27,395.67 | 4.0800% | 6.7145 | 181 | 4 |
| 4 | `monthly-ema6-above__close-cross-ema5__atr14x1__target-risk2p5` | $25,563.67 | 6.1139% | 4.1813 | 166 | 6 |
| 5 | `monthly-ema6-above__close-cross-ema5__atr14x1p5__target-risk1p75` | $23,576.11 | 4.9068% | 4.8048 | 134 | 7 |

## Top five by lowest maximum drawdown

| Rank | Strategy | Gross profit | Max drawdown | Profit/drawdown | Trades | Median hold |
|---:|---|---:|---:|---:|---:|---:|
| 1 | `weekly-ema13-above__close-cross-sma10__atr14x1p5__target-rolling-high20` | $10,123.66 | 3.8542% | 2.6267 | 108 | 7 |
| 2 | `weekly-ema13-above__close-cross-sma10__atr14x1__target-risk1p75` | $10,129.80 | 3.9356% | 2.5739 | 229 | 4 |
| 3 | `weekly-ema13-above__return5-cross-zero__atr14x1p5__target-rolling-high20` | $11,427.26 | 4.0640% | 2.8118 | 104 | 8.5 |
| 4 | `monthly-ema6-above__close-cross-sma10__atr14x1__target-rolling-high20` | $27,395.67 | 4.0800% | 6.7145 | 181 | 4 |
| 5 | `monthly-ema6-above__close-cross-sma10__atr14x1__target-risk1p75` | $20,655.25 | 4.0940% | 5.0452 | 218 | 4 |

## Top five by profit/drawdown

| Rank | Strategy | Gross profit | Max drawdown | Profit/drawdown | Trades | Median hold |
|---:|---|---:|---:|---:|---:|---:|
| 1 | `monthly-ema6-above__close-cross-sma10__atr14x1__target-rolling-high20` | $27,395.67 | 4.0800% | 6.7145 | 181 | 4 |
| 2 | `monthly-ema6-above__return5-cross-zero__atr14x1__target-rolling-high20` | $29,218.37 | 4.3743% | 6.6796 | 164 | 5 |
| 3 | `monthly-ema6-above__close-cross-sma10__atr14x1__target-risk1p75` | $20,655.25 | 4.0940% | 5.0452 | 218 | 4 |
| 4 | `monthly-ema6-above__close-cross-ema5__atr14x1p5__target-risk1p75` | $23,576.11 | 4.9068% | 4.8048 | 134 | 7 |
| 5 | `monthly-ema6-above__close-cross-ema5__atr14x1__target-risk1p75` | $32,868.84 | 6.9018% | 4.7623 | 217 | 4 |

## Limitations

- The accepted current roster introduces survivorship, symbol-history, and
  delisting limitations; these are not untouched out-of-sample results.
- Historical earnings report sessions are known on the event session, so the
  two-session retrospective earnings blackout cannot be reconstructed.
- Yahoo adjusted history is tied to its recorded adjustment vintage.
- Validation and study OOS remain closed.
