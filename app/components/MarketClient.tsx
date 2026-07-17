"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  Bell,
  Brush,
  CalendarDays,
  Camera,
  ChevronDown,
  CircleDot,
  Clock3,
  Crosshair,
  Fullscreen,
  Grid2X2,
  Layers3,
  LineChart,
  Menu,
  Minus,
  MousePointer2,
  MoveHorizontal,
  MoveVertical,
  PanelRightOpen,
  Palette,
  PenLine,
  Plus,
  RotateCcw,
  Ruler,
  Search,
  Settings2,
  Spline,
  Trash2,
  Type,
  X,
  ZoomIn,
} from "lucide-react";
import { AppSidebar } from "./AppSidebar";
import { MarketChart, type ChartDrawing, type DrawingMode, type MarketChartHandle } from "./MarketChart";
import { api, fmtAmount, fmtMarketValue, fmtMetric, fmtNumber, formatDate, metricLabel } from "../lib/api";
import type { Bar, PatternKey, PatternResponse, StateSnapshot, Stock } from "../lib/types";

const periods = [
  ["日K", "D"], ["周K", "W"], ["月K", "M"], ["季K", "Q"], ["年K", "Y"],
] as const;
const unavailablePeriods = ["分时", "5分", "15分", "30分", "60分"];
const ranges = [["1天", "1D"], ["5天", "5D"], ["1个月", "1M"], ["3个月", "3M"], ["6个月", "6M"], ["YTD", "YTD"], ["1年", "1Y"], ["3年", "3Y"], ["5年", "5Y"], ["全部", "ALL"]] as const;
const tabs = ["自选", "详情", "形态", "指标", "因子"] as const;
type RightTab = typeof tabs[number];

const patternNames: Record<PatternKey, string> = { breakout: "突破启动", pullback: "上升趋势回调", range_bounce: "区间下沿反弹" };
const emptyState: StateSnapshot = { viewed: [], saved: [], pending: [], watchlist: [], history: { runs: [], recommendations: [] } };
const rangeLimits: Record<string, Record<string, number>> = {
  "1D": { D: 1, W: 1, M: 1, Q: 1, Y: 1 }, "5D": { D: 5, W: 2, M: 1, Q: 1, Y: 1 },
  "1M": { D: 22, W: 5, M: 1, Q: 1, Y: 1 }, "3M": { D: 66, W: 14, M: 3, Q: 1, Y: 1 },
  "6M": { D: 110, W: 27, M: 6, Q: 2, Y: 1 }, YTD: { D: 160, W: 32, M: 8, Q: 3, Y: 1 },
  "1Y": { D: 250, W: 53, M: 12, Q: 4, Y: 1 }, "3Y": { D: 750, W: 160, M: 36, Q: 12, Y: 3 },
  "5Y": { D: 1250, W: 266, M: 60, Q: 20, Y: 5 }, ALL: { D: 10000, W: 2500, M: 600, Q: 200, Y: 50 },
};

