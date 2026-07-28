# Swing-v1 Practical Data Contract

- **Status:** PREREGISTERED; CACHE READ NOT AUTHORIZED
- **Source:** repository-local Yahoo-derived parquet cache
- **Use:** retrospective screening and engineering only

## Accepted inputs

Gate 1 may inspect:

- `configs/study_roster_manifest.json`;
- `cache/study_frames/*.parquet`;
- `cache/study_frames/SPY.parquet`;
- the installed `exchange_calendars` XNYS session implementation; and
- `cache/catalysts/earnings.json` only if it exists, for coverage reporting.

No paid vendor, institutional source, historical constituent reconstruction,
or permanent-ID source is required. Network refresh is outside Gate 1 unless
separately authorized.

The actual symbol roster is the sorted intersection of manifest symbols and
valid parquet stems, excluding SPY/QQQ from tradable symbols while retaining
them as benchmarks. Gate 1 freezes the roster, each file hash, row count,
schema, first/last session, package versions, and one root identity.

## Screening boundary

Retrospective signals satisfy:

`2010-01-01 <= signal_date < 2026-01-01`.

Earlier rows may be used only for the 300-session warmup. Rows dated 2026 or
later may be inventoried and rejected at the boundary but cannot enter a
feature, signal, fill, outcome, metric, control, or selection decision.

This boundary is a retrospective screen cutoff, not a claim that 2024–2025
was untouched by the broader repository. No historical slice is labeled
genuinely OOS.

## Price semantics

The cache uses Yahoo `auto_adjust=True` split-and-dividend-adjusted OHLC with
recorded volume. Swing-v1 uses that single basis consistently for:

- returns, moving averages, RSI, ATR, ranges, gaps, and ranks;
- simulated entries, stops, targets, marks, exits, notional, and dollar
  volume; and
- SPY-relative features.

Raw executions, itemized dividends, split events, and historical adjustment
vintages are unavailable. They are not reconstructed or mixed into the
adjusted basis. Fixed-dollar commissions and whole-share sizing are therefore
screening approximations.

## Fatal cache checks

Gate 1 stops before implementation evidence can pass on:

- an unreadable manifest or parquet file;
- an unexpected schema outside `open, high, low, close, volume, date`;
- duplicate or non-increasing dates within a symbol;
- duplicate frozen symbols or case-colliding paths;
- negative prices or volume;
- `low > high`, or open/close outside `[low, high]`;
- a non-session row not explicitly explained by the calendar;
- any accepted row at or after `2026-01-01`;
- missing or inadequate SPY history;
- a file hash changing during a run;
- a many-to-many join or changed row cardinality;
- a future-value, shuffled-session, or wall canary passing; or
- two clean freezes producing different identities.

## Row and order treatment

Reject and count an affected opportunity for:

- incomplete signal history or stale rolling input;
- missing/nonpositive next-session open;
- invalid geometry or excessive entry gap;
- insufficient cash, risk, slots, gross capacity, liquidity, or whole shares;
- an existing position in the symbol; or
- an entry session missing from the frozen calendar.

Missing facts are never zero-filled. Rolling windows never cross a missing
row as though it were a normal session.

An unexplained missing bar while a position is open invokes the setup
contract's zero-recovery liquidation. Report every such event separately.

## Quality reporting

Mandatory output includes:

- manifest/actual symbol counts and exclusions;
- rows and date coverage by symbol;
- schema and hash inventory;
- missing expected sessions and unexplained gaps;
- OHLCV violation counts;
- screening-boundary exclusions;
- earnings-cache presence and coverage, without using it for retrospective
  selection;
- survivorship, symbol-history, adjustment, delisting, and commission-sizing
  limitations; and
- root source identity.

Coverage does not erase survivorship bias. A complete current-symbol file is
not evidence of a complete historical universe.

## Artifact separation

Authorized future Swing-v1 artifacts write only beneath:

`runs/swing-v1/<gate>/<run_id>/`.

They never write beneath `runs/ml-v2/`, predecessor study roots, or a forward
namespace before Gate 3.
