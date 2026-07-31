-- Report datasets for swing-ranking-v1 revision selection.
-- The loader supplies raw_revision_metrics and raw_filled_trade_signals after
-- manifest/hash verification and exact Decimal ranking in analysis.py.

DROP VIEW IF EXISTS option_members;
DROP VIEW IF EXISTS report_rank_scatter;
DROP VIEW IF EXISTS report_top20_continuity;
DROP VIEW IF EXISTS option_pairs;
DROP VIEW IF EXISTS option_pair_overlap;
DROP VIEW IF EXISTS report_option_overlap;
DROP VIEW IF EXISTS report_option_revisions;

CREATE TEMP VIEW option_members AS
SELECT 'A' AS option, identity
FROM raw_revision_metrics
WHERE validation_profit_rank <= 5
   OR validation_drawdown_rank <= 5
   OR validation_ratio_rank <= 5
UNION ALL
SELECT 'B' AS option, identity
FROM raw_revision_metrics
WHERE (validation_profit_rank <= 5)
    + (validation_drawdown_rank <= 5)
    + (validation_ratio_rank <= 5) >= 2
UNION ALL
SELECT 'C' AS option, identity
FROM raw_revision_metrics
WHERE (development_profit_rank <= 20 AND validation_profit_rank <= 20)
   OR (development_drawdown_rank <= 20 AND validation_drawdown_rank <= 20)
   OR (development_ratio_rank <= 20 AND validation_ratio_rank <= 20);

CREATE TEMP VIEW report_rank_scatter AS
SELECT
    name AS revision,
    substr(identity, 1, 12) AS identity_prefix,
    'Gross profit' AS metric,
    development_profit_rank AS development_rank,
    validation_profit_rank AS validation_rank,
    development_trades,
    validation_trades,
    CASE
        WHEN development_profit_rank <= 20 AND validation_profit_rank <= 20
        THEN 'Yes' ELSE 'No'
    END AS shared_top20_same_metric
FROM raw_revision_metrics
UNION ALL
SELECT
    name,
    substr(identity, 1, 12),
    'Lowest maximum drawdown',
    development_drawdown_rank,
    validation_drawdown_rank,
    development_trades,
    validation_trades,
    CASE
        WHEN development_drawdown_rank <= 20 AND validation_drawdown_rank <= 20
        THEN 'Yes' ELSE 'No'
    END
FROM raw_revision_metrics
UNION ALL
SELECT
    name,
    substr(identity, 1, 12),
    'Profit/drawdown',
    development_ratio_rank,
    validation_ratio_rank,
    development_trades,
    validation_trades,
    CASE
        WHEN development_ratio_rank <= 20 AND validation_ratio_rank <= 20
        THEN 'Yes' ELSE 'No'
    END
FROM raw_revision_metrics;

CREATE TEMP VIEW report_top20_continuity AS
SELECT
    'Gross profit' AS metric,
    'Shared top 20' AS continuity,
    SUM(development_profit_rank <= 20 AND validation_profit_rank <= 20) AS revisions,
    20 AS top20_denominator
FROM raw_revision_metrics
UNION ALL
SELECT
    'Gross profit',
    'Not shared',
    20 - SUM(development_profit_rank <= 20 AND validation_profit_rank <= 20),
    20
FROM raw_revision_metrics
UNION ALL
SELECT
    'Lowest maximum drawdown',
    'Shared top 20',
    SUM(development_drawdown_rank <= 20 AND validation_drawdown_rank <= 20),
    20
FROM raw_revision_metrics
UNION ALL
SELECT
    'Lowest maximum drawdown',
    'Not shared',
    20 - SUM(development_drawdown_rank <= 20 AND validation_drawdown_rank <= 20),
    20
FROM raw_revision_metrics
UNION ALL
SELECT
    'Profit/drawdown',
    'Shared top 20',
    SUM(development_ratio_rank <= 20 AND validation_ratio_rank <= 20),
    20
FROM raw_revision_metrics
UNION ALL
SELECT
    'Profit/drawdown',
    'Not shared',
    20 - SUM(development_ratio_rank <= 20 AND validation_ratio_rank <= 20),
    20
FROM raw_revision_metrics;

CREATE TEMP VIEW option_pairs AS
SELECT
    left_member.option,
    left_member.identity AS left_identity,
    right_member.identity AS right_identity
FROM option_members AS left_member
JOIN option_members AS right_member
  ON right_member.option = left_member.option
 AND right_member.identity > left_member.identity;

CREATE TEMP VIEW option_pair_overlap AS
SELECT
    pairs.option,
    evidence.window,
    pairs.left_identity,
    pairs.right_identity,
    (
        SELECT COUNT(*)
        FROM raw_filled_trade_signals AS left_signal
        WHERE left_signal.window = evidence.window
          AND left_signal.identity = pairs.left_identity
          AND EXISTS (
              SELECT 1
              FROM raw_filled_trade_signals AS right_signal
              WHERE right_signal.window = left_signal.window
                AND right_signal.identity = pairs.right_identity
                AND right_signal.signal_key = left_signal.signal_key
          )
    ) AS intersection_count,
    (
        SELECT COUNT(*)
        FROM raw_filled_trade_signals AS left_signal
        WHERE left_signal.window = evidence.window
          AND left_signal.identity = pairs.left_identity
    ) AS left_count,
    (
        SELECT COUNT(*)
        FROM raw_filled_trade_signals AS right_signal
        WHERE right_signal.window = evidence.window
          AND right_signal.identity = pairs.right_identity
    ) AS right_count
FROM option_pairs AS pairs
CROSS JOIN (
    SELECT 'development' AS window
    UNION ALL
    SELECT 'validation'
) AS evidence;

CREATE TEMP VIEW report_option_overlap AS
SELECT
    option,
    window,
    CAST(
        ROUND(
            AVG(
                1.0 * intersection_count
                / NULLIF(left_count + right_count - intersection_count, 0)
            ) * 10000
        ) AS INTEGER
    ) AS mean_overlap_bp,
    CAST(
        ROUND(
            MAX(
                1.0 * intersection_count
                / NULLIF(left_count + right_count - intersection_count, 0)
            ) * 10000
        ) AS INTEGER
    ) AS maximum_overlap_bp,
    COUNT(*) AS pair_count
FROM option_pair_overlap
GROUP BY option, window;

CREATE TEMP VIEW report_option_revisions AS
SELECT
    members.option,
    metrics.*
FROM option_members AS members
JOIN raw_revision_metrics AS metrics
  ON metrics.identity = members.identity;
