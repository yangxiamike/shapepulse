import type {
  Bar,
  BarsResponse,
  DataDates,
  HistoryRecommendation,
  IndustryStrengthResponse,
  PatternKey,
  PatternPool,
  PatternResponse,
  SavedScreenSnapshot,
  SavedScreenPage,
  ScreenFilters,
  ScreenProgress,
  ScreenResponse,
  StateItem,
  StateSnapshot,
  Stock,
  TemplateDefinition,
  TemplateStock,
  TemplateStocksResponse,
} from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_MARKET_API || "http://127.0.0.1:8765/api";

type Raw = Record<string, unknown>;

const barsCache = new Map<string, BarsResponse>();
const barsRequests = new Map<string, Promise<BarsResponse>>();
const stockCache = new Map<string, Stock>();
const stockRequests = new Map<string, Promise<{ item: Stock; cacheHit: boolean; httpMs: number }>>();
const templateCache = new Map<string, TemplateDefinition>();
const templateRequests = new Map<string, Promise<TemplateDefinition>>();
const templateStocksCache = new Map<string, TemplateStocksResponse>();
const templateStocksRequests = new Map<string, Promise<TemplateStocksResponse>>();
let templatesCache: TemplateDefinition[] | null = null;
let templatesRequest: Promise<TemplateDefinition[]> | null = null;
const industryStrengthCache = new Map<string, IndustryStrengthResponse>();
const industryStrengthRequests = new Map<string, Promise<IndustryStrengthResponse>>();
const frozenTemplateDescriptions: Record<string, string> = {
  fresh_breakout: "价格刚离开原有整理区，随后仍能站稳，重点看突破后的承接。",
  healthy_uptrend: "价格沿较平缓的方向逐步抬高，回撤有限，整体节奏较稳定。",
  pullback_strengthening: "已有一段上涨，随后回调并重新转强，重点看回调后的恢复。",
  parabolic_uptrend: "上涨速度逐渐加快，曲线后段更陡，属于加速型走势。",
};

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
    matches: Array.isArray(raw.matches) ? raw.matches.map(item => {
      const match = item as Raw;
      return {
        category: patternKey(match.category),
        category_label: String(match.category_label || ""),
        score: numeric(match.score),
        reasons: Array.isArray(match.reasons) ? match.reasons.map(String) : [],
        metrics: (match.metrics || {}) as Record<string, number>,
        minimum_score: optionalNumeric(match.minimum_score),
      };
    }) : [],
    score: optionalNumeric(raw.score ?? raw.match_score),
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
    screen_token: raw.screen_token ? String(raw.screen_token) : undefined,
    top_k: numeric(raw.top_k),
    filters: (raw.filters || {}) as Partial<ScreenFilters>,
  };
}

function mapSavedSnapshot(raw: Raw): SavedScreenSnapshot {
  return {
    ...raw,
    run_id: String(raw.run_id || raw.history_run_id || ""),
    snapshot_date: String(raw.snapshot_date || ""),
    result_count: numeric(raw.result_count),
    filters: (raw.filters || {}) as Record<string, unknown>,
    category_counts: (raw.category_counts || {}) as SavedScreenSnapshot["category_counts"],
    warnings: Array.isArray(raw.warnings) ? raw.warnings.map(String) : [],
    created_at: String(raw.created_at || new Date().toISOString()),
    rule_version: raw.rule_version == null ? undefined : String(raw.rule_version),
    top_k: numeric(((raw.filters || {}) as Raw).top_k) || undefined,
    results: Array.isArray(raw.results) ? (raw.results as Raw[]).map(mapStock) : undefined,
  };
}

function numericArray(value: unknown) {
  return Array.isArray(value) ? value.map(item => {
    if (item && typeof item === "object") {
      const point = item as Raw;
      return numeric(point.value ?? point.close ?? point.z ?? point.y);
    }
    return numeric(item);
  }).filter(Number.isFinite) : [];
}

export function normalizeLogCloseWindow(values: number[]) {
  if (values.length < 2 || values.some(value => !Number.isFinite(value) || value <= 0)) return [];
  const logged = values.map(Math.log);
  const mean = logged.reduce((sum, value) => sum + value, 0) / logged.length;
  const variance = logged.reduce((sum, value) => sum + (value - mean) ** 2, 0) / logged.length;
  const deviation = Math.sqrt(variance);
  return deviation > 1e-12 ? logged.map(value => (value - mean) / deviation) : [];
}

