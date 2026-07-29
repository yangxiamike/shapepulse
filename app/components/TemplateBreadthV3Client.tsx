"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
} from "react";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Gauge,
  Info,
  LoaderCircle,
  RotateCcw,
  TriangleAlert,
} from "lucide-react";
import { AppSidebar } from "./AppSidebar";
import styles from "./TemplateBreadthV3Client.module.css";

type SeriesPoint = { date: string; count: number; ma5?: number };
type IndustrySeriesPoint = { date: string; count: number };

type TopStock = {
  rank: number;
  ts_code: string;
  name: string;
  industry: string;
  score: number;
  above_threshold: boolean;
};

type Industry = {
  industry_code: string;
  industry: string;
  above_count: number;
  top100_count: number;
  top100_share: number;
  new_count: number;
  retained_count: number;
  exit_count: number;
  change_5d: number;
};

type TemplateData = {
  key: string;
  label: string;
  cue: string;
  accent: string;
  summary: {
    count: number;
    change1d: number;
    change5d: number;
    ma5: number;
    position: string;
    historicalPercentile: number;
  };
  marketSeries: SeriesPoint[];
  top30: TopStock[];
  industries: Industry[];
  industrySeries: Array<{
    industryCode: string;
    industry: string;
    points: IndustrySeriesPoint[];
  }>;
};

type BreadthPayload = {
  asOf: string;
  displayThreshold: number;
  warning: string;
  templates: TemplateData[];
};

type ViewMode = "width" | "change";

function signed(value: number, digits = 0) {
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
}

function readableDate(value: string) {
  const compact = value.replaceAll("-", "");
  if (compact.length !== 8) return value;
  return `${compact.slice(0, 4)}-${compact.slice(4, 6)}-${compact.slice(6, 8)}`;
}

function movement(value: number) {
  if (value > 0) return { label: "扩张", icon: <ArrowUp aria-hidden="true" />, className: styles.rise };
  if (value < 0) return { label: "收缩", icon: <ArrowDown aria-hidden="true" />, className: styles.fall };
  return { label: "持平", icon: <ArrowRight aria-hidden="true" />, className: styles.flat };
}

function compactDots(count: number, tone: "new" | "retained" | "exit") {
  const visible = Math.min(count, 10);
  return (
    <span className={styles.dotGroup} aria-label={`${tone === "new" ? "新进入" : tone === "retained" ? "保留" : "退出"} ${count} 只`}>
      {Array.from({ length: visible }, (_, index) => <i className={styles[tone]} key={index} />)}
      {count > visible ? <small>+{count - visible}</small> : null}
    </span>
  );
}

function treemapWeight(item: Industry, mode: ViewMode) {
  return mode === "change" ? Math.abs(item.change_5d) : item.above_count;
}

function buildTreemapRows(items: Industry[], mode: ViewMode) {
  const positive = items.filter(item => treemapWeight(item, mode) > 0);
  const total = positive.reduce((sum, item) => sum + treemapWeight(item, mode), 0);
  const largest = Math.max(1, ...positive.map(item => treemapWeight(item, mode)));
  const target = Math.max(largest, Math.sqrt(Math.max(1, total * largest * 1.25)));
  const rows: Industry[][] = [];
  let row: Industry[] = [];
  let rowTotal = 0;

  for (const item of positive) {
    if (row.length && rowTotal >= target) {
      rows.push(row);
      row = [];
      rowTotal = 0;
    }
    row.push(item);
    rowTotal += treemapWeight(item, mode);
  }
  if (row.length) rows.push(row);
  return { rows, total, omitted: items.filter(item => treemapWeight(item, mode) === 0) };
}

