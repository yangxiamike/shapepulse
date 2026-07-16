"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Bookmark,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Clock3,
  Database,
  Eye,
  ExternalLink,
  LoaderCircle,
  Play,
  RefreshCw,
  Star,
  TrendingUp,
  TriangleAlert,
  X,
} from "lucide-react";
import { AppSidebar } from "./AppSidebar";
import { MarketChart } from "./MarketChart";
import { MiniSparkline } from "./MiniSparkline";
import {
  api,
  fmtAmount,
  fmtMarketValue,
  fmtMetric,
  fmtNumber,
  formatDate,
  metricLabel,
} from "../lib/api";
import type {
  PatternKey,
  ScreenProgress,
  ScreenResponse,
  StateSnapshot,
  Stock,
} from "../lib/types";

type ViewKey = "combined" | PatternKey;

const patternMeta: Record<PatternKey, { name: string; color: "mint" | "blue" | "lime" }> = {
  breakout: { name: "突破启动", color: "mint" },
  pullback: { name: "上升趋势回调", color: "blue" },
  range_bounce: { name: "区间下沿反弹", color: "lime" },
};

const emptyState: StateSnapshot = {
  viewed: [], saved: [], pending: [], watchlist: [],
  history: { runs: [], recommendations: [] },
};

export function BoardClient() {
  const [board, setBoard] = useState("mainboard");
  const [mvOperator, setMvOperator] = useState("gte");
  const [mvValue, setMvValue] = useState(50);
  const [excludeSt, setExcludeSt] = useState(true);
  const [data, setData] = useState<ScreenResponse | null>(null);
  const [activeView, setActiveView] = useState<ViewKey>("combined");
  const [expanded, setExpanded] = useState(false);
  const [selected, setSelected] = useState<Stock | null>(null);
  const [state, setState] = useState<StateSnapshot>(emptyState);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [progress, setProgress] = useState<ScreenProgress | null>(null);
  const [drawer, setDrawer] = useState<"viewed" | "saved" | "pending" | "history" | null>(null);

  const query = useMemo(() => new URLSearchParams({
    board,
    mv_operator: mvOperator,
    mv_value: String(mvValue),
    exclude_st: String(excludeSt),
  }).toString(), [board, mvOperator, mvValue, excludeSt]);

  const activeItems = useMemo(() => {
    if (!data) return [];
    return activeView === "combined" ? data.items : data.categories[activeView];
  }, [activeView, data]);
  const visibleItems = expanded ? activeItems : activeItems.slice(0, 10);

  const hydrateStock = useCallback(async (base: Stock) => {
    try {
      const [{ item: detail }, history] = await Promise.all([
        api.stock(base.code),
        api.bars(base.code, "D", "6M"),
      ]);
      setSelected(current => current?.code === base.code ? {
        ...base,
        ...detail,
        pattern: base.pattern,
        pattern_name: base.pattern_name,
        score: base.score,
        reasons: base.reasons,
        metrics: base.metrics,
        rank: base.rank,
        category_rank: base.category_rank,
        bars: history.items,
      } : current);
    } catch (e) {
      setFeedback(e instanceof Error ? `候选详情暂未加载：${e.message}` : "候选详情暂未加载");
    }
  }, []);

  const chooseStock = useCallback(async (stock: Stock) => {
    setSelected(stock);
    void hydrateStock(stock);
    try { setState(await api.updateState(stock.code, "viewed")); } catch { /* selection stays usable */ }
  }, [hydrateStock]);

  const runScreen = useCallback(async () => {
    setLoading(true);
    setError("");
    setProgress({ stage: "准备本地筛选", completed: 0, total: 1 });
    setFeedback("正在读取本地数据库…");
    try {
      const response = await api.screen(query, setProgress);
      setData(response);
      setExpanded(false);
      const focusCode = new URLSearchParams(window.location.search).get("code");
      const all = [response.items, ...Object.values(response.categories)].flat();
      const first = (focusCode && all.find(item => item.code === focusCode)) || response.items[0] || response.categories.breakout[0] || null;
      setSelected(first);
      if (first) void hydrateStock(first);
      setFeedback(`完成 · ${response.filtered} 只进入股票池 · ${response.elapsed_ms?.toFixed(0)}ms${response.cache_hit ? " · 已命中缓存" : ""}`);
      setState(await api.state().catch(() => emptyState));
    } catch (e) {
      setError(e instanceof Error ? e.message : "无法连接本地数据服务");
      setFeedback("");
    } finally {
      setLoading(false);
      setProgress(null);
    }
  }, [hydrateStock, query]);

  useEffect(() => {
    const timer = window.setTimeout(() => void runScreen(), 0);
    return () => window.clearTimeout(timer);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function enterView(view: ViewKey) {
    setActiveView(view);
    setExpanded(false);
    const next = view === "combined" ? data?.items[0] : data?.categories[view][0];
    if (next) void chooseStock(next);
  }

  async function toggleState(kind: "saved" | "pending") {
    if (!selected) return;
    const enabled = !state[kind].some(item => item.code === selected.code);
    try {
      setState(await api.updateState(selected.code, kind, enabled));
      setFeedback(`${selected.name} 已${enabled ? "加入" : "移出"}${kind === "saved" ? "已保存" : "待判断"}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "状态保存失败");
    }
  }

  const asOf = data?.as_of.daily || "";
  const saved = Boolean(selected && state.saved.some(item => item.code === selected.code));
  const pending = Boolean(selected && state.pending.some(item => item.code === selected.code));
  const title = activeView === "combined" ? "综合榜" : patternMeta[activeView].name;

  return (
    <div className="app-shell board-shell">
      <AppSidebar active="screen" />
      <main className="board-main">
        <header className="filter-toolbar">
          <div className="filter-control date-control"><CalendarDays /><span>{formatDate(asOf)}</span></div>
          <div className="filter-control status-control"><Database /><div><b>{data ? "本地数据就绪" : "连接本地库"}</b><small>仅使用 zer0share 快照</small></div></div>
          <label className="filter-control select-control"><select value={board} onChange={e => setBoard(e.target.value)} aria-label="板块"><option value="mainboard">沪深主板</option><option value="chinext">创业板</option><option value="star">科创板</option></select><ChevronDown /></label>
          <label className="filter-control market-value-control"><select value={mvOperator} onChange={e => setMvOperator(e.target.value)} aria-label="市值关系"><option value="gte">市值 ≥</option><option value="lte">市值 ≤</option></select><input type="number" value={mvValue} min="1" onChange={e => setMvValue(Number(e.target.value))} aria-label="市值亿元" /><span>亿</span></label>
          <button className={`filter-control toggle-control ${excludeSt ? "on" : ""}`} onClick={() => setExcludeSt(value => !value)} aria-pressed={excludeSt}><span>剔除 ST</span><i><b /></i></button>
          <div className="filter-control fixed-top">每类 TOP 50</div>
          <button className="run-button" onClick={() => void runScreen()} disabled={loading}>{loading ? <LoaderCircle className="spin" /> : <Play />}<span>{loading ? "筛选中" : "运行筛选"}</span></button>
        </header>

        {loading && progress && <div className="screen-progress" role="status" aria-live="polite"><span>{progress.stage}</span><i><b style={{ width: `${Math.max(4, progress.completed / progress.total * 100)}%` }} /></i><em>{progress.completed}/{progress.total}</em></div>}

        <section className="board-overview">
          <button className={`metric-card top-card ${activeView === "combined" ? "active" : ""}`} onClick={() => enterView("combined")}>
            <span>综合榜</span><h1>TOP 50</h1>
            <div className="progress-ring" style={{ "--progress": `${Math.min(100, ((data?.items.length || 0) / 50) * 100)}%` } as React.CSSProperties}><b>{data?.items.length || 0}</b><span>只</span></div>
            <p>股票池 <b>{data?.filtered || 0}</b> 只</p>
          </button>
          <div className="metric-card patterns-card">
            {(Object.keys(patternMeta) as PatternKey[]).map(key => {
              const meta = patternMeta[key];
              const delta = data?.category_deltas[key];
              return <button className={`pattern-metric ${activeView === key ? "active" : ""}`} key={key} onClick={() => enterView(key)}>
                <span className={`pattern-icon ${meta.color}`}><TrendingUp /></span>
                <span className="pattern-copy"><span>{meta.name}</span><strong>{data?.counts[key] || 0}</strong></span>
                <span className={`mini-bars ${meta.color}`}>{[5,9,7,12,8,10,6,4,7,3,2].map((h,i) => <i key={i} style={{ height: `${h * 3}px` }} />)}</span>
                <small>较前一筛选日 {delta == null ? <em className="muted">暂无对比</em> : <em className={delta >= 0 ? "up" : "down"}>{delta >= 0 ? "+" : ""}{delta}</em>}</small>
              </button>;
            })}
          </div>
          <article className="metric-card stock-snapshot">
            {selected ? <>
              <div className="snapshot-title"><span>{selected.code}</span><b>{selected.name}</b><button className={saved ? "active" : ""} onClick={() => void toggleState("saved")} aria-label={saved ? "取消保存" : "保存"} aria-pressed={saved}><Star fill={saved ? "currentColor" : "none"} /></button></div>
              <div className={`snapshot-price ${selected.pct_chg >= 0 ? "up" : "down"}`}><strong>{fmtNumber(selected.close)}</strong><span>{signed(selected.change)}　{signed(selected.pct_chg)}%</span></div>
              <div className="snapshot-grid"><span>最高<b>{fmtNumber(selected.high)}</b></span><span>最低<b>{fmtNumber(selected.low)}</b></span><span>今开<b>{fmtNumber(selected.open)}</b></span><span>换手<b>{fmtNumber(selected.turnover_rate)}%</b></span><span>成交额<b>{fmtAmount(selected.amount)}</b></span></div>
            </> : <EmptyState compact text="暂无候选股票" />}
          </article>
        </section>

        {data?.warnings.length ? <section className="data-warning" aria-label="数据口径警告"><TriangleAlert /> <div>{data.warnings.map(item => <span key={item}>{item}</span>)}</div><DatePills dates={data.as_of} /></section> : data && <section className="date-strip"><DatePills dates={data.as_of} /></section>}

        <section className="board-workspace">
          <article className={`candidate-card ${expanded ? "expanded" : ""}`}>
            <div className="section-heading"><div><h2>{title}</h2><span>{feedback}</span></div><button onClick={() => void runScreen()} aria-label="刷新"><RefreshCw /></button></div>
            {error ? <ErrorState message={error} onRetry={runScreen} /> : <div className="table-wrap">
              <table className="candidate-table">
                <thead><tr><th>排名</th><th>股票代码</th><th>股票名称</th><th>所属板块</th><th>形态</th><th>匹配理由</th><th>匹配度</th><th>总市值</th><th>涨跌幅</th><th>5日趋势</th></tr></thead>
                <tbody>{visibleItems.map((stock, index) => {
                  const meta = patternMeta[stock.pattern || "breakout"];
                  const rank = activeView === "combined" ? stock.rank : stock.category_rank || stock.rank;
                  return <tr key={`${stock.code}-${stock.pattern}`} className={selected?.code === stock.code && selected?.pattern === stock.pattern ? "selected" : ""} onClick={() => void chooseStock(stock)} tabIndex={0} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); void chooseStock(stock); } }}>
                    <td><span className={(rank || index + 1) <= 3 ? "rank top-rank" : "rank"}>{rank || index + 1}</span></td>
                    <td className="code-cell">{stock.code}</td><td className="name-cell">{stock.name}</td><td>{stock.industry || stock.market || "—"}</td>
                    <td><span className={`pattern-tag ${meta.color}`}>{stock.pattern_name || meta.name}</span></td>
                    <td className="reason-cell" title={(stock.reasons || []).join("；")}>{stock.reasons?.[0] || "已计算，理由待复核"}</td>
                    <td><div className="score-cell"><b>{Math.round(stock.score || 0)}</b><i><span style={{ width: `${stock.score || 0}%` }} /></i></div></td>
                    <td>{fmtMarketValue(stock.total_mv)}</td><td className={stock.pct_chg >= 0 ? "up" : "down"}>{signed(stock.pct_chg)}%</td>
                    <td><MiniSparkline values={stock.sparkline} tone={meta.color} /></td>
                  </tr>;
                })}</tbody>
              </table>
              {!activeItems.length && !loading && <EmptyState text="当前条件暂无候选，请调整市值或板块后重新筛选" />}
            </div>}
            {activeItems.length > 10 && <button className="view-all-button" onClick={() => setExpanded(value => !value)} aria-expanded={expanded}>{expanded ? "收起列表" : `查看全部 ${activeItems.length} 只`} <ChevronDown className={expanded ? "rotate" : ""} /></button>}
          </article>
          <article className="detail-card">
            {selected ? <>
              <div className="detail-chart-head"><b>日 K · 近 5 个月</b><span className="ma ma5">MA5</span><span className="ma ma10">MA10</span><span className="ma ma20">MA20</span></div>
              <div className="detail-chart"><MarketChart bars={selected.bars || []} compact /></div>
              <div className="pattern-reading">
                <div className="reading-head"><h3>形态解读</h3><span className={`pattern-tag ${patternMeta[selected.pattern || "breakout"].color}`}>{selected.pattern_name || patternMeta[selected.pattern || "breakout"].name}</span></div>
                {selected.reasons?.length ? <ul>{selected.reasons.slice(0, 4).map(reason => <li key={reason}><Check />{reason}</li>)}</ul> : <p className="reading-empty">已计算，但没有可展示的匹配理由。</p>}
                {selected.metrics && <div className="metric-facts">{Object.entries(selected.metrics).slice(0, 4).map(([key, value]) => <span key={key}><small>{metricLabel(key)}</small><b>{fmtMetric(key, value)}</b></span>)}</div>}
                <div className="detail-actions"><button className={`secondary-action ${pending ? "active" : ""}`} onClick={() => void toggleState("pending")}><CircleHelp />{pending ? "移出待判断" : "待判断"}</button><Link className="open-market-button" href={`/market?code=${selected.code}`}>打开行情 <ExternalLink /></Link></div>
              </div>
            </> : <EmptyState text="选择一只候选股票查看详情" />}
          </article>
        </section>

        <section className="state-cards">
          <StateCard tone="mint" icon={<Eye />} label="已查看" count={state.viewed.length} onClick={() => setDrawer("viewed")} />
          <StateCard tone="blue" icon={<Bookmark />} label="已保存" count={state.saved.length} onClick={() => setDrawer("saved")} />
          <StateCard tone="yellow" icon={<CircleHelp />} label="待判断" count={state.pending.length} onClick={() => setDrawer("pending")} />
          <StateCard tone="plain" icon={<Clock3 />} label="历史记录" count={state.history.runs.length} onClick={() => setDrawer("history")} />
        </section>
      </main>
      {drawer && <StateDrawer kind={drawer} state={state} onClose={() => setDrawer(null)} onChoose={async code => {
        const { item } = await api.stock(code);
        setDrawer(null);
        await chooseStock(item);
      }} />}
    </div>
  );
}

function DatePills({ dates }: { dates: ScreenResponse["as_of"] }) {
  return <div className="date-pills"><span>行情 {formatDate(dates.daily)}</span><span>估值 {formatDate(dates.valuation)}</span><span>ST {formatDate(dates.st)}</span><span>复权 {formatDate(dates.adj_factor)}</span></div>;
}

function StateCard({ tone, icon, label, count, onClick }: { tone: string; icon: React.ReactNode; label: string; count: number; onClick: () => void }) {
  return <button className={`state-card ${tone}`} onClick={onClick}><span className="state-icon">{icon}</span><span><small>{label}</small><b>{count}</b></span><ChevronRight className="state-arrow" /></button>;
}

function StateDrawer({ kind, state, onClose, onChoose }: { kind: "viewed" | "saved" | "pending" | "history"; state: StateSnapshot; onClose: () => void; onChoose: (code: string) => void }) {
  const items = kind === "history" ? state.history.recommendations : state[kind];
  return <div className="drawer-backdrop" onClick={onClose}><aside className="state-drawer" onClick={e => e.stopPropagation()} aria-label={drawerLabel(kind)}><button className="drawer-close" onClick={onClose} aria-label="关闭"><X /></button><h2>{drawerLabel(kind)}</h2><p>记录只保存在本项目的本地数据库中。</p><div className="drawer-list">{items.length ? items.slice(0, 100).map((item, index) => {
    const code = item.code;
    const label = "category_label" in item ? item.category_label : item.market || "本地记录";
    return <button key={`${code}-${index}`} onClick={() => onChoose(code)}><span><b>{item.name || code}</b><small>{code} · {label}</small></span><ChevronRight /></button>;
  }) : <EmptyState compact text="暂无记录" />}</div></aside></div>;
}

function EmptyState({ text, compact = false }: { text: string; compact?: boolean }) { return <div className={`empty-state ${compact ? "compact" : ""}`}><Database /><span>{text}</span></div>; }
function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) { return <div className="error-state"><Database /><h3>本地数据暂不可用</h3><p>{message}</p><button onClick={onRetry}>重新连接</button></div>; }
function drawerLabel(key: string) { return ({ viewed: "已查看", saved: "已保存", pending: "待判断", history: "历史筛选记录" } as Record<string, string>)[key] || key; }
function signed(value?: number) { if (value == null || !Number.isFinite(value)) return "—"; return `${value >= 0 ? "+" : ""}${fmtNumber(value)}`; }
