export type PatternKey = "breakout" | "pullback" | "range_bounce";

export type DataDates = {
  daily?: string | null;
  quote?: string | null;
  valuation?: string | null;
  st?: string | null;
  adj_factor?: string | null;
  [key: string]: string | null | undefined;
};

export type TimingBreakdown = Record<string, number>;

export type Bar = {
  time: string;
  trade_date?: string;
  open: number;
  high: number;
  low: number;
  close: number;
  pre_close?: number;
  change?: number;
  pct_chg?: number;
  volume: number;
  amount?: number;
  ma5?: number | null;
  ma10?: number | null;
  ma20?: number | null;
  ma60?: number | null;
};

export type StockState = {
  viewed?: boolean;
  saved?: boolean;
  pending?: boolean;
  watchlist?: boolean;
};

export type PatternMatch = {
  category: PatternKey;
  category_label: string;
  score: number;
  reasons: string[];
  metrics: Record<string, number>;
  minimum_score?: number;
};

export type Stock = {
  code: string;
  ts_code: string;
  name: string;
  initials?: string;
  market?: string;
  exchange?: string;
  industry?: string;
  close: number;
  pre_close?: number;
  pct_chg: number;
  change?: number;
  open?: number;
  high?: number;
  low?: number;
  volume?: number;
  amount?: number;
  turnover_rate?: number;
  total_mv?: number;
  circ_mv?: number;
  pe_ttm?: number;
  pb?: number;
  is_st?: boolean;
  pattern?: PatternKey;
  pattern_name?: string;
  score?: number;
  reasons?: string[];
  metrics?: Record<string, number>;
  rank?: number;
  category_rank?: number;
  sparkline?: number[];
  bars?: Bar[];
  as_of?: DataDates;
  warnings?: string[];
  state?: StockState;
};

export type ScreenCounts = {
  breakout: number;
  pullback: number;
  range_bounce: number;
};

export type ScreenProgress = {
  stage: string;
  completed: number;
  total: number;
};

export type ScreenFilters = {
  board: string;
  industries: string[];
  market_cap_min_yi: number | null;
  market_cap_max_yi: number | null;
  exclude_st: boolean;
  top_k: number;
  mode: "per_category" | "combined";
};

export type ScreenResponse = {
  items: Stock[];
  categories: Record<PatternKey, Stock[]>;
  counts: ScreenCounts;
  category_deltas: Record<PatternKey, number | null>;
  comparison_as_of?: string | null;
  total: number;
  filtered: number;
  scored: number;
  as_of: DataDates;
  warnings: string[];
  timings: TimingBreakdown;
  cache_hit: boolean;
  elapsed_ms?: number;
  run_id?: string;
  screen_token?: string;
  top_k?: number;
  filters?: Partial<ScreenFilters>;
};

export type StateItem = StockState & {
  ts_code: string;
  code: string;
  name?: string;
  symbol?: string;
  market?: string;
  viewed_at?: string | null;
  saved_at?: string | null;
  pending_at?: string | null;
  watchlist_at?: string | null;
  updated_at?: string;
  view_count?: number;
};

export type HistoryRun = {
  run_id: string;
  snapshot_date: string;
  result_count: number;
  filters: Record<string, unknown>;
  category_counts: Partial<ScreenCounts>;
  warnings: string[];
  created_at: string;
  rule_version?: string | number;
  top_k?: number;
};

export type HistoryRecommendation = {
  run_id: string;
  ts_code: string;
  code: string;
  name?: string;
  category: PatternKey;
  category_label: string;
  rank: number;
  score: number;
  reasons: string[];
  snapshot_date: string;
  created_at: string;
};

export type StateSnapshot = {
  viewed: StateItem[];
  saved: StateItem[];
  pending: StateItem[];
  watchlist: StateItem[];
  history: { runs: HistoryRun[]; recommendations: HistoryRecommendation[] };
};

export type SavedScreenSnapshot = HistoryRun & {
  saved_at?: string;
  results?: Stock[];
};

export type SavedScreenPage = {
  items: SavedScreenSnapshot[];
  page: number;
  page_size: number;
  total: number;
};

export type PatternPool = {
  category: PatternKey;
  category_label: string;
  items: Stock[];
  snapshot_id?: string | null;
};

export type StateSummary = {
  viewed: number;
  saved: number;
  pending: number;
  history: number;
};

export type PatternEvaluation = {
  run_id: string;
  status: "matched" | "no_match" | "not_calculated";
  matches: PatternMatch[];
  trade_date?: string | null;
  history_bars: number;
  warning?: string | null;
  snapshot_date: string;
  created_at: string;
  filters: Record<string, unknown>;
  run_warnings: string[];
};

export type PatternResponse = {
  ts_code: string;
  calculation_state: "not_calculated" | "calculated_no_match" | "matched";
  message: string;
  current: PatternEvaluation | null;
  history: PatternEvaluation[];
  rule_version: number;
  rules: Record<PatternKey, Record<string, string | number | boolean>>;
  as_of: DataDates;
};

export type BarsResponse = {
  items: Bar[];
  period: string;
  as_of: DataDates;
  warnings: string[];
  timings: TimingBreakdown;
  cache_hit: boolean;
  client_cache_hit?: boolean;
  http_ms?: number;
  has_more?: boolean;
  history_start?: string | null;
  history_end?: string | null;
};