export function TemplateBreadthV3Client() {
  const [data, setData] = useState<BreadthPayload | null>(null);
  const [selectedKey, setSelectedKey] = useState("");
  const [selectedIndustry, setSelectedIndustry] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("width");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/template-breadth-v3.json", { cache: "no-store" });
      if (!response.ok) throw new Error(`数据文件返回 ${response.status}`);
      const payload = await response.json() as BreadthPayload;
      if (!Array.isArray(payload.templates) || payload.templates.length !== 4) {
        throw new Error("四模板数据不完整");
      }
      setData(payload);
      setSelectedKey(current => payload.templates.some(item => item.key === current)
        ? current
        : payload.templates[0].key);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "本地数据读取失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const template = useMemo(
    () => data?.templates.find(item => item.key === selectedKey) || data?.templates[0] || null,
    [data, selectedKey],
  );
  const treemap = useMemo(
    () => buildTreemapRows([...(template?.industries || [])].sort((a, b) =>
      treemapWeight(b, viewMode) - treemapWeight(a, viewMode) || a.industry_code.localeCompare(b.industry_code)), viewMode),
    [template, viewMode],
  );
  const industryExtremes = useMemo(() => {
    const industries = template?.industries || [];
    const expansion = [...industries].filter(item => item.change_5d > 0)
      .sort((a, b) => b.change_5d - a.change_5d || a.industry_code.localeCompare(b.industry_code))[0];
    const contraction = [...industries].filter(item => item.change_5d < 0)
      .sort((a, b) => a.change_5d - b.change_5d || a.industry_code.localeCompare(b.industry_code))[0];
    return { expansion, contraction };
  }, [template]);
  const focusedSeries = useMemo(
    () => template?.industrySeries.find(item => item.industryCode === selectedIndustry) || null,
    [selectedIndustry, template],
  );

  function chooseTemplate(key: string) {
    setSelectedKey(key);
    setSelectedIndustry("");
  }

  return (
    <div className={`app-shell ${styles.shell}`}>
      <AppSidebar active="template-breadth-v3" />
      <main
        className={styles.main}
        style={{ "--template-accent": template?.accent || "#1ca87a" } as CSSProperties}
      >
        <header className={styles.pageHead}>
          <div>
            <span className={styles.eyebrow}><Gauge aria-hidden="true" /> 统一观察线实验页</span>
            <h1>市场形态宽度</h1>
            <p>看有多少股票同时接近同一种市场形态，以及这种状态正在扩散还是收缩。</p>
          </div>
          {data ? <time>数据截至 {readableDate(data.asOf)}</time> : null}
        </header>

        <section className={styles.trialWarning} role="note" aria-label="试用观察线提醒">
          <TriangleAlert aria-hidden="true" />
          <div>
            <strong>0.80 试用观察线，实验未验证为四模板统一基准</strong>
            <span>{data?.warning || "本页只用于继续观察，不代表已确认有效，也不用于收益判断。"}</span>
          </div>
        </section>

        {loading ? (
          <section className={styles.stateCard} role="status">
            <LoaderCircle className="spin" aria-hidden="true" />
            <strong>正在读取本地试用数据</strong>
            <span>只读取仓库生成的统计文件。</span>
          </section>
        ) : error ? (
          <section className={styles.stateCard} role="alert">
            <TriangleAlert aria-hidden="true" />
            <strong>试用数据暂时不可用</strong>
            <span>{error}</span>
            <button type="button" onClick={() => void load()}><RotateCcw aria-hidden="true" />重新读取</button>
          </section>
        ) : data && template ? (
          <>
            <nav className={styles.templateTabs} aria-label="四模板切换">
              {data.templates.map(item => (
                <button
                  key={item.key}
                  type="button"
                  className={item.key === template.key ? styles.active : ""}
                  aria-pressed={item.key === template.key}
                  onClick={() => chooseTemplate(item.key)}
                >
                  <i style={{ background: item.accent }} />
                  <span><strong>{item.label}</strong><small>{item.cue}</small></span>
                </button>
              ))}
            </nav>

            <section className={styles.summaryGrid} aria-label={`${template.label}市场宽度概览`}>
              <SummaryCard label="当前超过 0.80" value={`${template.summary.count} 只`} note="同日达到试用观察线" featured />
              <SummaryCard label="较昨日" value={`${signed(template.summary.change1d)} 只`} note={template.summary.change1d > 0 ? "范围扩大" : template.summary.change1d < 0 ? "范围缩小" : "基本不变"} movementValue={template.summary.change1d} />
              <SummaryCard label="较 5 日前" value={`${signed(template.summary.change5d)} 只`} note="看一周左右的方向" movementValue={template.summary.change5d} />
              <SummaryCard label="5 日平均" value={`${template.summary.ma5.toFixed(1)} 只`} note="减少单日跳动干扰" />
              <SummaryCard label="历史位置" value={template.summary.position} note={`高于历史 ${template.summary.historicalPercentile.toFixed(0)}% 的日期`} />
            </section>

            <section className={styles.card}>
              <SectionHead kicker={`${template.label} · 近 60 个交易日`} title="超过观察线的股票数量" note="实线是每日数量，虚线是 5 日平均。" />
              <MarketSeriesChart points={template.marketSeries.slice(-60)} />
            </section>

            <div className={styles.workspace}>
              <section className={`${styles.card} ${styles.topCard}`}>
                <SectionHead kicker="固定展示 Top 30" title="最接近当前模板的股票" note="0.80 以下仍保留展示，并明确标为相对偏低。" />
                <Top30List items={template.top30.slice(0, 30)} threshold={data.displayThreshold} />
              </section>

              <section className={`${styles.card} ${styles.treemapCard}`}>
                <div className={styles.treemapHead}>
                  <SectionHead
                    kicker="申万一级行业"
                    title="行业宽度地图"
                    note={viewMode === "width"
                      ? "块的面积只表示当前超过 0.80 的股票数量。"
                      : "块的面积只表示近 5 日变化幅度；颜色、箭头与文字表示扩张或收缩。"}
                  />
                  <div className={styles.segmented} role="group" aria-label="行业地图视图">
                    <button type="button" className={viewMode === "width" ? styles.active : ""} aria-pressed={viewMode === "width"} onClick={() => setViewMode("width")}>当前宽度</button>
                    <button type="button" className={viewMode === "change" ? styles.active : ""} aria-pressed={viewMode === "change"} onClick={() => setViewMode("change")}>最近变化</button>
                  </div>
                </div>
                <div className={styles.industryExtremes} aria-label="行业五日最大变化摘要">
                  <span className={styles.rise}><ArrowUp aria-hidden="true" /><small>5日最大扩张</small><strong>{industryExtremes.expansion ? `${industryExtremes.expansion.industry} ${signed(industryExtremes.expansion.change_5d)}只` : "暂无"}</strong></span>
                  <span className={styles.fall}><ArrowDown aria-hidden="true" /><small>5日最大收缩</small><strong>{industryExtremes.contraction ? `${industryExtremes.contraction.industry} ${signed(industryExtremes.contraction.change_5d)}只` : "暂无"}</strong></span>
                </div>
                <div className={styles.legend} aria-label={viewMode === "width" ? "股票进出图例" : "行业变化方向图例"}>
                  {viewMode === "width" ? <>
                    <span><i className={styles.new} />新进入</span>
                    <span><i className={styles.retained} />保留</span>
                    <span><i className={styles.exit} />退出</span>
                    <small>面积表示当前数量；方格同时显示新进、保留和退出。</small>
                  </> : <>
                    <span><i className={styles.changeRise} />↑ 扩张</span>
                    <span><i className={styles.changeFall} />↓ 收缩</span>
                    <small>面积表示变化绝对值；收缩到 0 的行业也会显示。</small>
                  </>}
                </div>
                <IndustryTreemap
                  rows={treemap.rows}
                  total={treemap.total}
                  omitted={treemap.omitted}
                  mode={viewMode}
                  selected={selectedIndustry}
                  onSelect={setSelectedIndustry}
                />
              </section>
            </div>

            <section className={`${styles.card} ${styles.industryDetail}`} aria-live="polite">
              {focusedSeries ? (
                <>
                  <div className={styles.selectedIndustryHead}>
                    <div>
                      <span>已选行业</span>
                      <h2>{focusedSeries.industry}</h2>
                      <p>下图只看这个行业近 60 日超过 0.80 的股票数量。</p>
                    </div>
                    <button type="button" onClick={() => setSelectedIndustry("")}><ArrowLeft aria-hidden="true" />返回全部行业</button>
                  </div>
                  <IndustrySeriesChart points={focusedSeries.points.slice(-60)} industry={focusedSeries.industry} />
                </>
              ) : (
                <div className={styles.industryPrompt}>
                  <Info aria-hidden="true" />
                  <div><strong>点击一个行业块查看变化</strong><span>默认先看全市场，想进一步了解时再进入单个行业。</span></div>
                </div>
              )}
            </section>

            <section className={styles.explainer}>
              <h2>怎么读这页</h2>
              <div>
                <p><strong>数量上升：</strong>更多股票开始呈现相近形态，可以理解为形态正在扩散。</p>
                <p><strong>数量下降：</strong>达到观察线的股票变少，可以理解为形态正在收缩。</p>
                <p><strong>数量长期较低：</strong>这种形态在当时并不普遍。0.80 只是试用线，不能单独作为买卖依据。</p>
              </div>
            </section>
          </>
        ) : null}
      </main>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  note,
  featured = false,
  movementValue,
}: {
  label: string;
  value: string;
  note: string;
  featured?: boolean;
  movementValue?: number;
}) {
  const tone = movementValue == null ? "" : movement(movementValue).className;
  return (
    <article className={`${styles.summaryCard} ${featured ? styles.featured : ""} ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  );
}

function SectionHead({ kicker, title, note }: { kicker: string; title: string; note: string }) {
  return (
    <div className={styles.sectionHead}>
      <span>{kicker}</span>
      <h2>{title}</h2>
      <p>{note}</p>
    </div>
  );
}

function MarketSeriesChart({ points }: { points: SeriesPoint[] }) {
  const width = 900;
  const height = 250;
  const pad = { left: 52, right: 20, top: 20, bottom: 38 };
  const values = points.flatMap(point => [point.count, point.ma5 ?? point.count]);
  const max = Math.max(1, ...values);
  const x = (index: number) => pad.left + index * ((width - pad.left - pad.right) / Math.max(1, points.length - 1));
  const y = (value: number) => height - pad.bottom - value / max * (height - pad.top - pad.bottom);
  const countPath = points.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(point.count).toFixed(1)}`).join(" ");
  const average = points.filter(point => Number.isFinite(point.ma5));
  const averagePath = average.map((point, index) => {
    const originalIndex = points.indexOf(point);
    return `${index ? "L" : "M"}${x(originalIndex).toFixed(1)},${y(point.ma5 ?? point.count).toFixed(1)}`;
  }).join(" ");
  const ticks = [0, Math.round(max / 2), max];
  const dateIndexes = points.length ? [0, Math.floor((points.length - 1) / 2), points.length - 1] : [];

  if (!points.length) return <div className={styles.emptyChart}>暂无时间序列。</div>;
  return (
    <div className={styles.chartWrap}>
      <svg className={styles.lineChart} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="近60日超过观察线数量与5日均线">
        {ticks.map(tick => <g key={tick}><line x1={pad.left} x2={width - pad.right} y1={y(tick)} y2={y(tick)} /><text x={pad.left - 10} y={y(tick) + 5}>{tick}</text></g>)}
        <path className={styles.averageLine} d={averagePath} />
        <path className={styles.primaryLine} d={countPath} />
        {dateIndexes.map(index => <text className={styles.dateLabel} key={index} x={x(index)} y={height - 10}>{readableDate(points[index].date).slice(5)}</text>)}
      </svg>
    </div>
  );
}

function Top30List({ items, threshold }: { items: TopStock[]; threshold: number }) {
  const splitAt = items.findIndex(item => item.score < threshold || !item.above_threshold);
  return (
    <div className={styles.stockList}>
      {items.map((item, index) => (
        <div key={item.ts_code}>
          {index === splitAt ? (
            <div className={styles.thresholdLine} role="separator">
              <span>{threshold.toFixed(2)} 试用观察线</span>
            </div>
          ) : null}
          <article className={!item.above_threshold || item.score < threshold ? styles.below : ""}>
            <b className={styles.stockRank}>{item.rank}</b>
            <div className={styles.stockIdentity}><strong>{item.name}</strong><small>{item.ts_code} · {item.industry || "行业待补"}</small></div>
            <span className={styles.score}>{item.score.toFixed(3)}</span>
            <em>{item.above_threshold && item.score >= threshold ? "线上" : "相对偏低"}</em>
          </article>
        </div>
      ))}
      {splitAt < 0 ? <div className={`${styles.thresholdLine} ${styles.after}`} role="separator"><span>{threshold.toFixed(2)} 试用观察线</span></div> : null}
    </div>
  );
}

function IndustryTreemap({
  rows,
  total,
  omitted,
  mode,
  selected,
  onSelect,
}: {
  rows: Industry[][];
  total: number;
  omitted: Industry[];
  mode: ViewMode;
  selected: string;
  onSelect: (code: string) => void;
}) {
  if (!total) return <div className={styles.emptyChart}>{mode === "width" ? "当前没有行业股票达到 0.80。" : "近 5 日行业数量没有变化。"}</div>;
  return (
    <>
      <div className={styles.treemap} data-view={mode}>
        {rows.map((row, rowIndex) => {
          const rowTotal = row.reduce((sum, item) => sum + treemapWeight(item, mode), 0);
          return (
            <div className={styles.treemapRow} style={{ flexGrow: rowTotal }} key={rowIndex}>
              {row.map(item => {
                const state = movement(item.change_5d);
                return (
                  <button
                    type="button"
                    className={`${styles.industryBlock} ${mode === "change" ? state.className : ""} ${selected === item.industry_code ? styles.selected : ""}`}
                    style={{ flexGrow: treemapWeight(item, mode) }}
                    aria-pressed={selected === item.industry_code}
                    aria-label={`${item.industry}，当前 ${item.above_count} 只，Top100行业占比 ${(item.top100_share * 100).toFixed(0)}%，5日变化 ${signed(item.change_5d)} 只`}
                    onClick={() => onSelect(item.industry_code)}
                    key={item.industry_code}
                  >
                    <span className={styles.industryTitle}><strong>{item.industry}</strong><em>{item.above_count} 只</em></span>
                    <small>Top100 行业占比 {(item.top100_share * 100).toFixed(0)}%</small>
                    <span className={styles.changeLabel}>{state.icon}{state.label} {signed(item.change_5d)} 只</span>
                    <span className={styles.dotBands}>
                      {compactDots(item.new_count, "new")}
                      {compactDots(item.retained_count, "retained")}
                      {compactDots(item.exit_count, "exit")}
                    </span>
                  </button>
                );
              })}
            </div>
          );
        })}
      </div>
      {mode === "width" && omitted.length ? <p className={styles.zeroIndustries}>当前为 0：{omitted.map(item => item.industry).join("、")}</p> : null}
    </>
  );
}

function IndustrySeriesChart({ points, industry }: { points: IndustrySeriesPoint[]; industry: string }) {
  const width = 900;
  const height = 210;
  const pad = { left: 48, right: 20, top: 18, bottom: 34 };
  const max = Math.max(1, ...points.map(point => point.count));
  const x = (index: number) => pad.left + index * ((width - pad.left - pad.right) / Math.max(1, points.length - 1));
  const y = (value: number) => height - pad.bottom - value / max * (height - pad.top - pad.bottom);
  const path = points.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(point.count).toFixed(1)}`).join(" ");
  const last = points.at(-1);
  if (!points.length) return <div className={styles.emptyChart}>{industry}暂无历史序列。</div>;
  return (
    <div className={styles.chartWrap}>
      <svg className={styles.lineChart} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${industry}近60日超过观察线股票数量`}>
        {[0, Math.round(max / 2), max].map(tick => <g key={tick}><line x1={pad.left} x2={width - pad.right} y1={y(tick)} y2={y(tick)} /><text x={pad.left - 10} y={y(tick) + 5}>{tick}</text></g>)}
        <path className={styles.primaryLine} d={path} />
        {last ? <circle className={styles.lastPoint} cx={x(points.length - 1)} cy={y(last.count)} r="5" /> : null}
        <text className={styles.dateLabel} x={pad.left} y={height - 8}>{readableDate(points[0].date).slice(5)}</text>
        <text className={styles.dateLabel} x={width - pad.right} y={height - 8}>{readableDate(points.at(-1)!.date).slice(5)}</text>
      </svg>
    </div>
  );
}
