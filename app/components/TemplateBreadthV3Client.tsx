"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import { ArrowDown, ArrowRight, ArrowUp, Gauge, LoaderCircle, RotateCcw, TriangleAlert } from "lucide-react";
import { AppSidebar } from "./AppSidebar";
import styles from "./TemplateBreadthV3Client.module.css";

type Point = { date: string; count?: number; top100_count?: number };
type IndustryStock = { ts_code: string; code?: string; name: string; score?: number };
type Industry = {
  industry_code: string; industry: string; top100_count: number; top100_share?: number;
  eligible_count?: number; selection_rate?: number;
  new_count: number; retained_count: number; exit_count: number; change_5d: number;
  current_stocks?: IndustryStock[]; stocks?: IndustryStock[];
  new_stocks?: IndustryStock[]; retained_stocks?: IndustryStock[]; exit_stocks?: IndustryStock[];
};
type TemplateData = {
  key: string; label: string; cue: string; accent: string;
  top100?: IndustryStock[]; topStocks?: IndustryStock[];
  industries: Industry[];
  industrySeries: Array<{ industryCode: string; industry: string; points: Point[] }>;
};
type Payload = { asOf: string; warning?: string; templates: TemplateData[] };
type Rect = { item: Industry; x: number; y: number; width: number; height: number };

function date(value: string) {
  const text = value.replaceAll("-", "");
  return text.length === 8 ? `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6)}` : value;
}
function stockCode(item: IndustryStock) { return item.code || item.ts_code.split(".")[0]; }
function signed(value: number) { return `${value > 0 ? "+" : ""}${value}`; }

function worst(row: Array<{ item: Industry; area: number }>, side: number) {
  if (!row.length) return Infinity;
  const sum = row.reduce((total, entry) => total + entry.area, 0);
  const min = Math.min(...row.map(entry => entry.area));
  const max = Math.max(...row.map(entry => entry.area));
  const side2 = side * side;
  return Math.max(side2 * max / (sum * sum), (sum * sum) / (side2 * min));
}

function squarify(items: Industry[]): Rect[] {
  const weighted = items.filter(item => item.top100_count > 0).sort((a, b) => b.top100_count - a.top100_count);
  const total = weighted.reduce((sum, item) => sum + item.top100_count, 0);
  const pending = weighted.map(item => ({ item, area: item.top100_count / Math.max(1, total) * 10000 }));
  const output: Rect[] = [];
  let box = { x: 0, y: 0, width: 100, height: 100 };

  function layout(row: typeof pending) {
    const area = row.reduce((sum, entry) => sum + entry.area, 0);
    if (box.width >= box.height) {
      const rowWidth = area / box.height;
      let y = box.y;
      row.forEach(entry => {
        const height = entry.area / rowWidth;
        output.push({ item: entry.item, x: box.x, y, width: rowWidth, height });
        y += height;
      });
      box = { x: box.x + rowWidth, y: box.y, width: Math.max(0, box.width - rowWidth), height: box.height };
    } else {
      const rowHeight = area / box.width;
      let x = box.x;
      row.forEach(entry => {
        const width = entry.area / rowHeight;
        output.push({ item: entry.item, x, y: box.y, width, height: rowHeight });
        x += width;
      });
      box = { x: box.x, y: box.y + rowHeight, width: box.width, height: Math.max(0, box.height - rowHeight) };
    }
  }

  let row: typeof pending = [];
  while (pending.length) {
    const next = pending[0];
    const side = Math.max(.001, Math.min(box.width, box.height));
    if (!row.length || worst([...row, next], side) <= worst(row, side)) {
      row.push(pending.shift()!);
    } else {
      layout(row);
      row = [];
    }
  }
  if (row.length) layout(row);
  return output;
}

