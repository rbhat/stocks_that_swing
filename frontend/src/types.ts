// Decimal-valued fields arrive as the strings the artifacts store. Parse them
// with `num()` from format.ts only at the point of drawing or formatting;
// never round-trip them back into the API.

export type Integrity = {
  status: "ok" | "partial" | "degraded" | "unavailable";
  checked: number;
  mismatched: string[];
  missing: string[];
  detail: string;
};

export type CohortSummary = {
  cohort: string;
  member_count: number;
  members_resolved: number;
  forward_eligible: boolean;
  role: "forward" | "diagnostic";
  closed_trades: number;
  minimum_closed_trades_per_revision: number;
  open_positions: number;
  starting_capital: string | null;
  current_equity: string | null;
  evidence_tier: string;
  charter_status: string;
};

export type Book = {
  strategy_revision_identity: string;
  strategy_name: string;
  memberships: string[];
  status: string;
  starting_equity: string;
  current_equity: string;
  closed_trades: number;
  open_positions: number;
  maximum_drawdown: string;
  maximum_drawdown_dollars: string;
  turnover: string;
  session_count: number;
};

export type ForwardOverview = {
  run_id: string;
  present: boolean;
  status: string;
  as_of: string;
  last_processed_session: string | null;
  next_eligible_signal_session: string | null;
  first_eligible_signal_session: string;
  no_backfill: boolean;
  paper_only: boolean;
  decision_readiness: string;
  evidence_thresholds: {
    decision_ready_closed_trades_per_revision?: number;
    interim_closed_trades_per_revision?: number[];
  };
  forward_eligible_cohorts: string[];
  identities: Record<string, string>;
  strategy_count: number;
  closed_trades: number;
  minimum_closed_trades_per_revision: number;
  open_positions: number;
  session_count: number;
  cohorts: CohortSummary[];
  books: Book[];
  integrity: Integrity;
};

export type EquityPoint = {
  session: string;
  cohort: string;
  member_count: number;
  raw_equity: string;
  normalized_index: string;
  drawdown: string;
  starting_capital: string;
};

export type Trade = {
  strategy_revision_identity: string;
  symbol?: string;
  permanent_id?: string;
  entry_session?: string;
  exit_session?: string;
  entry_price?: string;
  exit_price?: string;
  quantity?: string;
  gross_pnl?: string;
  exit_reason?: string;
};

export type CohortDetail = {
  cohort: string;
  summary: CohortSummary | null;
  members: Book[];
  equity: EquityPoint[];
  trades: Trade[];
};

export type WindowSummary = {
  window: string;
  present: boolean;
  evidence_label: string;
  evidence_window: string;
  evidence_start: string;
  evidence_end_exclusive: string;
  outcome_end_exclusive: string;
  artifact_identity: string;
  strategy_count: number;
  record_counts: Record<string, number>;
};

export type RankedEntry = {
  rank: number;
  strategy_revision_identity: string;
  strategy_name: string;
  gross_profit: string;
  gross_return: string;
  maximum_drawdown: string;
  profit_drawdown: string;
  profit_drawdown_status: string;
  trade_count: number | null;
  turnover: string;
  break_even_proportional_cost: string;
};

export type WindowDetail = {
  window: string;
  summary: WindowSummary | null;
  present: boolean;
  rankings: Record<string, RankedEntry[]>;
  ranking_identity: string;
  limitations: { kind: string; statement: string }[];
  source_hashes: Record<string, string>;
  report: string;
  integrity: Integrity;
};

export type Seal = {
  present: boolean;
  status: string;
  seal_identity: string;
  selection_identity: string;
  cohort_analysis_identity: string;
  oos_artifact_identity: string;
  forward_eligibility: string;
  forward_eligible_cohorts: string[];
  sealed_on: string;
};

export type CohortMetric = {
  cohort: string;
  member_count: number;
  closed_trades: number;
  starting_capital: string;
  ending_equity: string;
  gross_profit: string;
  gross_return: string;
  maximum_drawdown: string;
  maximum_drawdown_dollars: string;
  profit_drawdown: string;
  positive_revision_count: number;
  negative_revision_count: number;
  flat_revision_count: number;
  median_revision_return: string;
  largest_share_of_gross_positive_profit: string;
  top_three_share_of_gross_positive_profit: string;
  losses_offset_share_of_gains: string;
};

