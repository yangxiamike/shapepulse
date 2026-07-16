"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  Bell,
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
  MousePointer2,
  PanelRightOpen,
  Pencil,
  Plus,
  RotateCcw,
  Ruler,
  Search,
  Settings2,
  Trash2,
  Type,
  X,
  ZoomIn,
} from "lucide-react";
import { AppSidebar } from "./AppSidebar";
import { MarketChart, type ChartDrawing, type DrawingKind } from "./MarketChart";
import { api, fmtAmount, fmtMarketValue, fmtMetric, fmtNumber, formatDate, metricLabel } from "../lib/api";
import type { Bar, PatternKey, PatternResponse, StateSnapshot, Stock } from "../lib/types";

const periods = [
  ["日K", "D"], ["周K", "W"], ["月K", "M"], ["季K", "Q"], ["年K", "Y"],
] as const;
const unavailablePeriods = ["分时", "5分", "15分", "30分", "60分"];
const ranges = [["1天", "1D"], ["5天", "5D"], ["1个月", "1M"], ["3个月", "3M"], ["6个月", "6M"], ["YTD", "YTD"], ["1年", "1Y"], ["3年", "3Y"], ["5年", "5Y"], ["全部", "ALL"]] as const;
const tabs = ["自选", "详情", "形态", "指标", "因子", "交易"] as const;
type RightTab = typeof tabs[number];

