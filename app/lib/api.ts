import type { Bar, PatternKey, ScreenResponse, StateSummary, Stock } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_MARKET_API || "http://127.0.0.1:8765/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `本地数据服务返回 ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function numeric(value: unknown) { const n = Number(value); return Number.isFinite(n) ? n : 0; }
function symbolOf(value: unknown) { return String(value || "").split(".")[0].padStart(6, "0"); }

function mapStock(raw: Record<string, unknown>): Stock {
  const quote = (raw.quote || {}) as Record<string, unknown>;
  const valuation = (raw.valuation || {}) as Record<string, unknown>;
  const industry = (raw.industry || {}) as Record<string, unknown>;
  const category = String(raw.category || "breakout");
  const pattern: PatternKey = category === "range_bounce" ? "range_rebound" : category as PatternKey;
  const code = symbolOf(raw.symbol || raw.code || raw.ts_code);
  return {
    code,
    ts_code: String(raw.ts_code || raw.code || ""),
    name: String(raw.name || "—"),
    initials: String(raw.initials || raw.pinyin || raw.cnspell || ""),
    market: String(raw.market || ""),
    industry: String(industry.name || raw.industry_name || ""),
    close: numeric(raw.close ?? quote.close ?? valuation.close),
    pre_close: numeric(raw.pre_close ?? quote.pre_close),
    pct_chg: numeric(raw.pct_chg ?? quote.pct_chg),
    change: numeric(raw.change ?? quote.change),
    open: numeric(raw.open ?? quote.open),
    high: numeric(raw.high ?? quote.high),
    low: numeric(raw.low ?? quote.low),
    volume: numeric(raw.volume ?? raw.vol ?? quote.vol),
    amount: numeric(raw.amount ?? quote.amount),
    turnover_rate: numeric(raw.turnover_rate ?? valuation.turnover_rate),
    total_mv: numeric(raw.total_mv ?? valuation.total_mv ?? (numeric(raw.total_mv_yi) * 10000)),
    circ_mv: numeric(raw.circ_mv ?? valuation.circ_mv ?? (numeric(raw.circ_mv_yi) * 10000)),
    pattern,
    pattern_name: String(raw.category_label || raw.pattern_name || ""),
    score: numeric(raw.score),
    reasons: Array.isArray(raw.reasons) ? raw.reasons.map(String) : [],
    sparkline: Array.isArray(raw.sparkline) ? raw.sparkline.map(numeric) : [],
  };
}

function withMovingAverages(items: Bar[]) {
  const periods = [5, 10, 20, 60] as const;
  return items.map((bar, index) => {
    const enriched: Bar = { ...bar };
    for (const p of periods) {
      if (index + 1 < p) continue;
      const mean = items.slice(index + 1 - p, index + 1).reduce((sum, item) => sum + item.close, 0) / p;
      enriched[`ma${p}` as "ma5"] = Number(mean.toFixed(3));
    }
    return enriched;
  });
}

function mapState(raw: Record<string, unknown>): StateSummary {
  const history = (raw.history || {}) as Record<string, unknown>;
  return {
    viewed: Array.isArray(raw.viewed) ? raw.viewed.length : numeric(raw.viewed),
    saved: Array.isArray(raw.saved) ? raw.saved.length : numeric(raw.saved),
    pending: Array.isArray(raw.pending) ? raw.pending.length : numeric(raw.pending),
    history: Array.isArray(history.runs) ? history.runs.length : numeric(raw.history),
    watchlist: Array.isArray(raw.watchlist) ? raw.watchlist.map(item => symbolOf((item as Record<string, unknown>).ts_code)) : [],
  };
}

