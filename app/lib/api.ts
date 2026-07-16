import type {
  Bar,
  BarsResponse,
  DataDates,
  HistoryRecommendation,
  PatternKey,
  PatternResponse,
  ScreenProgress,
  ScreenResponse,
  StateItem,
  StateSnapshot,
  Stock,
} from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_MARKET_API || "http://127.0.0.1:8765/api";

type Raw = Record<string, unknown>;

const barsCache = new Map<string, BarsResponse>();
const stockCache = new Map<string, Stock>();

async function request<T>(path: string, init?: RequestInit): Promise<{ data: T; httpMs: number }> {
  const started = performance.now();
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const httpMs = performance.now() - started;
  if (!response.ok) {
    const body = await response.text();
    let message = body;
    try {
      const parsed = JSON.parse(body) as Raw;
      message = String(parsed.message || parsed.error || body);
    } catch { /* keep plain response */ }
    throw new Error(message || `本地数据服务返回 ${response.status}`);
  }
  return { data: await response.json() as T, httpMs };
}

function numeric(value: unknown) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function optionalNumeric(value: unknown) {
  const n = Number(value);
  return value == null || value === "" || !Number.isFinite(n) ? undefined : n;
}

function symbolOf(value: unknown) {
  return String(value || "").split(".")[0].padStart(6, "0");
}

function patternKey(value: unknown): PatternKey {
  const raw = String(value || "breakout");
  return raw === "range_rebound" ? "range_bounce" : raw as PatternKey;
}

function mapStock(raw: Raw): Stock {
  const quote = (raw.quote || {}) as Raw;
  const valuation = (raw.valuation || {}) as Raw;
  const industry = (raw.industry || {}) as Raw;
  const state = (raw.state || {}) as Raw;
  const code = symbolOf(raw.symbol || raw.code || raw.ts_code);
  return {
    code,
    ts_code: String(raw.ts_code || raw.code || ""),
    name: String(raw.name || "—"),
    initials: String(raw.initials || raw.pinyin || raw.cnspell || ""),
    market: String(raw.market || ""),
    exchange: String(raw.exchange || ""),
    industry: String(industry.name || raw.industry_name || ""),
    close: numeric(raw.close ?? quote.close ?? valuation.close),
    pre_close: optionalNumeric(raw.pre_close ?? quote.pre_close),
    pct_chg: numeric(raw.pct_chg ?? quote.pct_chg),
    change: optionalNumeric(raw.change ?? quote.change),
    open: optionalNumeric(raw.open ?? quote.open),
    high: optionalNumeric(raw.high ?? quote.high),
    low: optionalNumeric(raw.low ?? quote.low),
    volume: optionalNumeric(raw.volume ?? raw.vol ?? quote.vol),
    amount: optionalNumeric(raw.amount ?? quote.amount),
    turnover_rate: optionalNumeric(raw.turnover_rate ?? valuation.turnover_rate),
    total_mv: optionalNumeric(raw.total_mv ?? valuation.total_mv ?? (numeric(raw.total_mv_yi) * 10000)),
    circ_mv: optionalNumeric(raw.circ_mv ?? valuation.circ_mv ?? (numeric(raw.circ_mv_yi) * 10000)),
    pe_ttm: optionalNumeric(raw.pe_ttm ?? valuation.pe_ttm),
    pb: optionalNumeric(raw.pb ?? valuation.pb),
    is_st: Boolean(raw.is_st),
    pattern: raw.category ? patternKey(raw.category) : undefined,
    pattern_name: raw.category_label ? String(raw.category_label) : undefined,
    score: optionalNumeric(raw.score),
    reasons: Array.isArray(raw.reasons) ? raw.reasons.map(String) : [],
    metrics: (raw.metrics || {}) as Record<string, number>,
    rank: optionalNumeric(raw.rank),
    category_rank: optionalNumeric(raw.category_rank),
    sparkline: Array.isArray(raw.sparkline) ? raw.sparkline.map(numeric) : [],
    as_of: (raw.as_of || {}) as DataDates,
    warnings: Array.isArray(raw.warnings) ? raw.warnings.map(String) : [],
    state: {
      viewed: Boolean(state.viewed),
      saved: Boolean(state.saved),
      pending: Boolean(state.pending),
      watchlist: Boolean(state.watchlist),
    },
  };
}

function withMovingAverages(items: Bar[]) {
  const periods = [5, 10, 20, 60] as const;
  const sums = new Map<number, number>();
  return items.map((bar, index) => {
    const enriched: Bar = { ...bar };
    for (const p of periods) {
      const next = (sums.get(p) || 0) + bar.close - (index >= p ? items[index - p].close : 0);
      sums.set(p, next);
      if (index + 1 >= p) enriched[`ma${p}` as "ma5"] = Number((next / p).toFixed(3));
    }
    return enriched;
  });
}

