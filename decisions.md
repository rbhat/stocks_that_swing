# Decisions

## 2026-07-29 — Fresh swing discovery

`swing-ranking-v1` discovers readable multi-timeframe swing strategies without
a plan-selected winner, model, or composite metric. Before performance was
read, the first bundle froze a balanced 144-member grammar: weekly/monthly
context above or below an EMA, three daily triggers, four volatility/structure
stops, and three risk/structure targets. This is an initial exploration grid,
not an automatic preference or promotion rule.

The study uses a chronological 60/20/20 split by XNYS session: development,
validation, then the newest 20% as unseen study OOS. A 21-session purge
separates the windows. Split dates are frozen in the study bundle before
strategy performance is read.

Historical earnings report sessions and results come from the Investing.com
custom-date earnings calendar. Upcoming schedules are snapshotted daily so
their first-known session is retained. Historical schedule knowledge remains
an explicit source limitation.

The accepted current-roster cache is reported with its survivorship and
adjusted-history limitations. Trading costs are zero. Results are ranked
independently by gross profit, maximum drawdown, and profit/drawdown. The top
five for each metric are presented with raw values and diagnostics.

There is no performance kill, qualification gate, automatic promotion, or
automatic winner. The user chooses the strategies and mix for forward paper
testing.

The checked bundle selects development evidence only. The validation selection
is a separate immutable document bound to the checked bundle hash. Complete
development and validation runs are recorded in `docs/DEVELOPMENT_RESULTS.md`
and `docs/VALIDATION_RESULTS.md`. The results are exploratory and do not
automatically select, exclude, or promote a strategy. Revision selection is
pending and study OOS remains closed for its one final opening.

`docs/PLAN.md` is the sole active plan. Source preparation is complete. The
guarded read-only real-cache preflight passed for all 250 securities and 144
frozen strategies with both authorized evidence selections. The development
and validation runs completed. No study-OOS run has started.