export const api = {
  health: async () => {
    const raw = await request<Record<string, unknown>>("/health");
    return { status: raw.ok ? "ok" : "error", as_of: (raw.snapshots || {}) as Record<string, string> };
  },
  search: async (query: string) => {
    const raw = await request<{ results: Array<Record<string, unknown>> }>(`/search?q=${encodeURIComponent(query)}`);
    return { items: (raw.results || []).map(mapStock) };
  },
  stock: async (code: string) => mapStock(await request<Record<string, unknown>>(`/stock/${encodeURIComponent(code)}`)),
  bars: async (code: string, period = "D", start = "20150101") => {
    const periodMap: Record<string, string> = { D: "1d", W: "1w", M: "1m", Q: "1m", Y: "1m" };
    const raw = await request<{ bars: Bar[]; period: string; as_of: Record<string, string> }>(
      `/bars/${encodeURIComponent(code)}?period=${periodMap[period] || period}&start=${start}`,
    );
    return { items: withMovingAverages(raw.bars || []), period: raw.period, as_of: raw.as_of || {} };
  },
  screen: async (query: string): Promise<ScreenResponse> => {
    const incoming = new URLSearchParams(query);
    const boardMap: Record<string, string> = { mainboard: "主板", chinext: "创业板", star: "科创板" };
    const params = new URLSearchParams({
      board: boardMap[incoming.get("board") || "mainboard"] || "主板",
      operator: incoming.get("mv_operator") || "gte",
      market_cap_yi: incoming.get("mv_value") || "50",
      exclude_st: incoming.get("exclude_st") || "true",
      top_k: incoming.get("top_k") || "50",
    });
    const raw = await request<Record<string, unknown>>("/screen", {
      method: "POST",
      body: JSON.stringify({
        board: params.get("board"),
        operator: params.get("operator"),
        market_cap_yi: Number(params.get("market_cap_yi")),
        exclude_st: params.get("exclude_st") === "true",
        top_k: Number(params.get("top_k")),
        save_history: true,
      }),
    });
    const categories = (raw.categories || {}) as Record<string, unknown[]>;
    const rawCounts = (raw.counts || {}) as Record<string, unknown>;
    const byCategory = (rawCounts.by_category || {}) as Record<string, unknown>;
    const asOf = (raw.as_of || {}) as Record<string, string>;
    return {
      items: ((raw.results || []) as Array<Record<string, unknown>>).map(mapStock),
      counts: {
        breakout: numeric(byCategory.breakout) || categories.breakout?.length || 0,
        pullback: numeric(byCategory.pullback) || categories.pullback?.length || 0,
        range_rebound: numeric(byCategory.range_bounce) || categories.range_bounce?.length || 0,
      },
      total: numeric(rawCounts.board_pool),
      filtered: numeric(rawCounts.eligible),
      as_of: { ...asOf, screen: [asOf.daily, asOf.valuation, asOf.st].filter(Boolean).sort()[0] || asOf.daily },
      elapsed_ms: numeric(raw.elapsed_ms),
      run_id: String(raw.history_run_id || ""),
    };
  },
  stateSummary: async () => mapState(await request<Record<string, unknown>>("/state")),
  updateState: async (code: string, state: "viewed" | "saved" | "pending" | "watchlist", enabled = true) => {
    const action = state === "saved" ? (enabled ? "save" : "unsave") : state === "pending" ? (enabled ? "pending" : "unpending") : state === "watchlist" ? (enabled ? "watch" : "unwatch") : "viewed";
    await request<Record<string, unknown>>("/state", { method: "POST", body: JSON.stringify({ code, action }) });
    return mapState(await request<Record<string, unknown>>("/state"));
  },
};

export function fmtNumber(value?: number, digits = 2) {
  return Number(value || 0).toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtMarketValue(value?: number) {
  if (!value) return "—";
  const yi = value / 10000;
  return yi >= 10000 ? `${(yi / 10000).toFixed(2)}万亿` : `${yi.toFixed(0)}亿`;
}

export function fmtAmount(value?: number) {
  if (!value) return "—";
  const yi = value / 100000;
  return yi >= 10000 ? `${(yi / 10000).toFixed(2)}万亿` : `${yi.toFixed(2)}亿`;
}