function mapStateItem(raw: Raw): StateItem {
  return {
    ...raw,
    ts_code: String(raw.ts_code || ""),
    code: symbolOf(raw.symbol || raw.ts_code),
    name: raw.name ? String(raw.name) : undefined,
    viewed: Boolean(raw.viewed),
    saved: Boolean(raw.saved),
    pending: Boolean(raw.pending),
    watchlist: Boolean(raw.watchlist),
  } as StateItem;
}

function mapState(raw: Raw): StateSnapshot {
  const history = (raw.history || {}) as Raw;
  return {
    viewed: ((raw.viewed || []) as Raw[]).map(mapStateItem),
    saved: ((raw.saved || []) as Raw[]).map(mapStateItem),
    pending: ((raw.pending || []) as Raw[]).map(mapStateItem),
    watchlist: ((raw.watchlist || []) as Raw[]).map(mapStateItem),
    history: {
      runs: (history.runs || []) as StateSnapshot["history"]["runs"],
      recommendations: ((history.recommendations || []) as Raw[]).map(item => ({
        ...item,
        code: symbolOf(item.ts_code),
        category: patternKey(item.category),
      })) as HistoryRecommendation[],
    },
  };
}

function mapScreen(raw: Raw): ScreenResponse {
  const categories = (raw.categories || {}) as Record<string, Raw[]>;
  const rawCounts = (raw.counts || {}) as Raw;
  const byCategory = (rawCounts.by_category || {}) as Raw;
  const deltas = (raw.category_deltas || {}) as Raw;
  return {
    items: ((raw.results || []) as Raw[]).map(mapStock),
    categories: {
      breakout: (categories.breakout || []).map(mapStock),
      pullback: (categories.pullback || []).map(mapStock),
      range_bounce: (categories.range_bounce || []).map(mapStock),
    },
    counts: {
      breakout: numeric(byCategory.breakout),
      pullback: numeric(byCategory.pullback),
      range_bounce: numeric(byCategory.range_bounce),
    },
    category_deltas: {
      breakout: deltas.breakout == null ? null : numeric(deltas.breakout),
      pullback: deltas.pullback == null ? null : numeric(deltas.pullback),
      range_bounce: deltas.range_bounce == null ? null : numeric(deltas.range_bounce),
    },
    comparison_as_of: raw.comparison_as_of ? String(raw.comparison_as_of) : null,
    total: numeric(rawCounts.board_pool),
    filtered: numeric(rawCounts.eligible),
    scored: numeric(rawCounts.scored),
    as_of: (raw.as_of || {}) as DataDates,
    warnings: Array.isArray(raw.warnings) ? raw.warnings.map(String) : [],
    timings: (raw.timings || {}) as Record<string, number>,
    cache_hit: Boolean(raw.cache_hit),
    elapsed_ms: numeric(raw.elapsed_ms),
    run_id: raw.history_run_id ? String(raw.history_run_id) : undefined,
  };
}

