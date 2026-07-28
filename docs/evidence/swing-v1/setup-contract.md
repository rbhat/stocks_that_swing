# Swing-v1 Setup and Portfolio Contract

- **Status:** PREREGISTERED; IMPLEMENTATION NOT AUTHORIZED
- **Study ID:** `swing-v1`
- **Cells:** exactly two deterministic setups
- **Search:** none

## Accepted universe

On signal session `t`, a symbol is eligible only when:

1. it belongs to the Gate 1 frozen intersection of the tracked roster and
   actual local parquet files;
2. its cache contains at least 300 completed sessions through `t`;
3. adjusted close is at least `$5`;
4. trailing 20-session median adjusted-close dollar volume is at least `$20M`;
5. signal and execution inputs pass the cache checks in `data-contract.md`;
6. it is not already held by the same setup.

Symbol text is the available historical identity. Symbol changes are not
linked, and absent/delisted names are not reconstructed. This is a declared
limitation, not a silent permanent-ID substitute.

Historical earnings coverage is unavailable and is not used in retrospective
screening. A selected forward setup must apply the charter's two-session
scheduled-earnings entry veto from contemporaneously fetched information.

## `SV1-P` — trend pullback

A signal exists at close `t` when:

- `close_t > SMA200_t`;
- `SMA50_t > SMA200_t`;
- adjusted 60-session close return is positive;
- Wilder `RSI(2)_t <= 10`;
- adjusted 5-session close return is `<= -3%`;
- `close_t >= 0.90 × prior_20_session_high`; and
- no `SV1-P` signal occurred for the symbol in the prior five sessions.

Rank same-date candidates descending by:

`0.35*pct_rank(ret126)
 + 0.25*pct_rank(close/SMA200 - 1)
 + 0.25*pct_rank(-ret5)
 + 0.15*pct_rank(volume/median_volume20)`.

## `SV1-B` — compression breakout

A signal exists at close `t` when:

- `close_t > SMA200_t`;
- adjusted 60-session close return is positive;
- `close_t > prior_20_session_high`;
- `(prior_20_session_high - prior_20_session_low) / close_t <= 20%`;
- the causal percentile of `ATR14/close` over the prior 252 sessions,
  including `t-1` and excluding `t`, is `<= 40%`;
- `volume_t / median(prior_20_session_volume) >= 1.5`; and
- no `SV1-B` signal occurred for the symbol in the prior ten sessions.

Rank same-date candidates descending by:

`0.30*pct_rank(close/prior_high20 - 1)
 + 0.25*pct_rank(volume/median_volume20)
 + 0.25*pct_rank(-ATR14_percentile252)
 + 0.20*pct_rank(ret126 - SPY_ret126)`.

## Ranking and ties

Cross-sectional percentile ranks use average ranks for equal values and only
the same setup/date candidate pool. A final score tie uses the ascending
unsigned first 16 hex characters of:

`sha256(study_id | setup_id | signal_session | symbol)`.

Alphabetical order and input row order never break a tie.

## Entry and exit

- Decision after completed session `t`.
- Marketable buy at the next available session open.
- Reject when
  `abs(next_open / signal_close - 1) > min(3%, 0.75*ATR14/signal_close)`.
- Initial stop: `entry_fill - 2.0 × ATR14_t`.
- Initial target: `entry_fill + 4.0 × ATR14_t`.
- Reject if stop distance is nonpositive or exceeds 12% of entry.
- Planned reward:risk is exactly 2.0 before friction.
- Stop and target activate on the entry session.
- When both occur in one daily bar, the stop executes first.
- A stop gap exits at the opening print less sell friction.
- A target gap receives no improvement beyond the target less sell friction.
- Intraday exits use trigger price less sell friction.
- Exit at the fifteenth session close when no earlier exit occurs.
- Terminal liquidation closes all positions at the final allowed close.
- Stops never widen; no trailing, scaling, pyramiding, or averaging down.

All prices are on the cache's single adjusted basis. Dividends and splits are
not separately added because they are already embedded in adjusted history.

If an open symbol lacks an expected next bar and the gap is not an
exchange-wide closure, liquidate it at zero recovery on the first missing
session. This conservative rule prevents a disappeared history from being
carried at its last quote.

## Portfolio

Each setup receives an independent fresh `$100,000` book:

- long only;
- 0.75% of start-of-session equity initial risk per accepted entry;
- 15% of start-of-session equity maximum position notional;
- 1% of trailing median 20-session dollar volume participation cap;
- eight concurrent positions;
- three accepted entries per session;
- 80% maximum gross deployed;
- one position per symbol;
- whole shares, no leverage, no interest, and no same-session re-entry.

Opening exits release cash and slots before new entries. Candidates are
processed in the rank frozen at the prior close. A rejected candidate may
advance to the next already-ranked candidate; it never causes outcome-aware
reranking.

## Friction

Base friction per side is 5 bps plus `$1` per order. Judged results use
doubled friction: 10 bps plus `$2` per side.

Entry slippage is added to the opening reference. Exit slippage is subtracted
from the conservative exit reference. Commissions are separate cash debits.

## Identity and separation

Swing-v1 setup, tie, source, ledger, and artifact hashes use `swing-v1`
domains. ML-v2 identities and artifacts are never reused as Swing-v1 evidence,
even when a pure implementation pattern is adapted.