function mapTemplate(raw: Raw): TemplateDefinition {
  const kindValue = String(raw.kind || raw.type || raw.template_type || raw.source || "").toLowerCase();
  const source = (raw.source || {}) as Raw;
  const bars = Array.isArray(raw.bars) ? raw.bars as Raw[] : [];
  const directCurve = raw.curve ?? raw.normalized_curve ?? raw.template_curve ?? raw.z_values ?? raw.values;
  const mappedCurve = numericArray(directCurve);
  const barsCurve = normalizeLogCloseWindow(bars.map(bar => numeric(bar.qfq_close ?? bar.close)));
  const curve = barsCurve.length ? barsCurve : mappedCurve;
  const id = String(raw.id || raw.template_id || raw.key || "");
  return {
    id,
    key: String(raw.key || id),
    name: String(raw.name || raw.label || raw.key || "未命名模板"),
    kind: kindValue === "custom" || Boolean(raw.is_custom) ? "custom" : "frozen",
    source_ts_code: raw.source_ts_code == null && source.ts_code == null
      ? null
      : String(raw.source_ts_code || source.ts_code),
    source_name: raw.source_name == null && source.name == null
      ? null
      : String(raw.source_name || source.name),
    start_date: raw.start_date == null && source.start_date == null
      ? null
      : String(raw.start_date || source.start_date),
    end_date: raw.end_date == null && source.end_date == null
      ? null
      : String(raw.end_date || source.end_date),
    window_length: numeric(raw.window_length || raw.window_bars || raw.length || curve.length),
    curve,
    bars: bars.map(bar => ({
      time: String(bar.time || bar.trade_date || ""),
      trade_date: String(bar.trade_date || bar.time || ""),
      open: numeric(bar.qfq_open ?? bar.open),
      high: numeric(bar.qfq_high ?? bar.high),
      low: numeric(bar.qfq_low ?? bar.low),
      close: numeric(bar.qfq_close ?? bar.close),
      volume: numeric(bar.volume ?? bar.vol),
    })),
    description: String(raw.description || raw.analysis || raw.explanation || frozenTemplateDescriptions[String(raw.key || id)] || ""),
    cue: raw.cue == null ? undefined : String(raw.cue),
    created_at: raw.created_at == null ? null : String(raw.created_at),
    updated_at: raw.updated_at == null ? null : String(raw.updated_at),
  };
}

function mapTemplateStock(raw: Raw, index: number): TemplateStock {
  const curve = raw.curve ?? raw.normalized_curve ?? raw.candidate_curve ?? raw.values;
  const bars = Array.isArray(raw.bars) ? raw.bars as Raw[] : [];
  return {
    rank: numeric(raw.rank) || index + 1,
    ts_code: String(raw.ts_code || raw.code || ""),
    code: symbolOf(raw.ts_code || raw.code),
    name: String(raw.name || raw.stock_name || raw.ts_code || "—"),
    industry: raw.industry == null && raw.industry_name == null
      ? undefined
      : String(raw.industry || raw.industry_name),
    score: numeric(raw.score ?? raw.similarity),
    start_date: raw.start_date == null && raw.window_start == null
      ? null
      : String(raw.start_date || raw.window_start),
    end_date: raw.end_date == null && raw.window_end == null
      ? null
      : String(raw.end_date || raw.window_end),
    window_length: numeric(raw.window_bars || raw.window_length) || undefined,
    curve: numericArray(curve),
    bars: bars.map(bar => ({
      time: String(bar.time || bar.trade_date || ""),
      trade_date: String(bar.trade_date || bar.time || ""),
      open: numeric(bar.qfq_open ?? bar.open),
      high: numeric(bar.qfq_high ?? bar.high),
      low: numeric(bar.qfq_low ?? bar.low),
      close: numeric(bar.qfq_close ?? bar.close),
      volume: numeric(bar.volume ?? bar.vol),
    })),
  };
}

