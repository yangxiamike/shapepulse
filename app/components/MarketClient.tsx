"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bell,
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
import { MarketChart } from "./MarketChart";
import { api, fmtAmount, fmtMarketValue, fmtNumber } from "../lib/api";
import type { Bar, Stock } from "../lib/types";

const periods = [
  ["分时", "D"], ["5分", "D"], ["15分", "D"], ["30分", "D"], ["60分", "D"],
  ["日K", "D"], ["周K", "W"], ["月K", "M"], ["季K", "Q"], ["年K", "Y"],
] as const;

const defaultWatch = ["600519", "300750", "601318", "600036", "002594", "000333", "300760", "600900", "600276", "601899"];

export function MarketClient() {
  const [stock, setStock] = useState<Stock | null>(null);
  const [bars, setBars] = useState<Bar[]>([]);
  const [period, setPeriod] = useState("D");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Stock[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [activeResult, setActiveResult] = useState(0);
  const [rightTab, setRightTab] = useState("自选");
  const [watchlist, setWatchlist] = useState<Stock[]>([]);
  const [drawingMode, setDrawingMode] = useState<string | null>(null);
  const [drawings, setDrawings] = useState<Array<{ x1: number; y1: number; x2: number; y2: number }>>([]);
  const [status, setStatus] = useState("连接本地数据…");
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const code = new URLSearchParams(window.location.search).get("code") || "000001";
    void loadStock(code);
    void api.stateSummary().catch(() => ({ viewed: 0, saved: 0, pending: 0, history: 0, watchlist: [] })).then(state => {
      const codes = Array.from(new Set([...(state.watchlist || []), ...defaultWatch]));
      return Promise.all(codes.map(c => api.stock(c).catch(() => null)));
    }).then(items => setWatchlist(items.filter(Boolean) as Stock[]));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function loadStock(code: string, nextPeriod = period) {
    setStatus("正在读取本地行情…");
    try {
      const [detail, history] = await Promise.all([api.stock(code), api.bars(code, nextPeriod)]);
      setStock(detail); setBars(history.items); setPeriod(nextPeriod); setStatus(`行情已加载 · ${history.as_of?.daily || "本地快照"}`);
      setSearchOpen(false); setQuery("");
      window.history.replaceState(null, "", `/market?code=${detail.code}`);
      void api.updateState(detail.code, "viewed").catch(() => undefined);
    } catch (e) { setStatus(e instanceof Error ? e.message : "本地行情加载失败"); }
  }

  function onSearch(value: string) {
    setQuery(value); setSearchOpen(Boolean(value)); setActiveResult(0);
    if (searchTimer.current) clearTimeout(searchTimer.current);
    if (!value.trim()) { setResults([]); return; }
    searchTimer.current = setTimeout(() => void api.search(value).then(r => setResults(r.items.slice(0, 8))).catch(() => setResults([])), 120);
  }

  function searchKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") { e.preventDefault(); setActiveResult(i => Math.min(i + 1, results.length - 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setActiveResult(i => Math.max(i - 1, 0)); }
    if (e.key === "Enter" && results[activeResult]) { e.preventDefault(); void loadStock(results[activeResult].code); }
    if (e.key === "Escape") setSearchOpen(false);
  }

  async function toggleWatchlist() {
    if (!stock) return;
    const exists = watchlist.some(s => s.code === stock.code);
    setWatchlist(exists ? watchlist.filter(s => s.code !== stock.code) : [stock, ...watchlist]);
    await api.updateState(stock.code, "watchlist", !exists).catch(() => undefined);
  }

  const latest = bars.at(-1);
  const maLegend = useMemo(() => latest ? [latest.ma5, latest.ma10, latest.ma20] : [], [latest]);

  return (
    <div className="app-shell market-shell">
      <AppSidebar active="market" />
      <main className="market-main">
        <header className="market-topbar">
          <div className="market-search-wrap">
            <Search className="search-left" />
            <input value={query} onFocus={() => query && setSearchOpen(true)} onChange={e => onSearch(e.target.value)} onKeyDown={searchKeyDown} placeholder="搜索股票名称 / 代码 / 拼音首字母" aria-label="搜索股票" />
            {query ? <button onClick={() => onSearch("")} aria-label="清空搜索"><X /></button> : <Search className="search-right" />}
            {searchOpen && <div className="search-results" role="listbox">
              {results.length ? results.map((item, index) => <button key={item.code} className={index === activeResult ? "active" : ""} onMouseEnter={() => setActiveResult(index)} onClick={() => void loadStock(item.code)}><span>{item.code}</span><b>{item.name}</b><em>{item.initials}</em></button>) : <p>没有匹配的本地股票</p>}
            </div>}
          </div>
          <div className="layout-tools"><button><Grid2X2 /><span>多图布局</span><ChevronDown /></button><button><span>未命名布局</span><ChevronDown /></button><button aria-label="布局设置"><Settings2 /></button><button aria-label="菜单"><Menu /></button></div>
        </header>

        <section className="quote-summary">
          {stock ? <>
            <div className="quote-main"><div className="quote-title"><h1>{stock.name}</h1><span>{stock.code}</span><em>{stock.market || "A股"}</em><em>{stock.industry || "本地数据"}</em></div><div className={`quote-price ${stock.pct_chg >= 0 ? "up" : "down"}`}><b>{fmtNumber(stock.close)}</b><span>CNY</span><p>{stock.pct_chg >= 0 ? "+" : ""}{fmtNumber(stock.change)}　{stock.pct_chg >= 0 ? "+" : ""}{fmtNumber(stock.pct_chg)}%</p></div></div>
            <div className="quote-facts"><QuoteFact label="今开" value={fmtNumber(stock.open)} /><QuoteFact label="最高" value={fmtNumber(stock.high)} /><QuoteFact label="最低" value={fmtNumber(stock.low)} /><QuoteFact label="昨收" value={fmtNumber(stock.pre_close)} /><QuoteFact label="成交额" value={fmtAmount(stock.amount)} /><QuoteFact label="成交量" value={`${fmtNumber((stock.volume || 0) / 10000)}万手`} /><QuoteFact label="换手率" value={`${fmtNumber(stock.turnover_rate)}%`} /><QuoteFact label="市值" value={fmtMarketValue(stock.total_mv)} /></div>
          </> : <div className="quote-loading">{status}</div>}
        </section>

        <section className="chart-workspace">
          <div className="chart-toolbar">
            <div className="period-tabs">{periods.map(([label, value]) => { const unavailable = ["分时","5分","15分","30分","60分"].includes(label); return <button key={label} disabled={unavailable} title={unavailable ? "本地库当前仅有日线；分钟周期已保留入口" : label} className={period === value && label === ({D:"日K",W:"周K",M:"月K",Q:"季K",Y:"年K"} as Record<string,string>)[period] ? "active" : ""} onClick={() => stock && void loadStock(stock.code, value)}>{label}</button>; })}</div>
            <div className="chart-actions"><button>指标 <ChevronDown /></button><i /><button>对比</button><i /><button><Bell />预警</button><i /><button><RotateCcw />回放</button><i /><button aria-label="截图"><Camera /></button><button aria-label="全屏"><Fullscreen /></button></div>
            <div className="ma-legend"><span className="ma5">MA5　{fmtNumber(maLegend[0] || 0)}</span><span className="ma10">MA10　{fmtNumber(maLegend[1] || 0)}</span><span className="ma20">MA20　{fmtNumber(maLegend[2] || 0)}</span></div>
          </div>
          <div className="drawing-toolbar">
            <DrawingButton label="光标" active={!drawingMode} onClick={() => setDrawingMode(null)}><MousePointer2 /></DrawingButton>
            <DrawingButton label="趋势线" active={drawingMode === "line"} onClick={() => setDrawingMode(drawingMode === "line" ? null : "line")}><Pencil /></DrawingButton>
            <DrawingButton label="十字线" active={drawingMode === "cross"} onClick={() => setDrawingMode(drawingMode === "cross" ? null : "cross")}><Crosshair /></DrawingButton>
            <DrawingButton label="水平线" active={drawingMode === "horizontal"} onClick={() => setDrawingMode(drawingMode === "horizontal" ? null : "horizontal")}><LineChart /></DrawingButton>
            <DrawingButton label="文本" active={drawingMode === "text"} onClick={() => setDrawingMode(drawingMode === "text" ? null : "text")}><Type /></DrawingButton>
            <DrawingButton label="测量" active={drawingMode === "measure"} onClick={() => setDrawingMode(drawingMode === "measure" ? null : "measure")}><Ruler /></DrawingButton>
            <DrawingButton label="缩放" active={false} onClick={() => undefined}><ZoomIn /></DrawingButton>
            <DrawingButton label="清除画线" active={false} onClick={() => setDrawings([])}><Trash2 /></DrawingButton>
          </div>
          <div className="chart-stage"><MarketChart bars={bars} drawingMode={drawingMode} drawings={drawings} onDrawComplete={line => { setDrawings(v => [...v, line]); setDrawingMode(null); }} /></div>
          <div className="range-toolbar"><span>1天</span><span>5天</span><span>1个月</span><span>3个月</span><span>6个月</span><span>YTD</span><span>1年</span><span>3年</span><span>5年</span><span className="active">全部</span><b>2015年至今　<CalendarTiny /></b></div>
        </section>
      </main>

      <aside className="market-rightbar">
        <div className="right-tabs">{["自选","详情","指标","因子","交易"].map(tab => <button className={rightTab === tab ? "active" : ""} onClick={() => setRightTab(tab)} key={tab}>{tab}</button>)}</div>
        {rightTab === "自选" ? <>
          <div className="watch-header"><span>名称/代码</span><span>最新价</span><span>涨跌幅</span></div>
          <div className="watch-list">{watchlist.map(item => <button key={item.code} className={item.code === stock?.code ? "active" : ""} onClick={() => void loadStock(item.code)}><span><b>{item.name}</b><em>{item.code}</em></span><strong>{fmtNumber(item.close)}</strong><i className={item.pct_chg >= 0 ? "up" : "down"}>{item.pct_chg >= 0 ? "+" : ""}{fmtNumber(item.pct_chg)}%</i></button>)}</div>
          <button className="add-watch" onClick={() => void toggleWatchlist()}><Plus />{watchlist.some(s => s.code === stock?.code) ? "移出自选" : "添加自选"}</button>
        </> : rightTab === "详情" ? <div className="right-placeholder"><Layers3 /><h3>{stock?.name || "股票详情"}</h3><p>展示本地基础资料、估值和行情摘要。</p></div> : <div className="right-placeholder"><CircleDot /><h3>{rightTab} · 预留区域</h3><p>{rightTab === "交易" ? "交易能力尚未接入，本版本不提供下单。" : "接口边界已保留，当前版本未接入。"}</p></div>}
      </aside>

      <footer className="market-statusbar"><span><i className={stock ? "connected" : ""} />{stock ? "已连接" : "未连接"}</span><span><Clock3 />{new Date().toLocaleTimeString("zh-CN", { hour12: false })}</span><span className="status-center">本地数据　{status}</span><span><CircleDot />日线快照</span><span>CN</span></footer>
    </div>
  );
}

function QuoteFact({ label, value }: { label: string; value: string }) { return <span><small>{label}</small><b>{value}</b></span>; }
function DrawingButton({ label, active, onClick, children }: { label: string; active: boolean; onClick: () => void; children: React.ReactNode }) { return <button title={label} aria-label={label} className={active ? "active" : ""} onClick={onClick}>{children}</button>; }
function CalendarTiny() { return <span className="calendar-tiny">▣</span>; }