export const api = {
  health: async () => {
    const { data, httpMs } = await request<Raw>("/health");
    return { status: data.ok ? "ok" : "error", as_of: (data.snapshots || {}) as DataDates, httpMs };
  },
  search: async (query: string) => {
    const { data, httpMs } = await request<{ results: Raw[] }>(`/search?q=${encodeURIComponent(query)}`);
    return { items: (data.results || []).map(mapStock), httpMs };
  },
  stock: async (code: string, force = false) => {
    const key = symbolOf(code);
    if (!force && stockCache.has(key)) return { item: stockCache.get(key)!, cacheHit: true, httpMs: 0 };
    const { data, httpMs } = await request<Raw>(`/stock/${encodeURIComponent(code)}`);
    const item = mapStock(data);
    stockCache.set(key, item);
    return { item, cacheHit: false, httpMs };
  },
  bars: async (code: string, period = "D", range = "6M", force = false): Promise<BarsResponse> => {
    const key = `${symbolOf(code)}:${period}:${range}:qfq`;
    if (!force && barsCache.has(key)) {
      return { ...barsCache.get(key)!, client_cache_hit: true, http_ms: 0 };
    }
    const periodMap: Record<string, string> = { D: "1d", W: "1w", M: "1m", Q: "1q", Y: "1y" };
    const rangeLimits: Record<string, Record<string, number>> = {
      "1D": { D: 1, W: 1, M: 1, Q: 1, Y: 1 },
      "5D": { D: 5, W: 2, M: 1, Q: 1, Y: 1 },
      "1M": { D: 22, W: 5, M: 1, Q: 1, Y: 1 },
      "3M": { D: 66, W: 14, M: 3, Q: 1, Y: 1 },
      "6M": { D: 110, W: 27, M: 6, Q: 2, Y: 1 },
      YTD: { D: 160, W: 32, M: 8, Q: 3, Y: 1 },
      "1Y": { D: 250, W: 53, M: 12, Q: 4, Y: 1 },
      "3Y": { D: 750, W: 160, M: 36, Q: 12, Y: 3 },
      "5Y": { D: 1250, W: 266, M: 60, Q: 20, Y: 5 },
      ALL: { D: 5000, W: 1200, M: 240, Q: 80, Y: 20 },
    };
    const limit = rangeLimits[range]?.[period] || 110;
    const years = range === "ALL" ? 20 : Math.max(1, Math.ceil(limit / ({ D: 240, W: 52, M: 12, Q: 4, Y: 1 }[period] || 240)));
    const start = `${new Date().getFullYear() - years}0101`;
    const { data, httpMs } = await request<{ bars: Bar[]; period: string; as_of: DataDates; warnings: string[]; timings: Record<string, number>; cache_hit: boolean }>(
      `/bars/${encodeURIComponent(code)}?period=${periodMap[period] || period}&start=${start}&limit=${limit}`,
    );
    const response: BarsResponse = {
      items: withMovingAverages(data.bars || []),
      period: data.period,
      as_of: data.as_of || {},
      warnings: data.warnings || [],
      timings: data.timings || {},
      cache_hit: Boolean(data.cache_hit),
      client_cache_hit: false,
      http_ms: httpMs,
    };
    barsCache.set(key, response);
    return response;
  },
  screen: async (query: string, onProgress?: (progress: ScreenProgress) => void): Promise<ScreenResponse> => {
    const incoming = new URLSearchParams(query);
    const boardMap: Record<string, string> = { mainboard: "主板", chinext: "创业板", star: "科创板" };
    const body = {
      board: boardMap[incoming.get("board") || "mainboard"] || "主板",
      operator: incoming.get("mv_operator") || "gte",
      market_cap_yi: Number(incoming.get("mv_value") || "50"),
      exclude_st: incoming.get("exclude_st") !== "false",
      top_k: 50,
      mode: "per_category",
      save_history: true,
    };
    const { data: started } = await request<Raw>("/screen/start", { method: "POST", body: JSON.stringify(body) });
    const jobId = String(started.job_id || "");
    if (!jobId) throw new Error("筛选任务未能启动");
    while (true) {
      const { data: job } = await request<Raw>(`/screen/jobs/${encodeURIComponent(jobId)}`);
      onProgress?.({
        stage: String(job.stage || "正在筛选"),
        completed: numeric(job.completed),
        total: Math.max(1, numeric(job.total)),
      });
      if (job.status === "complete") return mapScreen((job.result || {}) as Raw);
      if (job.status === "error") {
        const error = (job.error || {}) as Raw;
        throw new Error(String(error.message || "筛选失败"));
      }
      await new Promise(resolve => window.setTimeout(resolve, 80));
    }
  },
  state: async () => mapState((await request<Raw>("/state")).data),
  updateState: async (code: string, state: "viewed" | "saved" | "pending" | "watchlist", enabled = true) => {
    const action = state === "saved" ? (enabled ? "save" : "unsave") : state === "pending" ? (enabled ? "pending" : "unpending") : state === "watchlist" ? (enabled ? "watch" : "unwatch") : "viewed";
    await request<Raw>("/state", { method: "POST", body: JSON.stringify({ code, action }) });
    if (state !== "viewed") stockCache.delete(symbolOf(code));
    return mapState((await request<Raw>("/state")).data);
  },
  pattern: async (code: string) => (await request<PatternResponse>(`/pattern/${encodeURIComponent(code)}?history_limit=12`)).data,
  clearCaches: () => { barsCache.clear(); stockCache.clear(); },
};

export function fmtNumber(value?: number | null, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtMarketValue(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return "—";
  const yi = value / 10000;
  return yi >= 10000 ? `${(yi / 10000).toFixed(2)}万亿` : `${yi.toFixed(0)}亿`;
}

export function fmtAmount(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return "—";
  const yi = value / 100000;
  return yi >= 10000 ? `${(yi / 10000).toFixed(2)}万亿` : `${yi.toFixed(2)}亿`;
}

export function formatDate(value?: string | null, separator = ".") {
  if (!value) return "—";
  const raw = value.replace(/-/g, "");
  return raw.replace(/^(\d{4})(\d{2})(\d{2})$/, `$1${separator}$2${separator}$3`);
}

export function metricLabel(key: string) {
  const labels: Record<string, string> = {
    return_20: "20日涨幅", breakout: "平台突破", volume_ratio: "量比",
    ma20_extension: "距MA20", trend_fit_20: "20日拟合",
    return_60: "60日涨幅", drawdown_from_peak: "距高点回撤",
    ma_support_distance: "均线距离", retracement_ratio: "回撤比例",
    consolidation_volatility: "收敛波动", trend_fit_60: "60日拟合",
    range_position: "区间位置", range_width: "区间宽度", bounce_5: "5日反弹",
    return_80: "80日涨幅", support_touches: "支撑触碰", sideways_fit: "横盘拟合",
    linear_fit_80: "80日线性拟合",
  };
  return labels[key] || key;
}

export function fmtMetric(key: string, value: number) {
  if (key.includes("touches")) return String(Math.round(value));
  if (key === "volume_ratio") return `${value.toFixed(2)}×`;
  return `${(value * 100).toFixed(1)}%`;
}