function optionalQueryNumber(value?: string | null) {
  if (value == null || value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeScreenFilters(filters: ScreenFilters) {
  const boardMap: Record<string, string> = { mainboard: "主板", chinext: "创业板", star: "科创板" };
  return { ...filters, board: boardMap[filters.board] || filters.board };
}

const barRangeLimits: Record<string, Record<string, number>> = {
  "1D": { D: 1, W: 1, M: 1, Q: 1, Y: 1 },
  "5D": { D: 5, W: 2, M: 1, Q: 1, Y: 1 },
  "1M": { D: 22, W: 5, M: 1, Q: 1, Y: 1 },
  "3M": { D: 66, W: 14, M: 3, Q: 1, Y: 1 },
  "6M": { D: 110, W: 27, M: 6, Q: 2, Y: 1 },
  YTD: { D: 160, W: 32, M: 8, Q: 3, Y: 1 },
  "1Y": { D: 250, W: 53, M: 12, Q: 4, Y: 1 },
  "3Y": { D: 750, W: 160, M: 36, Q: 12, Y: 3 },
  "5Y": { D: 1250, W: 266, M: 60, Q: 20, Y: 5 },
  ALL: { D: 10000, W: 2500, M: 600, Q: 200, Y: 50 },
};

type BarsWireResponse = {
  bars: Bar[];
  period: string;
  as_of: DataDates;
  warnings: string[];
  timings: Record<string, number>;
  cache_hit: boolean;
  range?: Raw;
};

async function loadBars(
  code: string,
  period: string,
  requestLimit: number,
  cacheKey: string,
  query: URLSearchParams,
  force = false,
): Promise<BarsResponse> {
  if (!force && barsCache.has(cacheKey)) {
    return { ...barsCache.get(cacheKey)!, client_cache_hit: true, http_ms: 0 };
  }
  if (!force && barsRequests.has(cacheKey)) return barsRequests.get(cacheKey)!;
  const pending = request<BarsWireResponse>(`/bars/${encodeURIComponent(code)}?${query}`)
    .then(({ data, httpMs }) => {
      const historyRange = data.range || {};
      const response: BarsResponse = {
        items: withMovingAverages(data.bars || []),
        period: data.period,
        as_of: data.as_of || {},
        warnings: data.warnings || [],
        timings: data.timings || {},
        cache_hit: Boolean(data.cache_hit),
        client_cache_hit: false,
        http_ms: httpMs,
        has_more: Boolean(historyRange.has_more_before),
        history_start: historyRange.oldest_available ? String(historyRange.oldest_available) : null,
        history_end: historyRange.newest_available ? String(historyRange.newest_available) : null,
      };
      barsCache.set(cacheKey, response);
      while (barsCache.size > 48) barsCache.delete(barsCache.keys().next().value!);
      return response;
    })
    .finally(() => barsRequests.delete(cacheKey));
  void requestLimit;
  barsRequests.set(cacheKey, pending);
  return pending;
}

function previousCalendarDate(value: string): string {
  const digits = String(value || "").replaceAll("-", "");
  if (!/^\d{8}$/.test(digits)) throw new Error("历史分页日期无效");
  const date = new Date(Date.UTC(
    Number(digits.slice(0, 4)),
    Number(digits.slice(4, 6)) - 1,
    Number(digits.slice(6, 8)),
  ));
  date.setUTCDate(date.getUTCDate() - 1);
  return date.toISOString().slice(0, 10).replaceAll("-", "");
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
    if (!force && stockRequests.has(key)) return stockRequests.get(key)!;
    const pending = request<Raw>(`/stock/${encodeURIComponent(code)}`)
      .then(({ data, httpMs }) => {
        const item = mapStock(data);
        stockCache.set(key, item);
        return { item, cacheHit: false, httpMs };
      })
      .finally(() => stockRequests.delete(key));
    stockRequests.set(key, pending);
    return pending;
  },
  bars: async (code: string, period = "D", range = "6M", force = false): Promise<BarsResponse> => {
    const periodMap: Record<string, string> = { D: "1d", W: "1w", M: "1m", Q: "1q", Y: "1y" };
    const visible = barRangeLimits[range]?.[period] || barRangeLimits["6M"][period] || 110;
    // Keep a small warm-up tail so MA60 is valid without loading the full history.
    const requestLimit = range === "ALL" ? visible : Math.min(10000, visible + 60);
    const wirePeriod = periodMap[period] || period;
    const key = `${symbolOf(code)}:${wirePeriod}:qfq:latest:${requestLimit}`;
    const query = new URLSearchParams({ period: wirePeriod, adjust: "qfq", limit: String(requestLimit) });
    return loadBars(code, wirePeriod, requestLimit, key, query, force);
  },
  barsAll: async (code: string, force = false): Promise<BarsResponse> => {
    let page = await api.bars(code, "D", "ALL", force);
    const pages = [page];
    let cursor = page.items[0]?.trade_date || page.items[0]?.time || "";
    for (let pageIndex = 1; page.has_more && pageIndex < 32; pageIndex += 1) {
      if (!cursor) throw new Error("完整历史分页缺少起始日期");
      const end = previousCalendarDate(cursor);
      const cacheKey = `${symbolOf(code)}:1d:qfq:before:${end}:10000`;
      const query = new URLSearchParams({
        period: "1d",
        adjust: "qfq",
        end,
        limit: "10000",
      });
      const older = await loadBars(code, "1d", 10000, cacheKey, query, force);
      const nextCursor = older.items[0]?.trade_date || older.items[0]?.time || "";
      if (!older.items.length || !nextCursor || nextCursor >= cursor) {
        throw new Error("完整历史分页没有继续向前推进");
      }
      pages.unshift(older);
      page = older;
      cursor = nextCursor;
    }
    if (page.has_more) throw new Error("完整历史超过本地分页安全上限");
    const merged = new Map<string, Bar>();
    for (const chunk of pages) {
      for (const item of chunk.items) {
        merged.set(String(item.trade_date || item.time), item);
      }
    }
    const items = [...merged.values()].sort((a, b) =>
      String(a.trade_date || a.time).localeCompare(String(b.trade_date || b.time))
    );
    return {
      ...pages.at(-1)!,
      items: withMovingAverages(items),
      warnings: [...new Set(pages.flatMap(item => item.warnings))],
      timings: {
        total_ms: pages.reduce((sum, item) => sum + (item.timings.total_ms || 0), 0),
      },
      cache_hit: pages.every(item => item.cache_hit),
      client_cache_hit: pages.every(item => item.client_cache_hit),
      http_ms: pages.reduce((sum, item) => sum + (item.http_ms || 0), 0),
      has_more: false,
      history_start: items[0]?.trade_date || items[0]?.time || null,
      history_end: items.at(-1)?.trade_date || items.at(-1)?.time || null,
    };
  },
  barsWindow: async (
    code: string,
    startDate: string,
    endDate: string,
    limit = 240,
    force = false,
  ): Promise<BarsResponse> => {
    const start = String(startDate || "").replaceAll("-", "");
    const end = String(endDate || "").replaceAll("-", "");
    const safeLimit = Math.max(1, Math.min(10000, Math.floor(limit)));
    const key = `${symbolOf(code)}:1d:qfq:${start}:${end}:${safeLimit}`;
    const query = new URLSearchParams({
      period: "1d",
      adjust: "qfq",
      start,
      end,
      limit: String(safeLimit),
    });
    return loadBars(code, "1d", safeLimit, key, query, force);
  },
  screen: async (input: ScreenFilters | string, onProgress?: (progress: ScreenProgress) => void): Promise<ScreenResponse> => {
    const incoming = typeof input === "string" ? new URLSearchParams(input) : null;
    const boardMap: Record<string, string> = { mainboard: "主板", chinext: "创业板", star: "科创板" };
    const selectedBoard = incoming?.get("board") || (typeof input === "string" ? "mainboard" : input.board);
    const body = {
      board: boardMap[selectedBoard] || selectedBoard || "主板",
      industries: typeof input === "string" ? (incoming?.get("industries")?.split(",").filter(Boolean) || []) : input.industries,
      market_cap_min_yi: typeof input === "string" ? optionalQueryNumber(incoming?.get("market_cap_min_yi")) : input.market_cap_min_yi,
      market_cap_max_yi: typeof input === "string" ? optionalQueryNumber(incoming?.get("market_cap_max_yi")) : input.market_cap_max_yi,
      exclude_st: typeof input === "string" ? incoming?.get("exclude_st") !== "false" : input.exclude_st,
      top_k: typeof input === "string" ? Math.max(1, Number(incoming?.get("top_k") || 50)) : input.top_k,
      mode: typeof input === "string" ? "per_category" : input.mode,
      save_history: false,
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
  industries: async () => {
    const { data } = await request<Raw>("/industries");
    const names = Array.isArray(data.names) ? data.names.map(String) : Array.isArray(data.items) ? (data.items as Raw[]).map(item => String(item.name || "")).filter(Boolean) : [];
    return { items: names, as_of: data.as_of ? String(data.as_of) : null };
  },
  industryStrength: async (
    pattern: PatternKey,
    endDate?: string | null,
    force = false,
  ): Promise<IndustryStrengthResponse> => {
    const query = new URLSearchParams({ pattern });
    if (endDate) query.set("end_date", endDate.replace(/-/g, ""));
    const key = query.toString();
    if (!force && industryStrengthCache.has(key)) {
      return { ...industryStrengthCache.get(key)!, client_cache_hit: true, http_ms: 0 };
    }
    if (!force && industryStrengthRequests.has(key)) {
      return industryStrengthRequests.get(key)!;
    }
    const pending = request<IndustryStrengthResponse>(`/industry-strength?${query}`)
      .then(({ data, httpMs }) => {
        const result = { ...data, client_cache_hit: false, http_ms: httpMs };
        industryStrengthCache.set(key, result);
        while (industryStrengthCache.size > 8) {
          industryStrengthCache.delete(industryStrengthCache.keys().next().value!);
        }
        return result;
      })
      .finally(() => industryStrengthRequests.delete(key));
    industryStrengthRequests.set(key, pending);
    return pending;
  },
  saveScreenSnapshot: async (screen: ScreenResponse, filters: ScreenFilters) => {
    const body = screen.screen_token ? { screen_token: screen.screen_token } : { filters: normalizeScreenFilters(filters) };
    const { data } = await request<Raw>("/screen/snapshots", { method: "POST", body: JSON.stringify(body) });
    const runId = String(data.history_run_id || data.run_id || "");
    if (!runId) throw new Error("本次筛选快照未返回记录编号");
    return mapSavedSnapshot((await request<Raw>(`/screen/snapshots/${encodeURIComponent(runId)}`)).data);
  },
  screenSnapshot: async (runId: string) => mapSavedSnapshot((await request<Raw>(`/screen/snapshots/${encodeURIComponent(runId)}`)).data),
  screenSnapshots: async (page = 1, pageSize = 20): Promise<SavedScreenPage> => {
    const { data } = await request<Raw>(`/screen/snapshots?page=${Math.max(1, Math.floor(page))}&page_size=${Math.max(1, Math.floor(pageSize))}`);
    return { items: Array.isArray(data.items) ? (data.items as Raw[]).map(mapSavedSnapshot) : [], page: numeric(data.page) || 1, page_size: numeric(data.page_size) || pageSize, total: numeric(data.total) };
  },
  patternPool: async (category: PatternKey, limit = 200): Promise<PatternPool> => {
    const { data } = await request<Raw>(`/pattern/pool?category=${encodeURIComponent(category)}&limit=${Math.max(1, Math.floor(limit))}`);
    return { category, category_label: String(data.category_label || category), items: Array.isArray(data.items) ? (data.items as Raw[]).map(mapStock) : [], snapshot_id: data.snapshot_id ? String(data.snapshot_id) : null };
  },
  state: async () => mapState((await request<Raw>("/state")).data),
  updateState: async (code: string, state: "viewed" | "saved" | "pending" | "watchlist", enabled = true) => {
    const action = state === "saved" ? (enabled ? "save" : "unsave") : state === "pending" ? (enabled ? "pending" : "unpending") : state === "watchlist" ? (enabled ? "watch" : "unwatch") : "viewed";
    await request<Raw>("/state", { method: "POST", body: JSON.stringify({ code, action }) });
    if (state !== "viewed") stockCache.delete(symbolOf(code));
    return mapState((await request<Raw>("/state")).data);
  },
  pattern: async (code: string) => (await request<PatternResponse>(`/pattern/${encodeURIComponent(code)}?history_limit=12`)).data,
  templates: async (force = false): Promise<TemplateDefinition[]> => {
    if (!force && templatesCache) return templatesCache.map(item => ({ ...item }));
    if (!force && templatesRequest) return templatesRequest;
    const pending = request<Raw>("/templates")
      .then(({ data }) => {
        const items = Array.isArray(data.items) ? (data.items as Raw[]).map(mapTemplate) : [];
        templatesCache = items;
        for (const item of items) {
          const existing = templateCache.get(item.id);
          templateCache.set(item.id, existing?.bars.length ? { ...item, bars: existing.bars, curve: existing.curve } : item);
        }
        return items.map(item => ({ ...item }));
      })
      .finally(() => { templatesRequest = null; });
    templatesRequest = pending;
    return pending;
  },
  template: async (id: string, force = false): Promise<TemplateDefinition> => {
    if (!force && templateCache.get(id)?.bars.length) return { ...templateCache.get(id)! };
    if (!force && templateRequests.has(id)) return templateRequests.get(id)!;
    const pending = request<Raw>(`/templates/${encodeURIComponent(id)}`)
      .then(({ data }) => {
        const item = mapTemplate((data.template || data.item || data) as Raw);
        templateCache.set(id, item);
        return { ...item };
      })
      .finally(() => templateRequests.delete(id));
    templateRequests.set(id, pending);
    return pending;
  },
  templateStocks: async (id: string, limit = 100, force = false): Promise<TemplateStocksResponse> => {
    const safeLimit = Math.max(1, Math.min(100, Math.floor(limit)));
    const key = `${id}:${safeLimit}:metadata`;
    if (!force && templateStocksCache.has(key)) return templateStocksCache.get(key)!;
    if (!force && templateStocksRequests.has(key)) return templateStocksRequests.get(key)!;
    const pending = request<Raw>(`/templates/${encodeURIComponent(id)}/stocks?limit=${safeLimit}&include_bars=0`)
      .then(({ data }) => {
        const rawTemplate = (data.template || {}) as Raw;
        const items = Array.isArray(data.items)
          ? (data.items as Raw[]).map(mapTemplateStock)
          : [];
        const result = {
          template: mapTemplate(rawTemplate),
          items,
          total: numeric(data.total ?? data.total_eligible) || items.length,
        };
        templateStocksCache.set(key, result);
        return result;
      })
      .finally(() => templateStocksRequests.delete(key));
    templateStocksRequests.set(key, pending);
    return pending;
  },
  createTemplate: async (input: { name: string; source_ts_code: string; start_date: string; end_date: string }): Promise<TemplateDefinition> => {
    const { data } = await request<Raw>("/templates", { method: "POST", body: JSON.stringify(input) });
    return mapTemplate((data.template || data.item || data) as Raw);
  },
  renameTemplate: async (id: string, name: string): Promise<TemplateDefinition> => {
    const { data } = await request<Raw>(`/templates/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ name }) });
    const mapped = mapTemplate((data.template || data.item || data) as Raw);
    const previous = templateCache.get(id);
    const item = !mapped.bars.length && previous?.bars.length
      ? { ...mapped, bars: previous.bars, curve: previous.curve }
      : mapped;
    templateCache.set(id, item);
    templatesCache = templatesCache?.map(template => template.id === id ? { ...template, name: item.name } : template) || null;
    return item;
  },
  deleteTemplate: async (id: string): Promise<void> => {
    await request<Raw>(`/templates/${encodeURIComponent(id)}`, { method: "DELETE" });
    templateCache.delete(id);
    templatesCache = templatesCache?.filter(item => item.id !== id) || null;
    for (const key of [...templateStocksCache.keys()]) if (key.startsWith(`${id}:`)) templateStocksCache.delete(key);
  },
  clearCaches: () => {
    barsCache.clear();
    barsRequests.clear();
    stockCache.clear();
    stockRequests.clear();
    templateCache.clear();
    templateRequests.clear();
    templateStocksCache.clear();
    templateStocksRequests.clear();
    templatesCache = null;
    templatesRequest = null;
  },
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
