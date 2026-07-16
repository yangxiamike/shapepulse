export type PatternKey = "breakout" | "pullback" | "range_rebound";

export type Bar = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount?: number;
  ma5?: number | null;
  ma10?: number | null;
  ma20?: number | null;
  ma60?: number | null;
};

export type Stock = {
  code: string;
  ts_code: string;
  name: string;
  initials?: string;
  market?: string;
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
  pattern?: PatternKey;
  pattern_name?: string;
  score?: number;
  reasons?: string[];
  sparkline?: number[];
  bars?: Bar[];
};

export type ScreenResponse = {
  items: Stock[];
  counts: Record<PatternKey, number>;
  total: number;
  filtered: number;
  as_of: Record<string, string>;
  elapsed_ms?: number;
  run_id?: string;
};

export type StateSummary = {
  viewed: number;
  saved: number;
  pending: number;
  history: number;
  watchlist?: string[];
};