export type StrategyMetric = {
  strategy_revision_identity: string;
  strategy_name: string;
  display_name: string;
  membership: string;
  closed_trades: number;
  starting_equity: string;
  ending_equity: string;
  gross_profit: string;
  gross_return: string;
  maximum_drawdown: string;
  maximum_drawdown_dollars: string;
  profit_drawdown: string;
  turnover: string;
  exposure_mean: string;
  exposure_maximum: string;
  break_even_proportional_cost: string | null;
};

export type LeaveOneOut = {
  cohort: string;
  omitted_strategy_name: string;
  omitted_strategy_revision_identity: string;
  starting_capital: string;
  ending_equity: string;
  gross_profit: string;
  gross_return: string;
  maximum_drawdown: string;
  maximum_drawdown_dollars: string;
  profit_drawdown: string;
};

export type Overlap = {
  left_strategy_revision_identity: string;
  right_strategy_revision_identity: string;
  entry_session_jaccard: string;
  filled_trade_jaccard: string;
  symbol_jaccard: string;
  shared_filled_trades: number;
};

export type CohortComparison = {
  present: boolean;
  source: Record<string, string>;
  analysis_identity: string;
  record_counts: Record<string, number>;
  cohort_metrics: CohortMetric[];
  strategy_metrics: StrategyMetric[];
  cohort_equity: EquityPoint[];
  leave_one_out: LeaveOneOut[];
  overlap: Overlap[];
  charts: { id: string; family: string; dataset: string; fields: string[] }[];
  report: string;
  integrity: Integrity;
};

export type ReportCandle = {
  session: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: number;
  indicators: Record<string, string>;
};

export type ReportTradeExample = {
  kind: "win" | "loss";
  fallback: boolean;
  trade: {
    trade_identity: string;
    candidate_identity: string;
    symbol: string;
    permanent_id: string;
    entry_session: string;
    exit_session: string;
    entry_price: string;
    exit_price: string;
    quantity: string;
    gross_pnl: string;
    exit_reason: string;
  };
  geometry: {
    initial_stop_price: string;
    target_price: string;
    planned_hold_sessions: number | null;
  };
  signal: {
    signal_session: string;
    signal_close: string;
    average_dollar_volume: string;
    priority_value: string;
    facts: Record<string, string>;
  };
  candles: ReportCandle[];
  plotted_indicators: string[];
};

export type ReportStrategy = {
  strategy_revision_identity: string;
  strategy_name: string;
  display_name: string;
  membership: string;
  description: string;
  provenance: {
    why_chosen: string;
    found_by: string;
    tested_by: string;
  };
  rules: string[];
  features: string[];
  stats: {
    closed_trades: number;
    wins: number;
    losses: number;
    flats: number;
    gross_profit: string;
    gross_return: string;
    maximum_drawdown: string;
    maximum_drawdown_dollars: string;
    profit_drawdown: string;
    turnover: string;
    exposure_mean: string;
    exposure_maximum: string;
    break_even_proportional_cost: string | null;
  };
  examples: ReportTradeExample[];
};

export type ProjectReport = {
  present: boolean;
  title: string;
  goal: string;
  conclusion: string[];
  source: Record<string, string>;
  cohort_equity: EquityPoint[];
  cohorts: {
    cohort: string;
    description: string;
    metrics: CohortMetric;
    strategies: ReportStrategy[];
  }[];
  limitations: { kind: string; statement: string }[];
  integrity: Integrity;
};

export type Overview = {
  forward: ForwardOverview;
  backtests: WindowSummary[];
  cohort_comparison_present: boolean;
  seal: Seal;
  integrity: Record<string, Integrity>;
  degraded: string[];
  partial: string[];
};

export type Me = { email: string | null; role: string | null };

export type LegacyRow = Record<string, unknown>;

export type LegacyOverview = {
  equity: LegacyRow[];
  tiles: {
    total_pnl: number;
    open_count: number;
    usd_deployed: number;
    win_rate: number | null;
  };
  open_positions: LegacyRow[];
  recent_signals: LegacyRow[];
};

export type LegacyForward = { rows: LegacyRow[]; open: LegacyRow[] };

export type LegacyBacktest = {
  family: string;
  generated_at?: string;
  verdict?: string | null;
  metrics?: LegacyRow;
  trades?: LegacyRow[] | null;
  equity_curve?: LegacyRow[] | null;
  source_paths?: string[];
};

export type LegacyConfig = {
  universe: unknown;
  study_roster: unknown;
  env: Record<string, string>;
  editable: Record<string, boolean | number>;
  schema: Record<string, string>;
};

export type LegacyJob = {
  name: string;
  status: string;
  last_run: string | null;
  next_run: string | null;
};
