# ML-v2 Bounded Setup and Model Matrix

- **Status:** PREREGISTERED; NOT AUTHORIZED TO RUN
- **Matrix size:** exactly six setup cells
- **Search:** none

No cell may be added, removed, substituted, tuned, ensembled, or altered after
the first authorized market-data read. Each cell is a complete standalone
portfolio setup, not merely a detector or model.

## Common point-in-time eligibility

On signal session `t`, a security is eligible only when all facts were known by
the close of `t`:

1. permanent security ID is an active primary US-listed common share on NYSE,
   Nasdaq, or NYSE American;
2. point-in-time security-type and listing histories exclude ETFs, ETNs,
   funds, preferreds, ADRs, OTC securities, SPAC units, rights, warrants, and
   when-issued securities;
3. at least 300 completed exchange sessions of causal split-adjusted OHLCV
   history exist;
4. unadjusted close is at least `$5.00`;
5. trailing 20-session median unadjusted dollar volume is at least `$25M`;
6. no announced earnings event is scheduled from `t+1` through `t+2`
   exchange sessions, based on the publication state known at `t`.

Delisted names remain eligible until their point-in-time final eligible
session. Symbol changes map through permanent IDs. Missing membership,
security type, delisting, earnings-publication, or corporate-action facts make
the row ineligible; they are never inferred from today's roster or encoded as
zero.

## Two locked signal families

All rolling calculations end on `t`. High/low windows that say “prior” exclude
`t`.

### P — trend pullback

A signal exists when:

- `close_t > SMA200_t`;
- `SMA50_t > SMA200_t`;
- split-adjusted 60-session close return is strictly positive;
- Wilder `RSI(2)_t <= 10`;
- split-adjusted 5-session close return is `<= -3%`;
- `close_t >= 0.90 × prior_20_session_high`;
- no P signal occurred for the same permanent ID in the prior five exchange
  sessions.

### B — compression breakout

A signal exists when:

- `close_t > SMA200_t`;
- split-adjusted 60-session close return is strictly positive;
- `close_t > prior_20_session_high`;
- `(prior_20_session_high - prior_20_session_low) / close_t <= 20%`;
- the causal percentile rank of `ATR14 / close` within the prior 252 sessions,
  including `t-1` and excluding `t`, is `<= 40%`;
- `volume_t / median(volume, prior 20 sessions) >= 1.5`;
- no B signal occurred for the same permanent ID in the prior ten exchange
  sessions.

## Three locked ranking methods

Percentile ranks below are cross-sectional within the exact same-date signal
pool, range from 0 to 1, use average ranks for equal values, and are computed
without symbols. A final score tie is resolved by the ascending unsigned
integer represented by the first 16 hex characters of
`sha256(setup_id | signal_session | permanent_security_id)`. Symbol text is
never a sort key.

### D — deterministic mechanism score

For P:

`score = 0.35*pct_rank(ret126) + 0.25*pct_rank(close/SMA200-1)
       + 0.25*pct_rank(-ret5) + 0.15*pct_rank(volume/median_volume20)`.

For B:

`score = 0.30*pct_rank(close/prior_high20-1)
       + 0.25*pct_rank(volume/median_volume20)
       + 0.25*pct_rank(-ATR14_percentile252)
       + 0.20*pct_rank(ret126 - SPY_ret126)`.

### R — ridge profitability score

Fold-local scikit-learn `Ridge` with `alpha=10`, `solver="lsqr"`,
`tol=1e-6`, and no outcome-driven threshold. Numeric inputs receive fold-local
median imputation, explicit missing indicators, and standardization.

### H — shallow histogram-gradient-boosting profitability score

Fold-local scikit-learn `HistGradientBoostingRegressor` with:

- `max_leaf_nodes=15`;
- `learning_rate=0.05`;
- `max_iter=200`;
- `l2_regularization=10`;
- `min_samples_leaf=100`;
- `early_stopping=False`;
- native numeric missing-value handling.

R and H predict the same fixed target:

`trade_nrocc_2x = fixed_policy_net_pnl_2x / entry_fill_notional`.

Training labels use the locked execution policy below at a `$10,000`
pre-slippage reference notional, rounded down to whole shares, including fixed
commissions. A zero-share or rejected hypothetical trade has a missing label
and is excluded with an explicit reason. Models rank only; the
capital-constrained simulator determines realized portfolio inclusion and
sizing. Loss is diagnostic and cannot select a setup.

### Locked R/H feature dictionary

Only these causal numeric facts are allowed:

- split-adjusted returns over 1, 2, 5, 10, 20, 60, 126, and 252 sessions;
- close distance from 10, 20, 50, 100, and 200-session moving averages;
- realized close-to-close volatility over 5, 10, 20, and 60 sessions;
- `ATR14/close` and its causal prior-252-session percentile;
- current range/close and close location within the current range;
- signal-close versus prior-close gap;
- volume divided by trailing 5, 20, and 60-session medians;
- dollar volume divided by trailing 20 and 60-session medians;
- SPY-relative returns over 5, 20, 60, 126, and 252 sessions;
- SPY close above its causal SMA200 indicator;
- signal-family indicator P or B.

No feature selection, target-derived fact, catalyst value, fundamental, text,
sector, future membership, revised future classification, model-derived
feature, or post-result addition is allowed.

