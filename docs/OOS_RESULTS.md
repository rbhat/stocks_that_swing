# Swing Ranking V1 OOS Results

- Evidence window: study OOS, 2026-03-13 through 2026-06-08
- Outcome boundary: 2026-07-10 exclusive; all recorded trades closed by 2026-06-08
- OOS artifact: `runs/swing-ranking-v1/oos-v1`
- OOS artifact identity:
  `7aa9476364d3916b292cfb4f485f353d54bbbbbb174b655344bdb906dd37b117`
- Cohort analysis: `runs/swing-ranking-v1/oos-cohort-comparison-v1`
- Cohort analysis identity:
  `22ad251f55fa7106b01b37bc79575c9e0ac3e59fa85f94a5de54924917416796`
- OOS seal: `runs/swing-ranking-v1/oos-seal-v1`
- Seal identity:
  `a9f9e0536f885663190cb2f9adf00482a11b01c371f26c975c4178b6d881b3da`
- Scope: nine preselected revisions, 6,915 candidates/orders, 333 closed
  trades, 540 daily equity records, and 7,788 events
- Costs: none assumed or deducted

The one-time OOS opening and cohort analysis are sealed. All content hashes,
strategy identities, record counts, equity-derived metrics, and closed-trade
P&L reconcile. VF9 and MC5 both proceed to forward paper unchanged because
their eligibility was recorded before OOS.

## Cohort results

| Cohort | Capital base | Ending equity | Gross P&L | Return | Maximum drawdown | Profit/drawdown | Breadth | Closed trades |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| VF9 | $900,000 | $891,559.02 | -$8,440.98 | -0.9379% | 4.0118% | -0.2338 | 2 positive / 7 negative | 333 |
| MC5 | $500,000 | $492,659.19 | -$7,340.81 | -1.4682% | 3.5972% | -0.4081 | 1 positive / 4 negative | 194 |
| FO4 | $400,000 | $398,899.83 | -$1,100.17 | -0.2750% | 4.5433% | -0.0605 | 1 positive / 3 negative | 139 |

The normalized comparison uses the same returns because every member begins
at $100,000 and cohorts equal-weight member books. FO4 lost less than MC5, so
including FO4 reduced VF9's aggregate loss. This is descriptive evidence, not
a promotion, exclusion, alternative cohort, or performance gate.

## Raw strategy books

| Revision | Membership | Gross P&L | Return | Maximum drawdown | Profit/drawdown | Trades |
|---|---:|---:|---:|---:|---:|---:|
| `monthly-ema6-above__return5-cross-zero__rolling-low20__target-risk1p75` | MC5 | $5,045.73 | 5.0457% | 3.8210% | 1.3205 | 26 |
| `weekly-ema13-below__close-cross-sma10__atr14x1p5__target-risk1p75` | FO4 | $1,578.80 | 1.5788% | 6.1386% | 0.2572 | 43 |
| `monthly-ema6-below__close-cross-sma10__atr14x1p5__target-risk2p5` | FO4 | -$444.53 | -0.4445% | 5.4898% | -0.0810 | 33 |
| `monthly-ema6-below__return5-cross-zero__rolling-low20__target-risk2p5` | FO4 | -$1,040.96 | -1.0410% | 5.0455% | -0.2063 | 29 |
| `monthly-ema6-below__close-cross-sma10__rolling-low10__target-risk1p75` | FO4 | -$1,193.47 | -1.1935% | 5.2916% | -0.2255 | 34 |
| `weekly-ema13-below__close-cross-ema5__atr14x1__target-risk1p75` | MC5 | -$1,545.85 | -1.5459% | 5.3569% | -0.2886 | 70 |
| `weekly-ema13-below__return5-cross-zero__rolling-low20__target-risk2p5` | MC5 | -$1,929.39 | -1.9294% | 4.5059% | -0.4282 | 32 |
| `monthly-ema6-below__close-cross-sma10__rolling-low20__target-risk2p5` | MC5 | -$2,365.63 | -2.3656% | 4.5154% | -0.5239 | 28 |
| `monthly-ema6-below__close-cross-sma10__atr14x1p5__target-rolling-high20` | MC5 | -$6,545.66 | -6.5457% | 7.8218% | -0.8369 | 38 |

## Concentration and overlap

- VF9's largest profitable revision supplied 76.17% of gross positive P&L;
  total losses were 227.42% of gross gains.
- MC5 had one profitable revision, so it supplied all gross positive P&L;
  total losses were 245.49% of gross gains.
- Removing the largest losing revision improved VF9 to -0.2369% and MC5 to
  -0.1988%; removing the sole profitable MC5 revision worsened VF9 to -1.6858%
  and MC5 to -3.0966%.
- Across all 36 strategy pairs, mean exact filled-trade Jaccard overlap was
  8.48%, with a 36.73% maximum. Mean symbol overlap was 21.98%; mean entry-time
  overlap was 43.64%.

The complete leave-one-out and overlap records are retained in the sealed
cohort analysis. These diagnostics do not change membership.

## Forward state

Forward run `swing-ranking-v1-forward-01` is initialized at
`runs/swing-ranking-v1-forward-01` with identity
`5fd0d4a27a8aad5d1e9b47fd43d76fe05c21f61bde569c3ed99bc0fff8e6083d`.
It contains the same nine revisions, VF9/MC5/FO4 memberships, charter,
aggregation, and metrics. No data were backfilled. The first eligible signal
session is 2026-08-03. Ten- and twenty-trade views are descriptive; evidence
is decision-ready only after every revision has at least 30 closed trades.

## Limitations

- The accepted current roster introduces survivorship, symbol-history, and
  delisting limitations.
- Historical earnings report sessions are known on the event session, so the
  two-session retrospective earnings blackout cannot be reconstructed.
- Yahoo adjusted history is tied to its recorded adjustment vintage.
- This is one historical OOS window. It does not establish stable future
  performance or causality; unchanged forward paper is the next evidence.
