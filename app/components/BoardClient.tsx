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
} from "lucide-react";
import { AppSidebar } from "./AppSidebar";
import { MarketChart } from "./MarketChart";
import { MiniSparkline } from "./MiniSparkline";
import { api, fmtAmount, fmtMarketValue, fmtNumber } from "../lib/api";
import type { PatternKey, ScreenResponse, StateSummary, Stock } from "../lib/types";

const patternMeta: Record<PatternKey, { name: string; color: string; delta: string }> = {
  breakout: { name: "突破启动", color: "mint", delta: "+4" },
  pullback: { name: "上升趋势回调", color: "blue", delta: "+6" },
  range_rebound: { name: "区间下沿反弹", color: "lime", delta: "-2" },
};

const initialSummary: StateSummary = { viewed: 0, saved: 0, pending: 0, history: 0 };

export function BoardClient() {
  const [board, setBoard] = useState("mainboard");
  const [mvOperator, setMvOperator] = useState("gte");
  const [mvValue, setMvValue] = useState(50);
  const [excludeSt, setExcludeSt] = useState(true);
  const [topK, setTopK] = useState(50);
  const [data, setData] = useState<ScreenResponse | null>(null);
  const [selected, setSelected] = useState<Stock | null>(null);
  const [summary, setSummary] = useState<StateSummary>(initialSummary);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [drawer, setDrawer] = useState<keyof StateSummary | null>(null);

  const query = useMemo(() => new URLSearchParams({
    board,
    mv_operator: mvOperator,
    mv_value: String(mvValue),
    exclude_st: String(excludeSt),
    top_k: String(topK),
  }).toString(), [board, mvOperator, mvValue, excludeSt, topK]);

  const hydrateStock = useCallback(async (base: Stock) => {
    try {
      const [detail, history] = await Promise.all([api.stock(base.code), api.bars(base.code, "D", "20250101")]);
      setSelected(current => current?.code === base.code ? { ...base, ...detail, pattern: base.pattern, pattern_name: base.pattern_name, score: base.score, reasons: base.reasons, bars: history.items } : current);
    } catch { /* candidate row remains usable even when detail loading fails */ }
  }, []);

  const runScreen = useCallback(async () => {
    setLoading(true);
    setError("");
    setFeedback("正在读取本地数据库并计算形态…");
    try {
      const response = await api.screen(query);
      setData(response);
      setSelected(response.items[0] || null);
      if (response.items[0]) void hydrateStock(response.items[0]);
      setFeedback(`筛选完成：${response.filtered} 只进入股票池，展示 Top ${Math.min(topK, response.items.length)}`);
      const state = await api.stateSummary().catch(() => initialSummary);
      setSummary(state);
    } catch (e) {
      setError(e instanceof Error ? e.message : "无法连接本地数据服务");
      setFeedback("");
    } finally {
      setLoading(false);
    }
  }, [hydrateStock, query, topK]);

  useEffect(() => {
    const timer = window.setTimeout(() => void runScreen(), 0);
    return () => window.clearTimeout(timer);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function chooseStock(stock: Stock) {
    setSelected(stock);
    void hydrateStock(stock);
    try { setSummary(await api.updateState(stock.code, "viewed")); } catch { /* feedback is non-blocking */ }
  }

  async function toggleState(state: "saved" | "pending") {
    if (!selected) return;
    try {
      setSummary(await api.updateState(selected.code, state));
      setFeedback(state === "saved" ? `已保存 ${selected.name}` : `已将 ${selected.name} 加入待判断`);
    } catch (e) { setError(e instanceof Error ? e.message : "保存失败"); }
  }

  const counts = data?.counts || { breakout: 0, pullback: 0, range_rebound: 0 };
  const asOf = data?.as_of?.screen || data?.as_of?.daily || "—";

  return (
    <div className="app-shell board-shell">
      <AppSidebar active="screen" />
      <main className="board-main">
        <header className="filter-toolbar">
          <div className="filter-control date-control"><CalendarDays /><span>{formatDate(asOf)}</span><ChevronDown /></div>
          <div className="filter-control status-control"><Database /><div><b>{data ? "数据已更新" : "连接本地库"}</b><small>筛选口径 {formatDate(asOf)}</small></div></div>
          <label className="filter-control select-control"><select value={board} onChange={e => setBoard(e.target.value)} aria-label="板块"><option value="mainboard">沪深主板</option><option value="chinext">创业板</option><option value="star">科创板</option></select><ChevronDown /></label>
          <label className="filter-control market-value-control"><select value={mvOperator} onChange={e => setMvOperator(e.target.value)} aria-label="市值关系"><option value="gte">市值 ≥</option><option value="lte">市值 ≤</option></select><input type="number" value={mvValue} min="1" onChange={e => setMvValue(Number(e.target.value))} aria-label="市值亿元" /><span>亿</span></label>
          <button className={`filter-control toggle-control ${excludeSt ? "on" : ""}`} onClick={() => setExcludeSt(v => !v)}><span>剔除 ST</span><i><b /></i></button>
          <label className="filter-control select-control top-control"><select value={topK} onChange={e => setTopK(Number(e.target.value))} aria-label="Top K"><option value="20">TOP 20</option><option value="50">TOP 50</option><option value="100">TOP 100</option></select><ChevronDown /></label>
          <button className="run-button" onClick={() => void runScreen()} disabled={loading}>{loading ? <LoaderCircle className="spin" /> : <Play />}<span>{loading ? "筛选中" : "运行筛选"}</span></button>
        </header>

        <section className="board-overview">
          <article className="metric-card top-card">
            <h1>TOP {topK}</h1>
            <div className="progress-ring" style={{ "--progress": `${Math.min(100, ((data?.items.length || 0) / topK) * 100)}%` } as React.CSSProperties}><b>{data?.items.length || 0}</b><span>只</span></div>
            <p>股票池 <b>{data?.filtered || 0}</b> 只</p>
          </article>
          <article className="metric-card patterns-card">
            {(Object.keys(patternMeta) as PatternKey[]).map(key => (
              <div className="pattern-metric" key={key}>
                <div className={`pattern-icon ${patternMeta[key].color}`}><TrendingUp /></div>
                <div className="pattern-copy"><span>{patternMeta[key].name}</span><strong>{counts[key] || 0}</strong></div>
                <div className={`mini-bars ${patternMeta[key].color}`}>{[5,9,7,12,8,10,6,4,7,3,2].map((h,i) => <i key={i} style={{ height: `${h * 3}px` }} />)}</div>
                <small>较昨日 <em>{patternMeta[key].delta}</em></small>
              </div>
            ))}
          </article>
          <article className="metric-card stock-snapshot">
            {selected ? <>
              <div className="snapshot-title"><span>{selected.code}</span><b>{selected.name}</b><button onClick={() => void toggleState("saved")} aria-label="保存"><Star /></button></div>
              <div className={`snapshot-price ${selected.pct_chg >= 0 ? "up" : "down"}`}><strong>{fmtNumber(selected.close)}</strong><span>{selected.pct_chg >= 0 ? "+" : ""}{fmtNumber(selected.change)}　{selected.pct_chg >= 0 ? "+" : ""}{fmtNumber(selected.pct_chg)}%</span></div>
              <div className="snapshot-grid"><span>最高<b>{fmtNumber(selected.high)}</b></span><span>最低<b>{fmtNumber(selected.low)}</b></span><span>今开<b>{fmtNumber(selected.open)}</b></span><span>换手<b>{fmtNumber(selected.turnover_rate)}%</b></span><span>成交额<b>{fmtAmount(selected.amount)}</b></span></div>
            </> : <EmptyState compact text="暂无候选股票" />}
          </article>
        </section>

        <section className="board-workspace">
          <article className="candidate-card">
            <div className="section-heading"><div><h2>今日候选</h2><span>{feedback}</span></div><button onClick={() => void runScreen()} aria-label="刷新"><RefreshCw /></button></div>
            {error ? <ErrorState message={error} onRetry={runScreen} /> : (
              <div className="table-wrap">
                <table className="candidate-table">
                  <thead><tr><th>排名</th><th>股票代码</th><th>股票名称</th><th>所属板块</th><th>形态匹配理由</th><th>匹配度</th><th>总市值</th><th>今日涨跌幅</th><th>5日趋势</th></tr></thead>
                  <tbody>{data?.items.slice(0, 10).map((stock, index) => {
                    const meta = patternMeta[stock.pattern || "breakout"];
                    return <tr key={stock.code} className={selected?.code === stock.code ? "selected" : ""} onClick={() => void chooseStock(stock)} tabIndex={0} onKeyDown={e => e.key === "Enter" && void chooseStock(stock)}>
                      <td><span className={index < 3 ? "rank top-rank" : "rank"}>{index + 1}</span></td>
                      <td className="code-cell">{stock.code}</td><td className="name-cell">{stock.name}</td><td>{stock.industry || stock.market || "—"}</td>
                      <td><span className={`pattern-tag ${meta.color}`}>{stock.pattern_name || meta.name}</span></td>
                      <td><div className="score-cell"><b>{Math.round(stock.score || 0)}</b><i><span style={{ width: `${stock.score || 0}%` }} /></i></div></td>
                      <td>{fmtMarketValue(stock.total_mv)}</td><td className={stock.pct_chg >= 0 ? "up" : "down"}>{stock.pct_chg >= 0 ? "+" : ""}{fmtNumber(stock.pct_chg)}%</td>
                      <td><MiniSparkline values={stock.sparkline} tone={meta.color as "mint" | "blue" | "lime"} /></td>
                    </tr>;
                  })}</tbody>
                </table>
                {!data?.items.length && !loading && <EmptyState text="当前条件暂无候选，请调整市值或板块后重新筛选" />}
              </div>
            )}
            <button className="view-all-button">查看全部 {data?.items.length || 0} 只 <ChevronDown /></button>
          </article>
          <article className="detail-card">
            {selected ? <>
              <div className="detail-chart-head"><b>日线</b><span className="ma ma5">MA5</span><span className="ma ma10">MA10</span><span className="ma ma20">MA20</span></div>
              <div className="detail-chart"><MarketChart bars={selected.bars || []} compact /></div>
              <div className="pattern-reading">
                <div className="reading-head"><h3>形态解读</h3><span className={`pattern-tag ${patternMeta[selected.pattern || "breakout"].color}`}>{selected.pattern_name || patternMeta[selected.pattern || "breakout"].name}</span></div>
                <ul>{(selected.reasons || ["结构条件已满足", "曲线形态相似度靠前", "处在可人工复核区间"]).slice(0, 4).map(reason => <li key={reason}><Check />{reason}</li>)}</ul>
                <div className="detail-actions"><button className="secondary-action" onClick={() => void toggleState("pending")}><CircleHelp />待判断</button><Link className="open-market-button" href={`/market?code=${selected.code}`}>打开行情 <ExternalLink /></Link></div>
              </div>
            </> : <EmptyState text="选择一只候选股票查看详情" />}
          </article>
        </section>

        <section className="state-cards">
          <StateCard tone="mint" icon={<Eye />} label="已查看" count={summary.viewed} onClick={() => setDrawer("viewed")} />
          <StateCard tone="blue" icon={<Bookmark />} label="已保存" count={summary.saved} onClick={() => setDrawer("saved")} />
          <StateCard tone="yellow" icon={<CircleHelp />} label="待判断" count={summary.pending} onClick={() => setDrawer("pending")} />
          <StateCard tone="plain" icon={<Clock3 />} label="历史记录" count={summary.history} onClick={() => setDrawer("history")} />
        </section>
      </main>
      {drawer && <div className="drawer-backdrop" onClick={() => setDrawer(null)}><aside className="state-drawer" onClick={e => e.stopPropagation()}><button className="drawer-close" onClick={() => setDrawer(null)}>×</button><h2>{drawerLabel(drawer)}</h2><p>记录保存在本项目的本地数据库中，不会上传。</p><strong>{Number(summary[drawer] || 0)}</strong><span>条记录</span></aside></div>}
    </div>
  );
}

function StateCard({ tone, icon, label, count, onClick }: { tone: string; icon: React.ReactNode; label: string; count: number; onClick: () => void }) {
  return <button className={`state-card ${tone}`} onClick={onClick}><span className="state-icon">{icon}</span><span><small>{label}</small><b>{count}</b></span><ChevronRight className="state-arrow" /></button>;
}

function EmptyState({ text, compact = false }: { text: string; compact?: boolean }) { return <div className={`empty-state ${compact ? "compact" : ""}`}><Database /><span>{text}</span></div>; }

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) { return <div className="error-state"><Database /><h3>本地数据暂不可用</h3><p>{message}</p><button onClick={onRetry}>重新连接</button></div>; }

function formatDate(value: string) { return value && value !== "—" ? value.replace(/-/g, ".").replace(/^(\d{4})(\d{2})(\d{2})$/, "$1.$2.$3") : "—"; }
function drawerLabel(key: keyof StateSummary) { return ({ viewed: "已查看", saved: "已保存", pending: "待判断", history: "历史筛选记录", watchlist: "自选" } as Record<string, string>)[key] || key; }
