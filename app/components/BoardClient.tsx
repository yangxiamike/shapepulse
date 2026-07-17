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
  Save,
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
  SavedScreenPage,
  SavedScreenSnapshot,
  ScreenFilters,
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
  const [industries, setIndustries] = useState<string[]>([]);
  const [industryOptions, setIndustryOptions] = useState<string[]>([]);
  const [industryOpen, setIndustryOpen] = useState(false);
  const [mvMin, setMvMin] = useState("");
  const [mvMax, setMvMax] = useState("");
  const [excludeSt, setExcludeSt] = useState(true);
  const [topK, setTopK] = useState(50);
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
  const [snapshotDetail, setSnapshotDetail] = useState<SavedScreenSnapshot | null>(null);
  const [savingSnapshot, setSavingSnapshot] = useState(false);
  const [historyPage, setHistoryPage] = useState<SavedScreenPage | null>(null);

  const filters = useMemo<ScreenFilters>(() => ({
    board,
    industries,
    market_cap_min_yi: mvMin === "" ? null : Number(mvMin),
    market_cap_max_yi: mvMax === "" ? null : Number(mvMax),
    exclude_st: excludeSt,
    top_k: topK,
    mode: "per_category",
  }), [board, excludeSt, industries, mvMax, mvMin, topK]);

  const filterError = useMemo(() => {
    if (!Number.isInteger(topK) || topK <= 0) return "Top K 必须是正整数";
    if (filters.market_cap_min_yi != null && (!Number.isFinite(filters.market_cap_min_yi) || filters.market_cap_min_yi < 0)) return "市值下限不能为负数";
    if (filters.market_cap_max_yi != null && (!Number.isFinite(filters.market_cap_max_yi) || filters.market_cap_max_yi < 0)) return "市值上限不能为负数";
    if (filters.market_cap_min_yi != null && filters.market_cap_max_yi != null && filters.market_cap_min_yi > filters.market_cap_max_yi) return "市值下限不能大于上限";
    return "";
  }, [filters, topK]);

  const activeItems = useMemo(() => {
    if (!data) return [];
    const items = activeView === "combined" ? data.items : data.categories[activeView];
    return items.slice(0, Math.min(topK, items.length));
  }, [activeView, data, topK]);
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
    if (filterError) { setError(filterError); setFeedback(""); return; }
    setLoading(true);
    setError("");
    setProgress({ stage: "准备本地筛选", completed: 0, total: 1 });
    setFeedback("正在读取本地数据库…");
    try {
      const response = await api.screen(filters, setProgress);
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
  }, [filterError, filters, hydrateStock]);

  useEffect(() => {
    const timer = window.setTimeout(() => void runScreen(), 0);
    void api.industries().then(result => setIndustryOptions(result.items)).catch(() => setIndustryOptions([]));
    return () => window.clearTimeout(timer);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const saveCurrentSnapshot = useCallback(async () => {
    if (!data || savingSnapshot) return;
    setSavingSnapshot(true); setError("");
    try {
      const savedRun = await api.saveScreenSnapshot(data, filters);
      setFeedback(`已保存本次筛选 · ${savedRun.result_count} 只 · ${new Date(savedRun.created_at).toLocaleString("zh-CN")}`);
      setState(await api.state());
    } catch (e) { setError(e instanceof Error ? e.message : "筛选快照保存失败"); }
    finally { setSavingSnapshot(false); }
  }, [data, filters, savingSnapshot]);

  const openHistory = useCallback(async (page = 1) => {
    setDrawer("history"); setSnapshotDetail(null);
    try { setHistoryPage(await api.screenSnapshots(page, 20)); }
    catch (e) { setError(e instanceof Error ? e.message : "历史快照加载失败"); }
  }, []);

  const applySnapshotFilters = useCallback((run: SavedScreenSnapshot) => {
    const next = run.filters || {};
    const boardValue = String(next.board || "mainboard");
    const boardMap: Record<string, string> = { 主板: "mainboard", 创业板: "chinext", 科创板: "star" };
    setBoard(boardMap[boardValue] || boardValue);
    setIndustries(Array.isArray(next.industries) ? next.industries.map(String) : []);
    setMvMin(next.market_cap_min_yi == null ? "" : String(next.market_cap_min_yi));
    setMvMax(next.market_cap_max_yi == null ? "" : String(next.market_cap_max_yi));
    setExcludeSt(next.exclude_st !== false);
    const restoredTopK = Number(next.top_k || run.top_k || 50);
    setTopK(Number.isInteger(restoredTopK) && restoredTopK > 0 ? restoredTopK : 50);
    if (run.results?.length) {
      const categories = { breakout: [], pullback: [], range_bounce: [] } as ScreenResponse["categories"];
      run.results.forEach(item => { if (item.pattern) categories[item.pattern].push(item); });
      setData(current => ({
        ...(current || { total: run.result_count, filtered: run.result_count, scored: run.result_count, as_of: {}, warnings: [], timings: {}, cache_hit: true, counts: { breakout: 0, pullback: 0, range_bounce: 0 }, category_deltas: { breakout: null, pullback: null, range_bounce: null } }),
        items: run.results || [], categories,
        counts: { breakout: categories.breakout.length, pullback: categories.pullback.length, range_bounce: categories.range_bounce.length },
        filters: next,
      }));
      setSelected(run.results[0] || null);
    }
    setDrawer(null); setSnapshotDetail(null);
    setFeedback("已恢复该次筛选条件，可直接运行或查看保存名单");
  }, []);

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
          <div className="industry-filter">
            <button className="filter-control industry-trigger" type="button" aria-expanded={industryOpen} onClick={() => setIndustryOpen(value => !value)}><span>{industries.length ? `行业 ${industries.length} 项` : "全部行业"}</span><ChevronDown /></button>
            {industryOpen && <div className="industry-popover" data-testid="industry-filter"><div><b>行业多选</b><button type="button" onClick={() => setIndustries([])}>清空</button></div><div className="industry-options">{industryOptions.map(item => <label key={item}><input type="checkbox" checked={industries.includes(item)} onChange={e => setIndustries(current => e.target.checked ? [...current, item] : current.filter(value => value !== item))} /><span>{item}</span></label>)}</div></div>}
          </div>
          <label className="filter-control market-range-control market-value-control"><span>市值</span><input type="number" min="0" value={mvMin} placeholder="下限" onChange={e => setMvMin(e.target.value)} aria-label="市值下限亿元" /><i>—</i><input type="number" min="0" value={mvMax} placeholder="上限" onChange={e => setMvMax(e.target.value)} aria-label="市值上限亿元" /><em>亿元</em></label>
          <button className={`filter-control toggle-control ${excludeSt ? "on" : ""}`} onClick={() => setExcludeSt(value => !value)} aria-pressed={excludeSt}><span>剔除 ST</span><i><b /></i></button>
          <label className="filter-control top-k-control"><span>每类 Top</span><input type="number" min="1" step="1" value={topK} onChange={e => setTopK(Number(e.target.value))} aria-label="Top K" /></label>
          <button className="save-screen-button" type="button" onClick={() => void saveCurrentSnapshot()} disabled={!data || loading || savingSnapshot}><Save />{savingSnapshot ? "保存中" : "保存本次筛选"}</button>
          <button className="run-button" onClick={() => void runScreen()} disabled={loading || Boolean(filterError)} title={filterError || undefined}>{loading ? <LoaderCircle className="spin" /> : <Play />}<span>{loading ? "筛选中" : "运行筛选"}</span></button>
        </header>

        {filterError && <div className="filter-error" role="alert">{filterError}</div>}

        {loading && progress && <div className="screen-progress" role="status" aria-live="polite"><span>{progress.stage}</span><i><b style={{ width: `${Math.max(4, progress.completed / progress.total * 100)}%` }} /></i><em>{progress.completed}/{progress.total}</em></div>}

        <section className="board-overview">
          <button className={`metric-card top-card ${activeView === "combined" ? "active" : ""}`} onClick={() => enterView("combined")}>
            <span>综合榜</span><h1>TOP {topK}</h1>
            <div className="progress-ring" style={{ "--progress": `${Math.min(100, ((data?.items.length || 0) / Math.max(1, topK)) * 100)}%` } as React.CSSProperties}><b>{Math.min(data?.items.length || 0, topK)}</b><span>只</span></div>
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
                <thead><tr><th>排名</th><th>股票代码</th><th>股票名称</th><th>所属行业</th><th>形态</th><th>匹配理由</th><th>匹配度</th><th>总市值</th><th>涨跌幅</th><th>5日趋势</th></tr></thead>
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
              <div className="detail-chart"><MarketChart bars={selected.bars || []} visibleCount={110} compact /></div>
              <div className="pattern-reading">
                <div className="reading-head"><h3>形态解读</h3><span className={`pattern-tag ${patternMeta[selected.pattern || "breakout"].color}`}>{selected.pattern_name || patternMeta[selected.pattern || "breakout"].name}</span></div>
                {selected.reasons?.length ? <ul>{selected.reasons.slice(0, 4).map(reason => <li key={reason}><Check />{reason}</li>)}</ul> : <p className="reading-empty">已计算，但没有可展示的匹配理由。</p>}
                {selected.metrics && <div className="metric-facts">{Object.entries(selected.metrics).slice(0, 4).map(([key, value]) => <span key={key}><small>{metricLabel(key)}</small><b>{fmtMetric(key, value)}</b></span>)}</div>}
                <div className="detail-actions"><button className={`secondary-action ${pending ? "active" : ""}`} onClick={() => void toggleState("pending")}><CircleHelp />{pending ? "移出待判断" : "待判断"}</button><Link className="open-market-button" href={`/market?code=${selected.code}${selected.pattern ? `&category=${selected.pattern}` : ""}`}>打开行情 <ExternalLink /></Link></div>
              </div>
            </> : <EmptyState text="选择一只候选股票查看详情" />}
          </article>
        </section>

        <section className="state-cards">
          <StateCard tone="mint" icon={<Eye />} label="已查看" count={state.viewed.length} onClick={() => setDrawer("viewed")} />
          <StateCard tone="blue" icon={<Bookmark />} label="已保存" count={state.saved.length} onClick={() => setDrawer("saved")} />
          <StateCard tone="yellow" icon={<CircleHelp />} label="待判断" count={state.pending.length} onClick={() => setDrawer("pending")} />
          <StateCard tone="plain" icon={<Clock3 />} label="历史记录" count={historyPage?.total ?? state.history.runs.length} onClick={() => void openHistory()} />
        </section>
      </main>
      {drawer && <StateDrawer kind={drawer} state={state} historyPage={historyPage} snapshotDetail={snapshotDetail} onClose={() => { setDrawer(null); setSnapshotDetail(null); }} onChoose={async code => {
        const { item } = await api.stock(code);
        setDrawer(null);
        await chooseStock(item);
      }} onOpenSnapshot={async runId => setSnapshotDetail(runId ? await api.screenSnapshot(runId) : null)} onHistoryPage={page => void openHistory(page)} onApplySnapshot={applySnapshotFilters} />}
    </div>
  );
}