export function TemplateBreadthV3Client() {
  const [data, setData] = useState<Payload | null>(null);
  const [selectedKey, setSelectedKey] = useState("");
  const [selectedIndustry, setSelectedIndustry] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const response = await fetch("/template-breadth-v3.json", { cache: "no-store" });
      if (!response.ok) throw new Error(`数据文件返回 ${response.status}`);
      const payload = await response.json() as Payload;
      if (payload.templates?.length !== 4) throw new Error("冻结四模板数据不完整");
      setData(payload);
      setSelectedKey(key => payload.templates.some(item => item.key === key) ? key : payload.templates[0].key);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "本地 Top100 数据读取失败");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);
  const template = useMemo(() => data?.templates.find(item => item.key === selectedKey) || data?.templates[0] || null, [data, selectedKey]);
  const rects = useMemo(() => squarify(template?.industries || []), [template]);
  const selected = useMemo(() => template?.industries.find(item => item.industry_code === selectedIndustry) || null, [template, selectedIndustry]);
  const selectedSeries = useMemo(() => template?.industrySeries.find(item => item.industryCode === selectedIndustry)?.points || [], [template, selectedIndustry]);
  const entrants = useMemo(() => [...(template?.industries || [])].sort((a, b) => b.new_count - a.new_count)[0], [template]);
  const exits = useMemo(() => [...(template?.industries || [])].sort((a, b) => b.exit_count - a.exit_count)[0], [template]);
  const widest = useMemo(() => [...(template?.industries || [])].sort((a, b) => b.top100_count - a.top100_count)[0], [template]);

  return <div className={`app-shell ${styles.shell}`}>
    <AppSidebar active="template-breadth-v3" />
    <main className={styles.main} style={{ "--accent": template?.accent || "#138563" } as CSSProperties}>
      <header className={styles.pageHead}>
        <div><span><Gauge /> 每模板每日固定 Top100</span><h1>Top100 行业宽度</h1><p>面积看当前入选数量，变化看相对 5 个交易日前的新进入、保留与退出。</p></div>
        {data ? <time>数据日期 {date(data.asOf)}</time> : null}
      </header>
      {loading ? <State title="正在读取本地 Top100 日序列" text="每个模板独立排名，不跨模板综合。" /> :
        error ? <State title="Top100 数据暂不可用" text={error} action={<button onClick={() => void load()}><RotateCcw />重试</button>} /> :
        template && data ? <>
          <nav className={styles.tabs} aria-label="冻结四模板切换">{data.templates.map(item => <button key={item.key} className={item.key === template.key ? styles.active : ""} aria-pressed={item.key === template.key} onClick={() => { setSelectedKey(item.key); setSelectedIndustry(""); }}><i style={{ background: item.accent }} /><span><strong>{item.label}</strong><small>{item.cue}</small></span></button>)}</nav>

          <section className={styles.summary} aria-label={`${template.label} Top100 行业摘要`}>
            <article><span>当前模板</span><strong>{template.label}</strong><small>冻结定义 · 本模板独立 Pearson 排名</small></article>
            <article><span>最宽行业</span><strong>{widest ? `${widest.industry} ${widest.top100_count} 只` : "—"}</strong><small>面积最大的行业块</small></article>
            <article><span>5日新进入最多</span><strong>{entrants ? `${entrants.industry} ${entrants.new_count} 只` : "—"}</strong><small>相对 5 个交易日前</small></article>
            <article><span>5日退出最多</span><strong>{exits ? `${exits.industry} ${exits.exit_count} 只` : "—"}</strong><small>退出不计入当前面积</small></article>
          </section>

          <div className={styles.workspace}>
            <section className={styles.mapCard}>
              <div className={styles.sectionHead}><div><span>当前宽度 · 申万一级行业</span><h2>Top100 行业空间</h2><p>块面积只表示当前 Top100 中的行业股票数量；颜色深浅辅助区分行业，不表达涨跌。</p></div><small>分母：本模板当日可选股票 · 单位：只 / %</small></div>
              <div className={styles.legend}><span><i />当前 Top100 数量决定面积</span><span><b>入选率</b> = 行业入选数 ÷ 行业当日可选数</span></div>
              <div className={styles.treemap} role="group" aria-label={`${template.label} Top100 行业矩形树图`}>
                {rects.map((rect, index) => {
                  const industry = rect.item;
                  const eligible = industry.eligible_count || 0;
                  const rate = industry.selection_rate ?? (eligible ? industry.top100_count / eligible : industry.top100_share || 0);
                  return <button
                    key={industry.industry_code}
                    className={industry.industry_code === selectedIndustry ? styles.selected : ""}
                    style={{ left: `${rect.x}%`, top: `${rect.y}%`, width: `${rect.width}%`, height: `${rect.height}%`, "--shade": `${Math.max(.08, Math.min(.32, rate * 1.8 + index % 4 * .025))}` } as CSSProperties}
                    onClick={() => setSelectedIndustry(industry.industry_code)}
                    aria-label={`${industry.industry}，当前 Top100 ${industry.top100_count} 只，行业入选率 ${(rate * 100).toFixed(1)}%，点击查看股票`}
                  >
                    <strong>{industry.industry}</strong><b>{industry.top100_count} 只</b>
                    {rect.width > 13 && rect.height > 12 ? <small>{eligible ? `${(rate * 100).toFixed(1)}% · ${industry.top100_count}/${eligible}` : `Top100 占比 ${(industry.top100_share || 0) * 100}%`}</small> : null}
                  </button>;
                })}
              </div>
            </section>

            <aside className={styles.changeCard}>
              <div className={styles.sectionHead}><div><span>最近变化 · 相对 5 个交易日前</span><h2>行业进出</h2><p>数字、文字和条段共同表达，不只依赖颜色。</p></div></div>
              <div className={styles.changeList}>{[...(template.industries || [])].sort((a, b) => b.new_count + b.exit_count - a.new_count - a.exit_count).map(item => {
                const total = Math.max(1, item.new_count + item.retained_count + item.exit_count);
                return <button key={item.industry_code} onClick={() => setSelectedIndustry(item.industry_code)} className={item.industry_code === selectedIndustry ? styles.active : ""}>
                  <span><strong>{item.industry}</strong><small>{signed(item.change_5d)} 只净变化</small></span>
                  <div aria-label={`新进入 ${item.new_count}，保留 ${item.retained_count}，退出 ${item.exit_count}`}>
                    <i className={styles.new} style={{ width: `${item.new_count / total * 100}%` }} />
                    <i className={styles.kept} style={{ width: `${item.retained_count / total * 100}%` }} />
                    <i className={styles.exit} style={{ width: `${item.exit_count / total * 100}%` }} />
                  </div>
                  <em><b>新 {item.new_count}</b><b>留 {item.retained_count}</b><b>退 {item.exit_count}</b></em>
                </button>;
              })}</div>
            </aside>
          </div>

          <section className={styles.detail}>
            {selected ? <>
              <div className={styles.detailHead}><div><span>已选行业</span><h2>{selected.industry}</h2><p>{date(data.asOf)}：当前 Top100 {selected.top100_count} 只；行业当日可选 {selected.eligible_count ?? "待数据补充"} 只；入选率 {selected.eligible_count ? `${(selected.top100_count / selected.eligible_count * 100).toFixed(1)}%` : "待数据补充"}。</p></div><button onClick={() => setSelectedIndustry("")}>返回全行业</button></div>
              <div className={styles.detailGrid}>
                <div className={styles.currentStocks}><h3>当前进入 Top100</h3><StockList items={selected.current_stocks || selected.stocks || []} templateId={template.key} empty="当前股票明细待本地统计文件补充。" /></div>
                <div className={styles.transitions}><h3>5日进出明细</h3><Transition title="新进入" icon={<ArrowUp />} count={selected.new_count} items={selected.new_stocks || []} templateId={template.key} /><Transition title="保留" icon={<ArrowRight />} count={selected.retained_count} items={selected.retained_stocks || []} templateId={template.key} /><Transition title="退出" icon={<ArrowDown />} count={selected.exit_count} items={selected.exit_stocks || []} templateId={template.key} /></div>
                <div className={styles.series}><h3>行业 Top100 数量时间序列</h3><Series points={selectedSeries} industry={selected.industry} /></div>
              </div>
            </> : <div className={styles.prompt}><strong>点击行业块查看股票与时间序列</strong><span>可继续从股票行进入行情详情，并保留当前模板上下文。</span></div>}
          </section>
          <section className={styles.note}><TriangleAlert /><p><strong>口径边界：</strong>Top100 是每个模板当日 Pearson 排名，不是跨模板综合排名，也不代表市场已进入或缺少某种行情阶段。真实模板与候选 K 线用于判断匹配更接近起涨、加速还是末端；本页不使用未来收益验证。</p></section>
        </> : null}
    </main>
  </div>;
}