export function MarketClient() {
  const [stock, setStock] = useState<Stock | null>(null);
  const [bars, setBars] = useState<Bar[]>([]);
  const [period, setPeriod] = useState("D");
  const [range, setRange] = useState("6M");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Stock[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [activeResult, setActiveResult] = useState(0);
  const [rightTab, setRightTab] = useState<RightTab>("自选");
  const [rightOpen, setRightOpen] = useState(false);
  const [state, setState] = useState<StateSnapshot>(emptyState);
  const [watchlist, setWatchlist] = useState<Stock[]>([]);
  const [pattern, setPattern] = useState<PatternResponse | null>(null);
  const [patternLoading, setPatternLoading] = useState(false);
  const [patternError, setPatternError] = useState("");
  const [drawingMode, setDrawingMode] = useState<DrawingMode | null>(null);
  const [drawings, setDrawings] = useState<ChartDrawing[]>([]);
  const [selectedDrawing, setSelectedDrawing] = useState<number | null>(null);
  const [drawingColor, setDrawingColor] = useState("#2864ff");
  const [drawingLineWidth, setDrawingLineWidth] = useState(2);
  const [drawingText, setDrawingText] = useState("文本标记");
  const [layout, setLayout] = useState<1 | 2 | 4>(1);
  const [layoutOpen, setLayoutOpen] = useState(false);
  const [maximizedPane, setMaximizedPane] = useState<number | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [patternCategory, setPatternCategory] = useState<PatternKey>("breakout");
  const [patternPool, setPatternPool] = useState<Stock[]>([]);
  const [poolLoading, setPoolLoading] = useState(false);
  const [crosshairEnabled, setCrosshairEnabled] = useState(true);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [rightWidth, setRightWidth] = useState(360);
  const [patternPendingCode, setPatternPendingCode] = useState<string | null>(null);
  const [status, setStatus] = useState("连接本地数据…");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [clock, setClock] = useState("—");
  const [perf, setPerf] = useState({ frontendMs: 0, httpMs: 0, queryMs: 0, renderMs: 0, cache: false });
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const operationStarted = useRef(0);
  const loadSequence = useRef(0);
  const barsLoadSequence = useRef(0);
  const shellRef = useRef<HTMLDivElement>(null);
  const workspaceRef = useRef<HTMLElement>(null);
  const chartRefs = useRef<Array<MarketChartHandle | null>>([]);
  const patternCursorRef = useRef(-1);
  const patternCategoryRef = useRef<PatternKey>("breakout");
  const rightResizeActive = useRef(false);
  const rightResizeFrame = useRef<number | null>(null);

  const refreshWatchlist = useCallback(async (snapshot: StateSnapshot) => {
    const items = await Promise.all(snapshot.watchlist.map(item => api.stock(item.code).then(result => result.item).catch(() => ({ code: item.code, ts_code: item.ts_code, name: item.name || item.code, close: 0, pct_chg: 0 } as Stock))));
    setWatchlist(items);
  }, []);

  const loadPattern = useCallback(async (code: string) => {
    setPatternLoading(true); setPatternError("");
    try { setPattern(await api.pattern(code)); }
    catch (e) { setPatternError(e instanceof Error ? e.message : "形态事实加载失败"); setPattern(null); }
    finally { setPatternLoading(false); }
  }, []);

  const loadPatternPool = useCallback(async (category: PatternKey) => {
    setPoolLoading(true);
    try {
      const pool = await api.patternPool(category, 500);
      setPatternPool(pool.items);
    } catch (e) { setPatternError(e instanceof Error ? e.message : "形态股票池加载失败"); setPatternPool([]); }
    finally { setPoolLoading(false); }
  }, []);

  const loadStock = useCallback(async (code: string, nextPeriod = "D", nextRange = "6M", preserveContext = false) => {
    const sequence = ++loadSequence.current;
    ++barsLoadSequence.current;
    const started = performance.now();
    operationStarted.current = started;
    setLoading(true); setError(""); setStatus("正在读取本地行情…");
    try {
      const [detailResult, history] = await Promise.all([api.stock(code), api.bars(code, nextPeriod, nextRange)]);
      if (sequence !== loadSequence.current) return;
      const detail = detailResult.item;
      setStock(detail); setBars(history.items); setPeriod(nextPeriod); setRange(nextRange);
      setPatternPendingCode(null);
      setPerf(current => ({ ...current, frontendMs: performance.now() - started, httpMs: detailResult.httpMs + (history.http_ms || 0), queryMs: history.timings.total_ms || 0, cache: detailResult.cacheHit && Boolean(history.client_cache_hit) }));
      setStatus(`${history.client_cache_hit ? "前端缓存" : history.cache_hit ? "后端缓存" : "本地快照"} · ${formatDate(history.as_of.daily)} · ${history.items.length} 根`);
      setSearchOpen(false); setQuery(""); if (!preserveContext) setRightOpen(false);
      window.history.replaceState(null, "", `/market?code=${detail.code}&category=${patternCategoryRef.current}`);
      void api.updateState(detail.code, "viewed").catch(() => undefined);
      void loadPattern(detail.code);
    } catch (e) {
      const message = e instanceof Error ? e.message : "本地行情加载失败";
      setError(message); setStatus(message);
      if (sequence === loadSequence.current) setPatternPendingCode(null);
    } finally { if (sequence === loadSequence.current) setLoading(false); }
  }, [loadPattern]);

  const choosePatternStock = useCallback((code: string) => {
    const index = patternPool.findIndex(item => item.code === code);
    if (index >= 0) patternCursorRef.current = index;
    setPatternPendingCode(code);
    void loadStock(code, period, range, true);
  }, [loadStock, patternPool, period, range]);

  const stepPatternStock = useCallback((direction: -1 | 1) => {
    if (!patternPool.length) return false;
    let index = patternCursorRef.current;
    if (index < 0 || index >= patternPool.length) {
      index = patternPool.findIndex(item => item.code === (patternPendingCode || stock?.code));
    }
    if (index < 0) index = direction > 0 ? -1 : patternPool.length;
    const nextIndex = Math.max(0, Math.min(patternPool.length - 1, index + direction));
    if (nextIndex === index) return false;
    patternCursorRef.current = nextIndex;
    const code = patternPool[nextIndex].code;
    setPatternPendingCode(code);
    void loadStock(code, period, range, true);
    return true;
  }, [loadStock, patternPendingCode, patternPool, period, range, stock?.code]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code") || "000001";
    const requestedCategory = params.get("category") as PatternKey | null;
    const updateClock = () => setClock(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
    const boot = window.setTimeout(() => {
      if (requestedCategory && requestedCategory in patternNames) {
        patternCategoryRef.current = requestedCategory;
        setPatternCategory(requestedCategory);
        void loadPatternPool(requestedCategory);
      }
      void loadStock(code);
      void api.state().then(snapshot => { setState(snapshot); void refreshWatchlist(snapshot); }).catch(() => undefined);
      updateClock();
    }, 0);
    const timer = window.setInterval(updateClock, 1000);
    return () => { window.clearTimeout(boot); window.clearInterval(timer); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const timer = window.setTimeout(() => { if (rightTab === "形态") void loadPatternPool(patternCategory); }, 0);
    return () => window.clearTimeout(timer);
  }, [loadPatternPool, patternCategory, rightTab]);

  useEffect(() => {
    const index = patternPool.findIndex(item => item.code === (patternPendingCode || stock?.code));
    if (index >= 0) patternCursorRef.current = index;
  }, [patternPendingCode, patternPool, stock?.code]);

  useEffect(() => {
    const onFullscreen = () => {
      setFullscreen(document.fullscreenElement === workspaceRef.current);
      window.setTimeout(() => chartRefs.current.forEach(chart => chart?.resize()), 40);
    };
    document.addEventListener("fullscreenchange", onFullscreen);
    return () => document.removeEventListener("fullscreenchange", onFullscreen);
  }, []);

  useEffect(() => () => {
    if (rightResizeFrame.current != null) cancelAnimationFrame(rightResizeFrame.current);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (rightTab !== "形态" || (event.key !== "ArrowUp" && event.key !== "ArrowDown")) return;
      const target = event.target as HTMLElement | null;
      if (target?.matches("input, select, textarea, [contenteditable=true]")) return;
      if (stepPatternStock(event.key === "ArrowDown" ? 1 : -1)) event.preventDefault();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [rightTab, stepPatternStock]);

  const changeBars = useCallback(async (nextPeriod: string, nextRange = range) => {
    if (!stock || (nextPeriod === period && nextRange === range)) return;
    const sequence = ++barsLoadSequence.current;
    const previousPeriod = period;
    const previousRange = range;
    const started = performance.now();
    operationStarted.current = started;
    setPeriod(nextPeriod); setRange(nextRange);
    setLoading(true); setError(""); setStatus("切换 K 线周期…");
    try {
      const history = await api.bars(stock.code, nextPeriod, nextRange);
      if (sequence !== barsLoadSequence.current) return;
      setBars(history.items);
      setPerf(current => ({ ...current, frontendMs: performance.now() - started, httpMs: history.http_ms || 0, queryMs: history.timings.total_ms || 0, cache: Boolean(history.client_cache_hit || history.cache_hit) }));
      setStatus(`${history.client_cache_hit ? "前端缓存" : history.cache_hit ? "后端缓存" : "本地聚合"} · ${periodLabel(nextPeriod)} · ${history.items.length} 根`);
    } catch (e) {
      if (sequence !== barsLoadSequence.current) return;
      const message = e instanceof Error ? e.message : "周期切换失败";
      setPeriod(previousPeriod); setRange(previousRange); setError(message); setStatus(message);
    } finally {
      if (sequence === barsLoadSequence.current) setLoading(false);
    }
  }, [period, range, stock]);

  function onSearch(value: string) {
    setQuery(value); setSearchOpen(Boolean(value.trim())); setActiveResult(0);
    if (searchTimer.current) clearTimeout(searchTimer.current);
    if (!value.trim()) { setResults([]); return; }
    searchTimer.current = setTimeout(() => void api.search(value).then(result => setResults(result.items.slice(0, 8))).catch(() => setResults([])), 100);
  }

  function searchKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") { e.preventDefault(); setActiveResult(index => Math.min(index + 1, results.length - 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setActiveResult(index => Math.max(index - 1, 0)); }
    if (e.key === "Enter" && results[activeResult]) { e.preventDefault(); void loadStock(results[activeResult].code, "D", "6M"); }
    if (e.key === "Escape") setSearchOpen(false);
  }

  async function toggleWatchlist() {
    if (!stock) return;
    const exists = state.watchlist.some(item => item.code === stock.code);
    try {
      const next = await api.updateState(stock.code, "watchlist", !exists);
      setState(next); await refreshWatchlist(next);
      setStatus(`${stock.name} 已${exists ? "移出" : "加入"}自选`);
    } catch (e) { setError(e instanceof Error ? e.message : "自选保存失败"); }
  }

  function zoomIn() {
    const order = ["ALL", "5Y", "3Y", "1Y", "YTD", "6M", "3M", "1M", "5D", "1D"];
    const index = order.indexOf(range);
    const next = order[Math.min(order.length - 1, index + 1)];
    void changeBars(period, next);
  }

  function changeLayout(next: 1 | 2 | 4) {
    setLayout(next); setMaximizedPane(null); setLayoutOpen(false);
    window.setTimeout(() => chartRefs.current.forEach(chart => chart?.resize()), 40);
  }

  async function toggleFullscreen() {
    if (!workspaceRef.current) return;
    if (document.fullscreenElement) await document.exitFullscreen();
    else await workspaceRef.current.requestFullscreen();
  }

  function selectDrawing(index: number | null) {
    setSelectedDrawing(index);
    if (index == null) return;
    const drawing = drawings[index];
    if (!drawing) return;
    setDrawingColor(drawing.color || "#2864ff");
    setDrawingLineWidth(drawing.lineWidth || 2);
    if (drawing.kind === "text" && drawing.text) setDrawingText(drawing.text);
  }

  function changePatternCategory(category: PatternKey) {
    patternCategoryRef.current = category;
    patternCursorRef.current = -1;
    setPatternPendingCode(null);
    setPatternCategory(category);
    if (stock) window.history.replaceState(null, "", `/market?code=${stock.code}&category=${category}`);
  }

  function applyDrawingStyle(change: Pick<ChartDrawing, "color" | "lineWidth" | "text">) {
    if (selectedDrawing == null) return;
    setDrawings(items => items.map((item, index) => index === selectedDrawing ? { ...item, ...change } : item));
  }

  function changeDrawingColor(color: string) {
    setDrawingColor(color);
    applyDrawingStyle({ color });
  }

  function changeDrawingLineWidth(lineWidth: number) {
    setDrawingLineWidth(lineWidth);
    applyDrawingStyle({ lineWidth });
  }

  function changeDrawingText(text: string) {
    setDrawingText(text);
    if (selectedDrawing != null && drawings[selectedDrawing]?.kind === "text") applyDrawingStyle({ text });
  }

  function completeDrawing(drawing: ChartDrawing) {
    setSelectedDrawing(drawings.length);
    setDrawings(items => [...items, drawing]);
    setDrawingMode("select");
  }

  function deleteDrawing(index: number) {
    setDrawings(items => items.filter((_item, itemIndex) => itemIndex !== index));
    setSelectedDrawing(null);
  }

  function rightWidthLimit() {
    if (typeof window === "undefined") return 560;
    const sidebar = window.innerWidth <= 1320 ? 78 : 136;
    return Math.max(300, Math.min(560, window.innerWidth - sidebar - 620));
  }

  function resizeRightbarAt(clientX: number) {
    const next = Math.max(300, Math.min(rightWidthLimit(), window.innerWidth - clientX));
    if (rightResizeFrame.current != null) cancelAnimationFrame(rightResizeFrame.current);
    rightResizeFrame.current = requestAnimationFrame(() => {
      rightResizeFrame.current = null;
      setRightWidth(next);
    });
  }

  function startRightResize(event: React.PointerEvent<HTMLDivElement>) {
    rightResizeActive.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    resizeRightbarAt(event.clientX);
  }

  function moveRightResize(event: React.PointerEvent<HTMLDivElement>) {
    if (rightResizeActive.current) resizeRightbarAt(event.clientX);
  }

  function finishRightResize(event: React.PointerEvent<HTMLDivElement>) {
    rightResizeActive.current = false;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }

  function rightResizeKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight" && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    if (event.key === "Home") setRightWidth(300);
    else if (event.key === "End") setRightWidth(rightWidthLimit());
    else setRightWidth(current => Math.max(300, Math.min(rightWidthLimit(), current + (event.key === "ArrowLeft" ? 24 : -24))));
  }

  function toggleRightbar() {
    if (window.matchMedia("(max-width: 1100px)").matches) setRightOpen(value => !value);
    else setRightCollapsed(value => !value);
    window.setTimeout(() => chartRefs.current.forEach(chart => chart?.resize()), 30);
  }

  const onRendered = useCallback((durationMs: number) => {
    setPerf(current => ({ ...current, renderMs: durationMs, frontendMs: operationStarted.current ? performance.now() - operationStarted.current : current.frontendMs }));
  }, []);

  const latest = bars.at(-1);
  const maLegend = useMemo(() => latest ? [latest.ma5, latest.ma10, latest.ma20] : [], [latest]);
  const watched = Boolean(stock && state.watchlist.some(item => item.code === stock.code));
  const visibleCount = rangeLimits[range]?.[period] || 110;
  const paneIndexes = maximizedPane == null ? Array.from({ length: layout }, (_value, index) => index) : [maximizedPane];

  return <div
    ref={shellRef}
    className={`app-shell market-shell ${rightCollapsed ? "right-collapsed" : ""}`}
    style={{ "--rightbar-width": `${rightWidth}px` } as React.CSSProperties}
    data-rightbar-state={rightCollapsed ? "collapsed" : "expanded"}
  >
    <AppSidebar active="market" />
    <main className="market-main">
      <header className="market-topbar">
        <div className="market-search-wrap">
          <Search className="search-left" />
          <input value={query} onFocus={() => query && setSearchOpen(true)} onChange={e => onSearch(e.target.value)} onKeyDown={searchKeyDown} placeholder="搜索股票名称 / 代码 / 拼音首字母" aria-label="搜索股票" />
          {query ? <button onClick={() => onSearch("")} aria-label="清空搜索"><X /></button> : <Search className="search-right" />}
          {searchOpen && <div className="search-results" role="listbox">{results.length ? results.map((item, index) => <button role="option" aria-selected={index === activeResult} key={item.code} className={index === activeResult ? "active" : ""} onMouseEnter={() => setActiveResult(index)} onClick={() => void loadStock(item.code, "D", "6M")}><span>{item.code}</span><b>{item.name}</b><em>{item.initials}</em></button>) : <p>没有匹配的本地股票</p>}</div>}
        </div>
        <div className="layout-tools"><div className="layout-picker"><button onClick={() => setLayoutOpen(value => !value)} aria-expanded={layoutOpen}><Grid2X2 /><span>{layout} 图布局</span><ChevronDown /></button>{layoutOpen && <div className="layout-menu">{([1, 2, 4] as const).map(value => <button key={value} className={layout === value ? "active" : ""} onClick={() => changeLayout(value)}>{value} 图</button>)}</div>}</div><button onClick={() => changeLayout(1)} title="恢复单图" aria-label="恢复单图"><Grid2X2 /><span>{maximizedPane == null ? `布局 ${layout}` : "单图放大"}</span></button><button onClick={() => chartRefs.current.forEach(chart => chart?.fitContent())} title="适配全部历史" aria-label="适配图表"><Settings2 /></button><button className="mobile-panel-button" onClick={() => setRightOpen(true)} aria-label="打开右侧面板"><PanelRightOpen /></button><button onClick={toggleRightbar} aria-label="折叠或展开右侧栏" aria-expanded={!rightCollapsed} title={rightCollapsed ? "展开右侧栏" : "折叠右侧栏"}><Menu /></button></div>
      </header>

      <section className="quote-summary">
        {stock ? <>
          <div className="quote-main"><div className="quote-title"><h1>{stock.name}</h1><span>{stock.code}</span><em>{stock.market || "A股"}</em><em>{stock.industry || "本地数据"}</em>{stock.is_st && <em className="st-badge">ST</em>}</div><div className={`quote-price ${stock.pct_chg >= 0 ? "up" : "down"}`}><b>{fmtNumber(stock.close)}</b><span>CNY</span><p>{signed(stock.change)}　{signed(stock.pct_chg)}%</p></div></div>
          <div className="quote-facts"><QuoteFact label="今开" value={fmtNumber(stock.open)} /><QuoteFact label="最高" value={fmtNumber(stock.high)} /><QuoteFact label="最低" value={fmtNumber(stock.low)} /><QuoteFact label="昨收" value={fmtNumber(stock.pre_close)} /><QuoteFact label="成交额" value={fmtAmount(stock.amount)} /><QuoteFact label="成交量" value={stock.volume == null ? "—" : `${fmtNumber(stock.volume / 10000)}万手`} /><QuoteFact label="换手率" value={stock.turnover_rate == null ? "—" : `${fmtNumber(stock.turnover_rate)}%`} /><QuoteFact label="市值" value={fmtMarketValue(stock.total_mv)} /></div>
          <div className="quote-dates"><span>行情 {formatDate(stock.as_of?.quote)}</span><span>估值 {formatDate(stock.as_of?.valuation)}</span><span>ST {formatDate(stock.as_of?.st)}</span><span>复权 {formatDate(stock.as_of?.adj_factor)}</span></div>
        </> : <div className="quote-loading">{status}</div>}
      </section>

      {stock?.warnings?.length ? <div className="market-warning">{stock.warnings.join(" · ")}</div> : null}

      <section ref={workspaceRef} className="chart-workspace" data-layout={layout} data-fullscreen={fullscreen}>
        <div className="chart-toolbar">
          <div className="period-tabs">{unavailablePeriods.map(label => <button key={label} disabled title="本地 zer0share 当前只有日线，分钟周期不可用">{label}</button>)}{periods.map(([label, value]) => <button key={label} className={period === value ? "active" : ""} onClick={() => void changeBars(value)}>{label}</button>)}</div>
          <div className="chart-actions"><DisabledButton title="指标尚未实现">指标 <ChevronDown /></DisabledButton><i /><DisabledButton title="对比尚未实现">对比</DisabledButton><i /><DisabledButton title="预警尚未实现"><Bell />预警</DisabledButton><i /><DisabledButton title="回放尚未实现"><RotateCcw />回放</DisabledButton><i /><DisabledButton title="截图导出尚未实现" label="截图"><Camera /></DisabledButton><button onClick={() => void toggleFullscreen()} aria-label={fullscreen ? "退出全屏" : "进入全屏"} title={fullscreen ? "退出全屏" : "进入全屏"}><Fullscreen />{fullscreen ? "退出" : "全屏"}</button></div>
          <div className="ma-legend">
            <span className="ma5">MA5　{fmtNumber(maLegend[0])}</span><span className="ma10">MA10　{fmtNumber(maLegend[1])}</span><span className="ma20">MA20　{fmtNumber(maLegend[2])}</span>
            <div className="drawing-style-controls" aria-label="画线样式">
              <label className="drawing-color-control" title="画线颜色"><Palette /><input type="color" value={drawingColor} onChange={event => changeDrawingColor(event.target.value)} aria-label="画线颜色" /></label>
              <label><span>线宽</span><select value={drawingLineWidth} onChange={event => changeDrawingLineWidth(Number(event.target.value))} aria-label="画线线宽">{[1, 2, 3, 4, 5].map(value => <option value={value} key={value}>{value}px</option>)}</select></label>
              {(drawingMode === "text" || (selectedDrawing != null && drawings[selectedDrawing]?.kind === "text")) && <label className="drawing-text-control"><span>文本</span><input value={drawingText} maxLength={40} onChange={event => changeDrawingText(event.target.value)} aria-label="标注文本" /></label>}
            </div>
            <span className="perf-chip" data-testid="market-performance">总 {perf.frontendMs.toFixed(0)}ms · HTTP {perf.httpMs.toFixed(0)}ms · 查询 {perf.queryMs.toFixed(0)}ms · 绘制 {perf.renderMs.toFixed(0)}ms{perf.cache ? " · 缓存" : ""}</span>
          </div>
        </div>
        <div className="drawing-toolbar" aria-label="绘图工具">
          <div className="drawing-tool-group" role="group" aria-label="选择工具">
            <DrawingButton label="选择/调整" active={drawingMode === "select"} onClick={() => setDrawingMode("select")}><MousePointer2 /></DrawingButton>
            <DrawingButton label={`十字光标${crosshairEnabled ? "已开启" : "已关闭"}`} active={crosshairEnabled} onClick={() => setCrosshairEnabled(value => !value)}><Crosshair /></DrawingButton>
          </div>
          <div className="drawing-tool-group" role="group" aria-label="线工具">
            <DrawingButton label="趋势线" active={drawingMode === "trend"} onClick={() => setDrawingMode("trend")}><PenLine /></DrawingButton>
            <DrawingButton label="线段" active={drawingMode === "segment"} onClick={() => setDrawingMode("segment")}><Minus /></DrawingButton>
            <DrawingButton label="射线" active={drawingMode === "ray"} onClick={() => setDrawingMode("ray")}><ArrowUpRight /></DrawingButton>
            <DrawingButton label="水平线" active={drawingMode === "horizontal"} onClick={() => setDrawingMode("horizontal")}><MoveHorizontal /></DrawingButton>
            <DrawingButton label="垂直线" active={drawingMode === "vertical"} onClick={() => setDrawingMode("vertical")}><MoveVertical /></DrawingButton>
          </div>
          <div className="drawing-tool-group" role="group" aria-label="斐波那契工具">
            <DrawingButton label="斐波那契回撤" active={drawingMode === "fibonacci"} onClick={() => setDrawingMode("fibonacci")}><Layers3 /></DrawingButton>
            <DrawingButton label="斐波那契扩展" active={drawingMode === "fibonacci-extension"} onClick={() => setDrawingMode("fibonacci-extension")}><LineChart /></DrawingButton>
          </div>
          <div className="drawing-tool-group" role="group" aria-label="曲线和自由绘制">
            <DrawingButton label="曲线" active={drawingMode === "curve"} onClick={() => setDrawingMode("curve")}><Spline /></DrawingButton>
            <DrawingButton label="自由绘制" active={drawingMode === "freehand"} onClick={() => setDrawingMode("freehand")}><Brush /></DrawingButton>
          </div>
          <div className="drawing-tool-group" role="group" aria-label="文本和测量">
            <DrawingButton label="文本" active={drawingMode === "text"} onClick={() => setDrawingMode("text")}><Type /></DrawingButton>
            <DrawingButton label="测量" active={drawingMode === "measure"} onClick={() => setDrawingMode("measure")}><Ruler /></DrawingButton>
          </div>
          <div className="drawing-tool-group drawing-tool-actions" role="group" aria-label="绘图操作">
            <DrawingButton label="放大图表" active={false} onClick={zoomIn}><ZoomIn /></DrawingButton>
            <DrawingButton label="删除所选" active={selectedDrawing != null} onClick={() => selectedDrawing != null && deleteDrawing(selectedDrawing)}><Trash2 /></DrawingButton>
            <DrawingButton label="清除画线（全部）" active={drawings.length > 0} onClick={() => { setDrawings([]); setSelectedDrawing(null); setDrawingMode(null); }}><Trash2 /></DrawingButton>
          </div>
        </div>
        <div className={`chart-stage chart-grid layout-${paneIndexes.length}`}>{error && !bars.length ? <div className="chart-error"><p>{error}</p><button onClick={() => stock && void loadStock(stock.code, period, range)}>重试</button></div> : paneIndexes.map(index => <div className="chart-pane" key={index} data-pane={index}><button className="pane-maximize" onClick={() => { setMaximizedPane(current => current === index ? null : index); window.setTimeout(() => chartRefs.current.forEach(chart => chart?.resize()), 40); }} aria-label={maximizedPane === index ? "退出单图放大" : `放大图表 ${index + 1}`}>{maximizedPane === index ? "恢复布局" : `图 ${index + 1} · 放大`}</button><MarketChart ref={handle => { chartRefs.current[index] = handle; }} bars={bars} visibleCount={visibleCount} drawingMode={drawingMode} crosshairEnabled={crosshairEnabled} drawingColor={drawingColor} drawingLineWidth={drawingLineWidth} drawingText={drawingText} drawings={drawings} selectedDrawingIndex={selectedDrawing} onDrawingSelect={selectDrawing} onDrawingsChange={setDrawings} onRendered={onRendered} onDrawComplete={completeDrawing} /></div>)}{loading && <div className="chart-loading">正在加载本地行情…</div>}</div>
        <div className="range-toolbar">{ranges.map(([label, value]) => <button className={range === value ? "active" : ""} key={value} onClick={() => void changeBars(period, value)}>{label}</button>)}<b>{bars[0]?.time || "—"} 至 {bars.at(-1)?.time || "—"}　<CalendarDays /></b></div>
      </section>
    </main>

    {rightOpen && <button className="rightbar-backdrop" onClick={() => setRightOpen(false)} aria-label="关闭右侧面板" />}
    {!rightCollapsed && <div
      className="market-right-resizer"
      data-testid="market-right-resizer"
      role="separator"
      aria-label="调整主图与右侧栏宽度"
      aria-orientation="vertical"
      aria-valuemin={300}
      aria-valuemax={560}
      aria-valuenow={Math.round(rightWidth)}
      tabIndex={0}
      onKeyDown={rightResizeKeyDown}
      onPointerDown={startRightResize}
      onPointerMove={moveRightResize}
      onPointerUp={finishRightResize}
      onPointerCancel={finishRightResize}
    />}
    <aside className={`market-rightbar ${rightOpen ? "open" : ""}`} aria-hidden={rightCollapsed}>
      <div className="rightbar-mobile-head"><b>股票面板</b><button onClick={() => setRightOpen(false)} aria-label="关闭"><X /></button></div>
      <div className="right-tabs">{tabs.map(tab => <button className={rightTab === tab ? "active" : ""} onClick={() => setRightTab(tab)} key={tab}>{tab}</button>)}</div>
      {rightTab === "自选" ? <>
        <div className="watch-header"><span>名称/代码</span><span>最新价</span><span>涨跌幅</span></div>
        <div className="watch-list">{watchlist.length ? watchlist.map(item => <button key={item.code} className={item.code === stock?.code ? "active" : ""} onClick={() => void loadStock(item.code, "D", "6M")}><span><b>{item.name}</b><em>{item.code}</em></span><strong>{fmtNumber(item.close)}</strong><i className={item.pct_chg >= 0 ? "up" : "down"}>{signed(item.pct_chg)}%</i></button>) : <PanelEmpty title="暂无自选" text="添加后会保存在本项目的本地数据库中。" />}</div>
        <button className={`add-watch ${watched ? "remove" : ""}`} onClick={() => void toggleWatchlist()} disabled={!stock}>{watched ? <X /> : <Plus />}{watched ? "移出自选" : "添加自选"}</button>
      </> : rightTab === "详情" ? <DetailPanel stock={stock} /> : rightTab === "形态" ? <PatternWorkspace activeCode={patternPendingCode || stock?.code || null} category={patternCategory} pool={patternPool} poolLoading={poolLoading} onCategory={changePatternCategory} onChoose={choosePatternStock} onStep={stepPatternStock}><PatternPanel stock={stock} data={pattern} loading={patternLoading} error={patternError} onRetry={() => stock && void loadPattern(stock.code)} /></PatternWorkspace> : <UnavailablePanel tab={rightTab} />}
    </aside>

    <footer className="market-statusbar"><span><i className={stock ? "connected" : ""} />{stock ? "已连接" : "未连接"}</span><span><Clock3 />{clock}</span><span className="status-center">本地数据　{status}</span><span><CircleDot />zer0share 日线快照</span><span>CN</span></footer>
  </div>;
}

function DetailPanel({ stock }: { stock: Stock | null }) {
  if (!stock) return <PanelEmpty title="尚未选择股票" text="先搜索或从自选中打开一只股票。" />;
  return <div className="detail-panel"><div className="panel-title"><Layers3 /><div><h3>{stock.name}</h3><p>{stock.ts_code}</p></div></div><dl><dt>市场</dt><dd>{stock.market || "—"}</dd><dt>行业</dt><dd>{stock.industry || "—"}</dd><dt>总市值</dt><dd>{fmtMarketValue(stock.total_mv)}</dd><dt>市盈率 TTM</dt><dd>{fmtNumber(stock.pe_ttm)}</dd><dt>市净率</dt><dd>{fmtNumber(stock.pb)}</dd><dt>ST 状态</dt><dd>{stock.is_st ? "是" : "否"}</dd></dl><div className="panel-dates"><b>数据表日期</b><span>行情 {formatDate(stock.as_of?.quote)}</span><span>估值 {formatDate(stock.as_of?.valuation)}</span><span>ST {formatDate(stock.as_of?.st)}</span><span>复权 {formatDate(stock.as_of?.adj_factor)}</span></div>{stock.warnings?.map(item => <p className="panel-warning" key={item}>{item}</p>)}</div>;
}

function PatternWorkspace({ activeCode, category, pool, poolLoading, onCategory, onChoose, onStep, children }: { activeCode: string | null; category: PatternKey; pool: Stock[]; poolLoading: boolean; onCategory: (category: PatternKey) => void; onChoose: (code: string) => void; onStep: (direction: -1 | 1) => boolean; children: React.ReactNode }) {
  const activeButtonRef = useRef<HTMLButtonElement>(null);
  const poolRef = useRef<HTMLDivElement>(null);
  const lastWheelAt = useRef(0);

  useEffect(() => {
    activeButtonRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeCode]);

  useEffect(() => {
    const list = poolRef.current;
    if (!list) return;
    const wheelNavigate = (event: WheelEvent) => {
      if (Math.abs(event.deltaY) < 4 || poolLoading) return;
      event.preventDefault();
      const now = performance.now();
      if (now - lastWheelAt.current < 90) return;
      lastWheelAt.current = now;
      onStep(event.deltaY > 0 ? 1 : -1);
    };
    list.addEventListener("wheel", wheelNavigate, { passive: false });
    return () => list.removeEventListener("wheel", wheelNavigate);
  }, [onStep, poolLoading]);

  return <div className="pattern-workspace">
    <section className="pattern-pool-section" aria-labelledby="pattern-pool-title">
      <div className="panel-section-heading"><b id="pattern-pool-title">形态股票列表</b><span>{pool.length} 只 · ↑↓ / 滚轮切换</span></div>
      <label className="pattern-group"><span>形态分组</span><select data-testid="pattern-group-select" value={category} onChange={event => onCategory(event.target.value as PatternKey)}>{(Object.keys(patternNames) as PatternKey[]).map(key => <option key={key} value={key}>{patternNames[key]}</option>)}</select></label>
      <div ref={poolRef} className="pattern-pool" data-testid="pattern-pool" data-wheel-navigation="enabled">{poolLoading ? <p>正在加载股票池…</p> : pool.length ? pool.map((item, index) => <button ref={item.code === activeCode ? activeButtonRef : undefined} key={item.code} aria-current={item.code === activeCode ? "true" : undefined} className={item.code === activeCode ? "active" : ""} onClick={() => onChoose(item.code)}><b>{index + 1}</b><span><strong>{item.name}</strong><small>{item.code}</small></span><em>{Math.round(item.score || 0)}分</em></button>) : <p>该分类当前没有可用股票</p>}</div>
    </section>
    <section className="pattern-facts-section" aria-labelledby="pattern-facts-title">
      <div className="panel-section-heading"><b id="pattern-facts-title">当前个股形态事实</b><span>{activeCode || "未选择"}</span></div>
      <div className="pattern-facts">{children}</div>
    </section>
  </div>;
}

function PatternPanel({ stock, data, loading, error, onRetry }: { stock: Stock | null; data: PatternResponse | null; loading: boolean; error: string; onRetry: () => void }) {
  if (!stock) return <PanelEmpty title="尚未选择股票" text="形态标签只展示当前股票的事实。" />;
  if (loading) return <PanelEmpty title="读取形态事实" text="正在查询本地筛选历史…" />;
  if (error) return <div className="panel-error"><p>{error}</p><button onClick={onRetry}>重试</button></div>;
  if (!data || data.calculation_state === "not_calculated") return <div className="pattern-empty"><CircleDot /><h3>尚未计算</h3><p>{data?.message || "请先在选股看板运行筛选。"}</p><Link href={`/?code=${stock.code}`}>到选股看板查看该股记录</Link></div>;
  if (data.calculation_state === "calculated_no_match") return <div className="pattern-empty"><CircleDot /><h3>已计算但无匹配</h3><p>{data.message}</p><PatternDates data={data} /><Link href={`/?code=${stock.code}`}>到选股看板查看该股记录</Link></div>;
  const current = data.current!;
  return <div className="pattern-panel"><div className="pattern-panel-head"><div><small>规则版本 v{data.rule_version}</small><h3>{stock.name} · 形态事实</h3></div><span>{formatDate(current.trade_date)}</span></div>{current.matches.map(match => <article key={match.category}><div><span>{patternNames[match.category]}</span><b>{match.score.toFixed(1)} 分</b></div><p>匹配 · 阈值 {match.minimum_score ?? data.rules[match.category]?.minimum_score} 分</p><ul>{match.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul><dl>{Object.entries(match.metrics).slice(0, 6).map(([key, value]) => <span key={key}><dt>{metricLabel(key)}</dt><dd>{fmtMetric(key, value)}</dd></span>)}</dl></article>)}<PatternDates data={data} />{current.run_warnings.map(item => <p className="panel-warning" key={item}>{item}</p>)}<div className="pattern-history"><b>形态历史</b>{data.history.slice(0, 6).map(item => <span key={`${item.run_id}-${item.created_at}`}><em>{formatDate(item.trade_date)}</em><strong>{item.status === "matched" ? item.matches.map(match => patternNames[match.category]).join("、") : item.status === "no_match" ? "无匹配" : "未计算"}</strong></span>)}</div><Link className="pattern-link" href={`/?code=${stock.code}`}>到选股看板查看该股记录</Link></div>;
}

function PatternDates({ data }: { data: PatternResponse }) { return <div className="panel-dates"><b>数据表日期</b><span>行情 {formatDate(data.as_of.daily_kline || data.as_of.daily)}</span><span>估值 {formatDate(data.as_of.daily_basic || data.as_of.valuation)}</span><span>ST {formatDate(data.as_of.stock_st || data.as_of.st)}</span><span>复权 {formatDate(data.as_of.adj_factor)}</span></div>; }
function UnavailablePanel({ tab }: { tab: RightTab }) { return <PanelEmpty title={`${tab} · 暂不可用`} text={`${tab}能力尚未实现，本版本只保留禁用入口。`} />; }
function PanelEmpty({ title, text }: { title: string; text: string }) { return <div className="right-placeholder"><CircleDot /><h3>{title}</h3><p>{text}</p></div>; }
function QuoteFact({ label, value }: { label: string; value: string }) { return <span><small>{label}</small><b>{value}</b></span>; }
function DrawingButton({ label, active, onClick, children }: { label: string; active: boolean; onClick: () => void; children: React.ReactNode }) { return <button title={label} aria-label={label} aria-pressed={active} className={active ? "active" : ""} onClick={onClick}>{children}</button>; }
function DisabledButton({ title, label, children }: { title: string; label?: string; children: React.ReactNode }) { return <button disabled title={title} aria-label={label || title}>{children}</button>; }
function periodLabel(value: string) { return ({ D: "日K", W: "周K", M: "月K", Q: "季K", Y: "年K" } as Record<string, string>)[value] || value; }
function signed(value?: number) { if (value == null || !Number.isFinite(value)) return "—"; return `${value >= 0 ? "+" : ""}${fmtNumber(value)}`; }