## Locked six-cell matrix

| Setup ID | Signal family | Ranking | Fit |
|---|---|---|---|
| `P-D` | trend pullback | deterministic P score | none |
| `P-R` | trend pullback | ridge | fold-local |
| `P-H` | trend pullback | shallow HGB | fold-local |
| `B-D` | compression breakout | deterministic B score | none |
| `B-R` | compression breakout | ridge | fold-local |
| `B-H` | compression breakout | shallow HGB | fold-local |

The model family is part of setup identity. A deterministic setup cannot be
replaced by a model, and a failed model cannot fall back to the deterministic
score under the same ID.

## Common executable trading policy

Every cell uses the same locked policy:

- **Decision:** after the completed signal-session close.
- **Entry:** marketable buy at the next exchange-session open, subject to all
  rejection and capacity rules.
- **Gap rejection:** reject when
  `abs(next_open / signal_close - 1) > min(3%, 0.75*ATR14/signal_close)`.
- **Initial stop:** `entry_fill - 1.5 × ATR14_t`.
- **Initial target:** `entry_fill + 3.0 × ATR14_t`.
- **Geometry:** stop distance must be positive and no more than 8% of entry;
  planned reward:risk is exactly 2.0 before slippage.
- **Management:** stop and target are active on the entry session. If both are
  inside one daily bar, the stop executes first. Orders never trail, widen,
  scale out, or move to breakeven.
- **Stop gap:** if an opening print is at or below the stop, sell at that
  opening print less sell slippage.
- **Target gap:** if an opening print is at or above the target, sell at the
  target less sell slippage; favorable gap improvement is not credited.
- **Intraday stop/target:** use the trigger price less sell slippage.
- **Maximum hold:** exit at the fifteenth exchange-session close after entry,
  counting the entry session as session 1, less sell slippage.
- **Terminal liquidation:** any open development position exits on the final
  allowed close with sell slippage and is included in the numerator.
- **Corporate actions while open:** splits adjust shares, stop, and target on
  the effective session without changing economic exposure. Certified cash
  distributions are recognized as a receivable on the ex-date and included
  in trade P&L, then settled to cash on the payable date. An unsupported
  merger, spinoff, or distribution fails the position closed under the
  certified conservative value or stops the simulation if no value exists.
- **Delisting:** use the certified delisting cash/return when available;
  otherwise assume zero recovery of that position. Never carry the last quote
  forward.

## Common sizing and allocation

Each setup is simulated separately from initial cash of `$1,000,000`:

- long-only; no leverage or shorting;
- risk budget per new position: `0.50%` of start-of-session equity;
- shares are the integer floor of the minimum allowed by:
  risk budget divided by planned per-share stop risk, 10% of start-of-session
  equity, 1% of trailing 20-session median dollar volume, and currently
  available cash;
- reject a zero-share order;
- at most eight concurrent positions;
- at most three new entries per session;
- at most one open position per permanent security ID;
- gross entry notional after all entries may not exceed 80% of
  start-of-session equity;
- no pyramiding and no same-session re-entry after an exit;
- cash earns zero.

At each session, process existing-position opening gaps, then rank and size new
orders using only prior-close facts and released cash, then process intraday
stops/targets, then time exits at the close. When cash, risk, slots, daily
entries, symbol ownership, or liquidity prevents an order, record one durable
rejection reason and do not defer or replace it after the session.

The complete candidate order is frozen at the prior close. At the opening
print, evaluate it sequentially until three orders are accepted or the list is
exhausted. A rejected order does not consume the daily-entry quota; the next
pre-ranked candidate may be evaluated immediately. Once slots, gross
allocation, or cash are exhausted, all remaining candidates receive the
corresponding skip reason. No intraday fact other than the opening print can
change the order.

Sizing is deterministic: calculate the four integer share caps using the
opening print and `1.5 × ATR14` risk, take their minimum, compute doubled
slippage from `shares × opening_print`, then reduce shares by deterministic
integer binary search if the slippage-adjusted entry cost plus commission
would breach cash, 10% equity, 1% liquidity, or 80% gross exposure. Never
increase shares after the first minimum or use a later intraday price.

## Friction and fills

Base friction per side is 5 bps of notional plus `$1` per order. The judged
doubled-friction path uses 10 bps per side plus `$2` per order and adverse
slippage:

`slippage_rate_2x =
 min(1.00%, max(0.10%, 0.10*(ATR14_t/signal_close)
                      + 0.20%*sqrt(order_notional/MDV20_t)))`.

Entry fill is `open × (1 + slippage_rate_2x)`. The entry fill, not the
unadjusted opening print, anchors stop, target, risk, and sizing. Exit fill applies
`reference_exit × (1 - slippage_rate_2x)`. The rate is fixed from causal entry
facts for the life of the trade. Commissions are deducted separately.
Base-cost diagnostics halve the explicit bps, fixed commission, and slippage
rate. The judged 2× path never receives price improvement.

`order_notional` in this formula is shares times the opening print and
`MDV20_t` is trailing 20-session median unadjusted dollar volume through `t`.

Missing/nonpositive opening prices, halts without a certified executable
print, stale inputs, invalid geometry, excessive gaps, capacity breaches, or
zero-share sizing are rejected fills. Rejections are not losses or trades, but
their counts and reasons are mandatory diagnostics.