function StockList({ items, templateId, empty }: { items: IndustryStock[]; templateId: string; empty: string }) {
  if (!items.length) return <p>{empty}</p>;
  return <div>{items.map(item => <Link href={`/market?code=${encodeURIComponent(stockCode(item))}&template=${encodeURIComponent(templateId)}`} key={item.ts_code}><span><strong>{item.name}</strong><small>{item.ts_code}</small></span>{item.score != null ? <b>{item.score.toFixed(3)}</b> : null}<ArrowRight /></Link>)}</div>;
}
function Transition({ title, icon, count, items, templateId }: { title: string; icon: React.ReactNode; count: number; items: IndustryStock[]; templateId: string }) {
  return <details open><summary>{icon}<strong>{title}</strong><b>{count} 只</b></summary><StockList items={items} templateId={templateId} empty="明细待本地统计文件补充。" /></details>;
}
function Series({ points, industry }: { points: Point[]; industry: string }) {
  const values = points.map(point => point.top100_count ?? point.count ?? 0);
  if (!points.length) return <p>暂无时间序列。</p>;
  const width = 760, height = 190, pad = 24, max = Math.max(1, ...values);
  const x = (i: number) => pad + i * ((width - pad * 2) / Math.max(1, values.length - 1));
  const y = (v: number) => height - pad - v / max * (height - pad * 2);
  const path = values.map((value, i) => `${i ? "L" : "M"}${x(i)},${y(value)}`).join(" ");
  return <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${industry} Top100 入选数量时间序列`}><line x1={pad} x2={width - pad} y1={height - pad} y2={height - pad} /><path d={path} /><text x={pad} y={height - 5}>{date(points[0].date).slice(5)}</text><text textAnchor="end" x={width - pad} y={height - 5}>{date(points.at(-1)!.date).slice(5)}</text></svg>;
}
function State({ title, text, action }: { title: string; text: string; action?: React.ReactNode }) {
  return <section className={styles.state}><LoaderCircle className="spin" /><strong>{title}</strong><span>{text}</span>{action}</section>;
}
