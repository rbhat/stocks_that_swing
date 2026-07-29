# Decisions

## 2026-07-29 — Fresh swing discovery

`swing-ranking-v1` discovers readable multi-timeframe swing strategies without
preselecting strategy families, behaviors, indicators, targets, models,
parameter ranges or a composite metric.

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

`docs/PLAN.md` is the sole active plan. No real-cache preflight or study run
has started.