function DatePills({ dates }: { dates: ScreenResponse["as_of"] }) {
  return <div className="date-pills"><span>行情 {formatDate(dates.daily)}</span><span>估值 {formatDate(dates.valuation)}</span><span>ST {formatDate(dates.st)}</span><span>复权 {formatDate(dates.adj_factor)}</span></div>;
}

function StateCard({ tone, icon, label, count, onClick }: { tone: string; icon: React.ReactNode; label: string; count: number; onClick: () => void }) {
  return <button className={`state-card ${tone}`} onClick={onClick}><span className="state-icon">{icon}</span><span><small>{label}</small><b>{count}</b></span><ChevronRight className="state-arrow" /></button>;
}

function StateDrawer({ kind, state, historyPage, snapshotDetail, onClose, onChoose, onOpenSnapshot, onHistoryPage, onApplySnapshot }: {
  kind: "viewed" | "saved" | "pending" | "history";
  state: StateSnapshot;
  historyPage: SavedScreenPage | null;
  snapshotDetail: SavedScreenSnapshot | null;
  onClose: () => void;
  onChoose: (code: string) => void;
  onOpenSnapshot: (runId: string) => void;
  onHistoryPage: (page: number) => void;
  onApplySnapshot: (run: SavedScreenSnapshot) => void;
}) {
  if (kind === "history") { const runs = historyPage?.items || state.history.runs; return <div className="drawer-backdrop" onClick={onClose}><aside className="state-drawer history-drawer" onClick={e => e.stopPropagation()} aria-label={drawerLabel(kind)}><button className="drawer-close" onClick={onClose} aria-label="关闭"><X /></button><h2>{snapshotDetail ? "筛选快照详情" : drawerLabel(kind)}</h2><p>每条记录代表用户主动保存的一次完整筛选。</p>{snapshotDetail ? <div className="snapshot-detail" data-run-id={snapshotDetail.run_id}><button className="drawer-back" onClick={() => onOpenSnapshot("")}>返回历史</button><dl>{Object.entries(snapshotDetail.filters || {}).map(([key, value]) => <span key={key}><dt>{filterLabel(key)}</dt><dd>{formatFilterValue(value)}</dd></span>)}</dl><button className="reuse-filter-button" onClick={() => onApplySnapshot(snapshotDetail)}>恢复并复用条件</button><div className="snapshot-results">{(snapshotDetail.results || []).map((item, index) => <button key={`${item.code}-${item.pattern}-${index}`} onClick={() => onChoose(item.code)}><b>{item.rank || index + 1}</b><span><strong>{item.name || item.code}</strong><small>{item.code} · {item.pattern_name || patternMeta[item.pattern || "breakout"].name}</small></span><em>{Math.round(item.score || 0)}分</em></button>)}</div></div> : <><div className="drawer-list">{runs.length ? runs.map(run => <button key={run.run_id} data-run-id={run.run_id} onClick={() => onOpenSnapshot(run.run_id)}><span><b>{new Date(run.created_at).toLocaleString("zh-CN")}</b><small>{run.result_count} 只 · Top {run.top_k || String(run.filters?.top_k || 50)}</small></span><ChevronRight /></button>) : <EmptyState compact text="尚未主动保存筛选快照" />}</div>{historyPage && historyPage.total > historyPage.page_size && <div className="history-pagination"><button disabled={historyPage.page <= 1} onClick={() => onHistoryPage(historyPage.page - 1)}>上一页</button><span>{historyPage.page} / {Math.ceil(historyPage.total / historyPage.page_size)}</span><button disabled={historyPage.page * historyPage.page_size >= historyPage.total} onClick={() => onHistoryPage(historyPage.page + 1)}>下一页</button></div>}</>}</aside></div>; }
  const items = state[kind];
  return <div className="drawer-backdrop" onClick={onClose}><aside className="state-drawer" onClick={e => e.stopPropagation()} aria-label={drawerLabel(kind)}><button className="drawer-close" onClick={onClose} aria-label="关闭"><X /></button><h2>{drawerLabel(kind)}</h2><p>记录只保存在本项目的本地数据库中。</p><div className="drawer-list">{items.length ? items.slice(0, 100).map((item, index) => <button key={`${item.code}-${index}`} onClick={() => onChoose(item.code)}><span><b>{item.name || item.code}</b><small>{item.code} · {item.market || "本地记录"}</small></span><ChevronRight /></button>) : <EmptyState compact text="暂无记录" />}</div></aside></div>;
}

function filterLabel(key: string) { return ({ board: "板块", industries: "行业", market_cap_min_yi: "市值下限", market_cap_max_yi: "市值上限", exclude_st: "剔除 ST", top_k: "Top K", mode: "结果模式" } as Record<string, string>)[key] || key; }
function formatFilterValue(value: unknown) { if (Array.isArray(value)) return value.length ? value.join("、") : "不限"; if (value == null || value === "") return "不限"; if (typeof value === "boolean") return value ? "是" : "否"; return String(value); }

function EmptyState({ text, compact = false }: { text: string; compact?: boolean }) { return <div className={`empty-state ${compact ? "compact" : ""}`}><Database /><span>{text}</span></div>; }
function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) { return <div className="error-state"><Database /><h3>本地数据暂不可用</h3><p>{message}</p><button onClick={onRetry}>重新连接</button></div>; }
function drawerLabel(key: string) { return ({ viewed: "已查看", saved: "已保存", pending: "待判断", history: "历史筛选记录" } as Record<string, string>)[key] || key; }
function signed(value?: number) { if (value == null || !Number.isFinite(value)) return "—"; return `${value >= 0 ? "+" : ""}${fmtNumber(value)}`; }