const patternNames: Record<PatternKey, string> = { breakout: "突破启动", pullback: "上升趋势回调", range_bounce: "区间下沿反弹" };
const emptyState: StateSnapshot = { viewed: [], saved: [], pending: [], watchlist: [], history: { runs: [], recommendations: [] } };

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
  const [drawingMode, setDrawingMode] = useState<DrawingKind | null>(null);
  const [drawings, setDrawings] = useState<ChartDrawing[]>([]);
  const [crosshairEnabled, setCrosshairEnabled] = useState(true);
  const [status, setStatus] = useState("连接本地数据…");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [clock, setClock] = useState("—");
  const [perf, setPerf] = useState({ frontendMs: 0, httpMs: 0, queryMs: 0, renderMs: 0, cache: false });
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const operationStarted = useRef(0);

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

  const loadStock = useCallback(async (code: string, nextPeriod = "D", nextRange = "6M") => {
    const started = performance.now();
    operationStarted.current = started;
    setLoading(true); setError(""); setStatus("正在读取本地行情…");
    try {
      const [detailResult, history] = await Promise.all([api.stock(code), api.bars(code, nextPeriod, nextRange)]);
      const detail = detailResult.item;
      setStock(detail); setBars(history.items); setPeriod(nextPeriod); setRange(nextRange);
      setPerf(current => ({ ...current, frontendMs: performance.now() - started, httpMs: detailResult.httpMs + (history.http_ms || 0), queryMs: history.timings.total_ms || 0, cache: detailResult.cacheHit && Boolean(history.client_cache_hit) }));
      setStatus(`${history.client_cache_hit ? "前端缓存" : history.cache_hit ? "后端缓存" : "本地快照"} · ${formatDate(history.as_of.daily)} · ${history.items.length} 根`);
      setSearchOpen(false); setQuery(""); setRightOpen(false);
      window.history.replaceState(null, "", `/market?code=${detail.code}`);
      void api.updateState(detail.code, "viewed").catch(() => undefined);
      void loadPattern(detail.code);
    } catch (e) {
      const message = e instanceof Error ? e.message : "本地行情加载失败";
      setError(message); setStatus(message);
    } finally { setLoading(false); }
  }, [loadPattern]);

  useEffect(() => {
    const code = new URLSearchParams(window.location.search).get("code") || "000001";
    const updateClock = () => setClock(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
    const boot = window.setTimeout(() => {
      void loadStock(code);
      void api.state().then(snapshot => { setState(snapshot); void refreshWatchlist(snapshot); }).catch(() => undefined);
      updateClock();
    }, 0);
    const timer = window.setInterval(updateClock, 1000);
    return () => { window.clearTimeout(boot); window.clearInterval(timer); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const changeBars = useCallback(async (nextPeriod: string, nextRange = range) => {
    if (!stock || (nextPeriod === period && nextRange === range)) return;
    const started = performance.now();
    operationStarted.current = started;
    setLoading(true); setError(""); setStatus("切换 K 线周期…");
    try {
      const history = await api.bars(stock.code, nextPeriod, nextRange);
      setBars(history.items); setPeriod(nextPeriod); setRange(nextRange);
      setPerf(current => ({ ...current, frontendMs: performance.now() - started, httpMs: history.http_ms || 0, queryMs: history.timings.total_ms || 0, cache: Boolean(history.client_cache_hit || history.cache_hit) }));
      setStatus(`${history.client_cache_hit ? "前端缓存" : history.cache_hit ? "后端缓存" : "本地聚合"} · ${periodLabel(nextPeriod)} · ${history.items.length} 根`);
    } catch (e) { const message = e instanceof Error ? e.message : "周期切换失败"; setError(message); setStatus(message); }
    finally { setLoading(false); }
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

  const onRendered = useCallback((durationMs: number) => {
    setPerf(current => ({ ...current, renderMs: durationMs, frontendMs: operationStarted.current ? performance.now() - operationStarted.current : current.frontendMs }));
  }, []);

  const latest = bars.at(-1);
  const maLegend = useMemo(() => latest ? [latest.ma5, latest.ma10, latest.ma20] : [], [latest]);
  const watched = Boolean(stock && state.watchlist.some(item => item.code === stock.code));

  return <div className="app-shell market-shell">
    <AppSidebar active="market" />
    <main className="market-main">
      <header className="market-topbar">
        <div className="market-search-wrap">
          <Search className="search-left" />
          <input value={query} onFocus={() => query && setSearchOpen(true)} onChange={e => onSearch(e.target.value)} onKeyDown={searchKeyDown} placeholder="搜索股票名称 / 代码 / 拼音首字母" aria-label="搜索股票" />
          {query ? <button onClick={() => onSearch("")} aria-label="清空搜索"><X /></button> : <Search className="search-right" />}
          {searchOpen && <div className="search-results" role="listbox">{results.length ? results.map((item, index) => <button role="option" aria-selected={index === activeResult} key={item.code} className={index === activeResult ? "active" : ""} onMouseEnter={() => setActiveResult(index)} onClick={() => void loadStock(item.code, "D", "6M")}><span>{item.code}</span><b>{item.name}</b><em>{item.initials}</em></button>) : <p>没有匹配的本地股票</p>}</div>}
        </div>
        <div className="layout-tools"><DisabledButton title="多图布局尚未实现"><Grid2X2 /><span>多图布局</span><ChevronDown /></DisabledButton><DisabledButton title="布局保存尚未实现"><span>未命名布局</span><ChevronDown /></DisabledButton><DisabledButton title="布局设置尚未实现" label="布局设置"><Settings2 /></DisabledButton><button className="mobile-panel-button" onClick={() => setRightOpen(true)} aria-label="打开右侧面板"><PanelRightOpen /></button><button aria-label="菜单"><Menu /></button></div>
      </header>

      <section className="quote-summary">
        {stock ? <>
          <div className="quote-main"><div className="quote-title"><h1>{stock.name}</h1><span>{stock.code}</span><em>{stock.market || "A股"}</em><em>{stock.industry || "本地数据"}</em>{stock.is_st && <em className="st-badge">ST</em>}</div><div className={`quote-price ${stock.pct_chg >= 0 ? "up" : "down"}`}><b>{fmtNumber(stock.close)}</b><span>CNY</span><p>{signed(stock.change)}　{signed(stock.pct_chg)}%</p></div></div>
          <div className="quote-facts"><QuoteFact label="今开" value={fmtNumber(stock.open)} /><QuoteFact label="最高" value={fmtNumber(stock.high)} /><QuoteFact label="最低" value={fmtNumber(stock.low)} /><QuoteFact label="昨收" value={fmtNumber(stock.pre_close)} /><QuoteFact label="成交额" value={fmtAmount(stock.amount)} /><QuoteFact label="成交量" value={stock.volume == null ? "—" : `${fmtNumber(stock.volume / 10000)}万手`} /><QuoteFact label="换手率" value={stock.turnover_rate == null ? "—" : `${fmtNumber(stock.turnover_rate)}%`} /><QuoteFact label="市值" value={fmtMarketValue(stock.total_mv)} /></div>
          <div className="quote-dates"><span>行情 {formatDate(stock.as_of?.quote)}</span><span>估值 {formatDate(stock.as_of?.valuation)}</span><span>ST {formatDate(stock.as_of?.st)}</span><span>复权 {formatDate(stock.as_of?.adj_factor)}</span></div>
        </> : <div className="quote-loading">{status}</div>}
      </section>

      {stock?.warnings?.length ? <div className="market-warning">{stock.warnings.join(" · ")}</div> : null}

      <section className="chart-workspace">
        <div className="chart-toolbar">
          <div className="period-tabs">{unavailablePeriods.map(label => <button key={label} disabled title="本地 zer0share 当前只有日线，分钟周期不可用">{label}</button>)}{periods.map(([label, value]) => <button key={label} className={period === value ? "active" : ""} onClick={() => void changeBars(value)}>{label}</button>)}</div>
          <div className="chart-actions"><DisabledButton title="指标尚未实现">指标 <ChevronDown /></DisabledButton><i /><DisabledButton title="对比尚未实现">对比</DisabledButton><i /><DisabledButton title="预警尚未实现"><Bell />预警</DisabledButton><i /><DisabledButton title="回放尚未实现"><RotateCcw />回放</DisabledButton><i /><DisabledButton title="截图导出尚未实现" label="截图"><Camera /></DisabledButton><DisabledButton title="全屏尚未实现" label="全屏"><Fullscreen /></DisabledButton></div>
          <div className="ma-legend"><span className="ma5">MA5　{fmtNumber(maLegend[0])}</span><span className="ma10">MA10　{fmtNumber(maLegend[1])}</span><span className="ma20">MA20　{fmtNumber(maLegend[2])}</span><span className="perf-chip" data-testid="market-performance">总 {perf.frontendMs.toFixed(0)}ms · HTTP {perf.httpMs.toFixed(0)}ms · 查询 {perf.queryMs.toFixed(0)}ms · 绘制 {perf.renderMs.toFixed(0)}ms{perf.cache ? " · 缓存" : ""}</span></div>
        </div>
        <div className="drawing-toolbar">
          <DrawingButton label="光标/拖动" active={!drawingMode} onClick={() => setDrawingMode(null)}><MousePointer2 /></DrawingButton>
          <DrawingButton label="趋势线" active={drawingMode === "line"} onClick={() => setDrawingMode(drawingMode === "line" ? null : "line")}><Pencil /></DrawingButton>
          <DrawingButton label={`十字光标${crosshairEnabled ? "已开启" : "已关闭"}`} active={crosshairEnabled} onClick={() => setCrosshairEnabled(value => !value)}><Crosshair /></DrawingButton>
          <DrawingButton label="水平线" active={drawingMode === "horizontal"} onClick={() => setDrawingMode(drawingMode === "horizontal" ? null : "horizontal")}><LineChart /></DrawingButton>
          <DrawingButton label="文本" active={drawingMode === "text"} onClick={() => setDrawingMode(drawingMode === "text" ? null : "text")}><Type /></DrawingButton>
          <DrawingButton label="测量" active={drawingMode === "measure"} onClick={() => setDrawingMode(drawingMode === "measure" ? null : "measure")}><Ruler /></DrawingButton>
          <DrawingButton label="放大图表" active={false} onClick={zoomIn}><ZoomIn /></DrawingButton>
          <DrawingButton label="清除画线" active={drawings.length > 0} onClick={() => setDrawings([])}><Trash2 /></DrawingButton>
        </div>
        <div className="chart-stage">{error && !bars.length ? <div className="chart-error"><p>{error}</p><button onClick={() => stock && void loadStock(stock.code, period, range)}>重试</button></div> : <MarketChart bars={bars} drawingMode={drawingMode} crosshairEnabled={crosshairEnabled} drawings={drawings} onRendered={onRendered} onDrawComplete={drawing => { setDrawings(items => [...items, drawing]); setDrawingMode(null); }} />}{loading && <div className="chart-loading">正在加载本地行情…</div>}</div>
        <div className="range-toolbar">{ranges.map(([label, value]) => <button className={range === value ? "active" : ""} key={value} onClick={() => void changeBars(period, value)}>{label}</button>)}<b>{bars[0]?.time || "—"} 至 {bars.at(-1)?.time || "—"}　<CalendarDays /></b></div>
      </section>
    </main>

    {rightOpen && <button className="rightbar-backdrop" onClick={() => setRightOpen(false)} aria-label="关闭右侧面板" />}
    <aside className={`market-rightbar ${rightOpen ? "open" : ""}`}>
      <div className="rightbar-mobile-head"><b>股票面板</b><button onClick={() => setRightOpen(false)} aria-label="关闭"><X /></button></div>
      <div className="right-tabs">{tabs.map(tab => <button className={rightTab === tab ? "active" : ""} onClick={() => setRightTab(tab)} key={tab}>{tab}</button>)}</div>
      {rightTab === "自选" ? <>
        <div className="watch-header"><span>名称/代码</span><span>最新价</span><span>涨跌幅</span></div>
        <div className="watch-list">{watchlist.length ? watchlist.map(item => <button key={item.code} className={item.code === stock?.code ? "active" : ""} onClick={() => void loadStock(item.code, "D", "6M")}><span><b>{item.name}</b><em>{item.code}</em></span><strong>{fmtNumber(item.close)}</strong><i className={item.pct_chg >= 0 ? "up" : "down"}>{signed(item.pct_chg)}%</i></button>) : <PanelEmpty title="暂无自选" text="添加后会保存在本项目的本地数据库中。" />}</div>
        <button className={`add-watch ${watched ? "remove" : ""}`} onClick={() => void toggleWatchlist()} disabled={!stock}>{watched ? <X /> : <Plus />}{watched ? "移出自选" : "添加自选"}</button>
      </> : rightTab === "详情" ? <DetailPanel stock={stock} /> : rightTab === "形态" ? <PatternPanel stock={stock} data={pattern} loading={patternLoading} error={patternError} onRetry={() => stock && void loadPattern(stock.code)} /> : <UnavailablePanel tab={rightTab} />}
    </aside>

    <footer className="market-statusbar"><span><i className={stock ? "connected" : ""} />{stock ? "已连接" : "未连接"}</span><span><Clock3 />{clock}</span><span className="status-center">本地数据　{status}</span><span><CircleDot />zer0share 日线快照</span><span>CN</span></footer>
  </div>;
}

function DetailPanel({ stock }: { stock: Stock | null }) {
  if (!stock) return <PanelEmpty title="尚未选择股票" text="先搜索或从自选中打开一只股票。" />;
  return <div className="detail-panel"><div className="panel-title"><Layers3 /><div><h3>{stock.name}</h3><p>{stock.ts_code}</p></div></div><dl><dt>市场</dt><dd>{stock.market || "—"}</dd><dt>行业</dt><dd>{stock.industry || "—"}</dd><dt>总市值</dt><dd>{fmtMarketValue(stock.total_mv)}</dd><dt>市盈率 TTM</dt><dd>{fmtNumber(stock.pe_ttm)}</dd><dt>市净率</dt><dd>{fmtNumber(stock.pb)}</dd><dt>ST 状态</dt><dd>{stock.is_st ? "是" : "否"}</dd></dl><div className="panel-dates"><b>数据表日期</b><span>行情 {formatDate(stock.as_of?.quote)}</span><span>估值 {formatDate(stock.as_of?.valuation)}</span><span>ST {formatDate(stock.as_of?.st)}</span><span>复权 {formatDate(stock.as_of?.adj_factor)}</span></div>{stock.warnings?.map(item => <p className="panel-warning" key={item}>{item}</p>)}</div>;
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
function UnavailablePanel({ tab }: { tab: RightTab }) { const text = tab === "交易" ? "交易接口未接入，本版本不提供下单。" : `${tab}能力尚未实现，本版本只保留禁用入口。`; return <PanelEmpty title={`${tab} · 暂不可用`} text={text} />; }
function PanelEmpty({ title, text }: { title: string; text: string }) { return <div className="right-placeholder"><CircleDot /><h3>{title}</h3><p>{text}</p></div>; }
function QuoteFact({ label, value }: { label: string; value: string }) { return <span><small>{label}</small><b>{value}</b></span>; }
function DrawingButton({ label, active, onClick, children }: { label: string; active: boolean; onClick: () => void; children: React.ReactNode }) { return <button title={label} aria-label={label} aria-pressed={active} className={active ? "active" : ""} onClick={onClick}>{children}</button>; }
function DisabledButton({ title, label, children }: { title: string; label?: string; children: React.ReactNode }) { return <button disabled title={title} aria-label={label || title}>{children}</button>; }
function periodLabel(value: string) { return ({ D: "日K", W: "周K", M: "月K", Q: "季K", Y: "年K" } as Record<string, string>)[value] || value; }
function signed(value?: number) { if (value == null || !Number.isFinite(value)) return "—"; return `${value >= 0 ? "+" : ""}${fmtNumber(value)}`; }
