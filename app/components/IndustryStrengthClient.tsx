"use client";

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent,
} from "react";
import {
  Activity,
  CalendarDays,
  CircleHelp,
  LoaderCircle,
  RefreshCw,
  TriangleAlert,
} from "lucide-react";
import { AppSidebar } from "./AppSidebar";
import { api, formatDate } from "../lib/api";
import type {
  IndustryStrengthPoint,
  IndustryStrengthResponse,
  IndustryStrengthRow,
  PatternKey,
} from "../lib/types";

const patternOptions: Array<{ value: PatternKey; label: string }> = [
  { value: "breakout", label: "突破启动" },
  { value: "pullback", label: "上升趋势回调" },
  { value: "range_bounce", label: "区间下沿反弹" },
];

const lineColors = ["#0057b8", "#d97706", "#7c3aed", "#0891b2", "#4b5563"];

function inputDate(value: string) {
  return value ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}` : "";
}

function signed(value: number, digits = 0, suffix = "") {
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}${suffix}`;
}

function movementClass(value: number) {
  return value > 0 ? "rotation-positive" : value < 0 ? "rotation-negative" : "";
}

export function IndustryStrengthClient() {
  const [pattern, setPattern] = useState<PatternKey>("breakout");
  const [endDate, setEndDate] = useState("");
  const [data, setData] = useState<IndustryStrengthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshStartedAt, setRefreshStartedAt] = useState<number | null>(null);
  const [selectedIndustry, setSelectedIndustry] = useState("");
  const [selectedDate, setSelectedDate] = useState("");

  const load = useCallback(async (
    nextPattern: PatternKey,
    nextEndDate?: string,
    force = false,
  ) => {
    setLoading(true);
    setRefreshStartedAt(Date.now());
    setError("");
    try {
      const result = await api.industryStrength(nextPattern, nextEndDate, force);
      const initialIndustry = result.display.default_visible_codes[0]
        || result.ranking[0]?.code
        || "";
      setData(result);
      setEndDate(inputDate(result.resolved_end_date));
      setSelectedIndustry(initialIndustry);
      setSelectedDate(result.resolved_end_date);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "行业强弱数据加载失败");
    } finally {
      setLoading(false);
      setRefreshStartedAt(null);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load("breakout"), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const allRowsByCode = useMemo(
    () => new Map(data?.ranking.map(row => [row.code, row]) || []),
    [data],
  );
  const visibleRows = useMemo(
    () => data?.display.default_visible_codes
      .map(code => allRowsByCode.get(code))
      .filter((row): row is IndustryStrengthRow => Boolean(row)) || [],
    [allRowsByCode, data],
  );
  const latestFirstDates = useMemo(
    () => data?.display.latest_first_dates?.length
      ? data.display.latest_first_dates
      : [...(data?.sampling.dates || [])].reverse(),
    [data],
  );
  const selectedRow = allRowsByCode.get(selectedIndustry) || data?.ranking[0] || null;
  const selectedPoint = selectedRow?.points.find(point => point.date === selectedDate)
    || selectedRow?.points.at(-1)
    || null;
  const trendRows = useMemo(() => {
    if (!data) return [];
    const codes = [
      selectedIndustry,
      ...data.display.default_visible_codes,
    ].filter(Boolean);
    return [...new Set(codes)]
      .map(code => allRowsByCode.get(code))
      .filter((row): row is IndustryStrengthRow => Boolean(row))
      .slice(0, 5);
  }, [allRowsByCode, data, selectedIndustry]);

  const selectPreview = useCallback((industryCode: string, date: string) => {
    setSelectedIndustry(industryCode);
    setSelectedDate(date);
  }, []);

  return (
    <div className="app-shell industry-shell">
      <AppSidebar active="industry-strength" />
      <main className="industry-main">
        <header className="industry-page-head">
          <div className="industry-page-copy">
            <span className="eyebrow"><Activity /> 行业轮动</span>
            <div className="industry-page-title-row">
              <h1>行业强弱</h1>
              <InfoTip
                label="固定统计口径"
                text="仅使用本地 zer0share：主板、剔除 ST，沿用既有形态算法与申万一级行业口径。回看 120 个交易日，每 5 个交易日采样，共 24 个节点；每个节点取 Top 100，分母固定为 100。"
              />
            </div>
            <p>先看变化速度，再看绝对水平：快速识别加速、退潮与刚启动。</p>
          </div>
          <div className="industry-filter-bar">
            <label>
              <span>形态</span>
              <select
                aria-label="形态"
                value={pattern}
                disabled={loading}
                onChange={event => {
                  const next = event.target.value as PatternKey;
                  setPattern(next);
                  void load(next, endDate);
                }}
              >
                {patternOptions.map(option => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label>
              <span><CalendarDays /> 截止日期</span>
              <input
                aria-label="截止日期"
                type="date"
                value={endDate}
                disabled={loading}
                onChange={event => setEndDate(event.target.value)}
              />
            </label>
            <button type="button" disabled={loading} onClick={() => void load(pattern, endDate, true)}>
              {loading ? <LoaderCircle className="spin" /> : <RefreshCw />}
              刷新截面
            </button>
          </div>
        </header>

        {loading && data ? (
          <div className="industry-refresh-state" role="status" aria-live="polite">
            <LoaderCircle className="spin" />
            <div>
              <b>正在更新轮动截面</b>
              <span>旧结果保持可读；本地服务完成 24 个截面后一次替换，不显示估算进度。</span>
            </div>
            <time>{refreshStartedAt ? "等待完成" : ""}</time>
          </div>
        ) : null}

        {loading && !data ? (
          <section className="industry-loading" aria-live="polite">
            <LoaderCircle className="spin" />
            <h2>正在计算 24 个真实历史截面</h2>
            <p>首次计算会读取本地行情并执行形态评分；接口完成后一次返回，不展示推测进度。</p>
            <div className="industry-loading-skeleton" aria-hidden="true">
              <i /><i /><i /><i /><i /><i />
            </div>
          </section>
        ) : error && !data ? (
          <section className="error-state" role="alert">
            <TriangleAlert />
            <b>行业强弱暂时不可用</b>
            <span>{error}</span>
            <button type="button" onClick={() => void load(pattern, endDate)}>重新加载</button>
          </section>
        ) : data ? (
          <>
            {error ? <div className="industry-warning" role="alert"><TriangleAlert />{error}</div> : null}
            {data.warnings.length ? (
              <div className="industry-warning" data-testid="industry-warnings">
                <TriangleAlert />
                <div>{data.warnings.map(item => <span key={item}>{item}</span>)}</div>
              </div>
            ) : null}

            <section className="industry-metrics" aria-label="行业轮动概览">
              <Metric
                label="上升最快"
                value={data.metrics.fastest_strengthening || "—"}
                note={`${signed(data.metrics.fastest_strengthening_speed, 2)} 只/点 · ${signed(data.metrics.fastest_strengthening_change)} 只`}
                tone="rise"
              />
              <Metric
                label="下降最快"
                value={data.metrics.fastest_weakening || "—"}
                note={`${signed(data.metrics.fastest_weakening_speed, 2)} 只/点 · ${signed(data.metrics.fastest_weakening_change)} 只`}
                tone="fall"
              />
              <Metric
                label="刚启动"
                value={data.metrics.just_started_industry || "暂无"}
                note={`${data.metrics.just_started_count} 个行业符合`}
                tone="rise"
              />
              <Metric
                label="持续增强"
                value={`${data.metrics.persistent_strengthening_count} 个`}
                note="近 3 个间隔至少 2 次上升"
              />
              <Metric
                label="轮动广度"
                value={`↑ ${data.metrics.rising_industry_count} / ↓ ${data.metrics.falling_industry_count}`}
                note="上升行业 / 下降行业"
              />
              <Metric
                label="绝对水平参考"
                value={data.metrics.strongest_industry || "—"}
                note={`当前 ${data.metrics.strongest_count}% · 次要指标`}
                tone="secondary"
              />
            </section>

            <section className="industry-card analysis-card">
              <div className="industry-section-head">
                <div><span>系统分析</span><h2>本期轮动判断</h2><p>{data.pattern_label} · {formatDate(data.resolved_end_date, "-")}</p></div>
                <InfoTip
                  label="轮动分析口径"
                  text={`${data.rules.slope_explanation} ${data.rules.stable_sort_explanation}`}
                />
              </div>
              <div className="analysis-sentences" aria-label="本期轮动分析结论">
                <strong>数据结论</strong>
                {data.analysis.map(item => <p key={item}>{item}</p>)}
              </div>
            </section>

            <section className="industry-card heatmap-card">
              <div className="industry-section-head">
                <div>
                  <span>轮动速度热力带 · 活跃 12 行</span>
                  <h2>最新在左，向右回看 24 个节点</h2>
                </div>
                <div className="section-head-actions">
                  <div className="heat-legend" aria-label="占比颜色图例，蓝色低值到橙黄色高值">
                    {["0", "1–2%", "3–4%", "5–7%", "8–10%", "10%以上"].map((label, index) => (
                      <span key={label}><i className={`heat-${index}`} />{label}</span>
                    ))}
                  </div>
                  <InfoTip
                    label="热力图阅读说明"
                    text="近 4 个采样点用线性斜率判断速度；同速按持续性、最新有效占比和行业代码稳定排序。颜色只表示占比档位，10% 以上视觉封顶，格内与详情保留真实数值。最新日期在最左侧。"
                  />
                </div>
              </div>
              <div className="industry-heat-scroll">
                <div className="industry-heat-canvas">
                  <HeatTimeAxis dates={latestFirstDates} />
                  <div className="industry-heat-grid" role="grid" aria-label="行业轮动热力图，最新日期在最左侧">
                    {visibleRows.map(row => (
                      <HeatmapRow
                        key={row.code}
                        row={row}
                        dates={latestFirstDates}
                        selectedIndustry={selectedIndustry}
                        selectedDate={selectedDate}
                        onPreview={selectPreview}
                      />
                    ))}
                  </div>
                </div>
              </div>
              {selectedRow && selectedPoint ? <PointDetail row={selectedRow} point={selectedPoint} /> : null}
            </section>

            <section className="industry-card trend-card">
              <div className="industry-section-head">
                <div><span>完整 24 节点趋势</span><h2>默认比较全部，悬停后聚焦单个行业</h2></div>
                <InfoTip
                  label="趋势图交互说明"
                  text="默认所有展示线条同等清晰。鼠标悬停或键盘聚焦某条线后，该线加粗，其余线淡化；离开或失焦即恢复全部。右侧选择器可加入任一申万一级行业。"
                />
              </div>
              <TrendChart
                rows={trendRows}
                allRows={data.ranking}
                dates={data.sampling.dates}
                selectedCode={selectedIndustry}
                onSelect={code => selectPreview(code, data.resolved_end_date)}
              />
            </section>

            <section className="industry-card ranking-card">
              <div className="industry-section-head">
                <div><span>近期轮动速度排名 · 前 15</span><h2>{formatDate(data.resolved_end_date, "-")} 收盘截面</h2></div>
                <InfoTip
                  label="排名口径说明"
                  text={`观察顺序优先看速度绝对值，再看持续性和最新有效占比；分母固定为 100。${data.rules.slope_explanation}`}
                />
              </div>
              <div className="industry-table-wrap">
                <table className="industry-ranking-table">
                  <thead>
                    <tr>
                      <th>观察序号</th><th>行业</th><th>近期速度</th><th>当前数量</th><th>占比</th>
                      <th>较上一节点</th><th>近 4 节点变化</th><th>状态</th><th>股票明细</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.ranking.slice(0, 15).map(row => (
                      <tr key={row.code} className={selectedIndustry === row.code ? "selected" : ""}>
                        <td><b className={row.rotation_rank <= 3 ? "top-rank rank" : "rank"}>{row.rotation_rank}</b></td>
                        <td>
                          <button type="button" onClick={() => selectPreview(row.code, data.resolved_end_date)}>
                            {row.name}<small>当前绝对排名 {row.current_rank}</small>
                          </button>
                        </td>
                        <td className={movementClass(row.recent_slope)}>
                          <strong>{signed(row.recent_slope, 2)}</strong> 只/点
                        </td>
                        <td><strong>{row.current_count}</strong> 只</td>
                        <td>{row.current_percent.toFixed(0)}%</td>
                        <td className={movementClass(row.change_previous)}>{signed(row.change_previous)}</td>
                        <td className={movementClass(row.recent_change)}>{signed(row.recent_change)}</td>
                        <td>
                          <span className="industry-status" title={`${row.status_detail}；${data.rules.slope_explanation}`}>
                            {row.status}<small>{signed(row.recent_slope, 2)} 只/点</small>
                          </span>
                        </td>
                        <td>
                          <button className="stock-detail-button" type="button" onClick={() => selectPreview(row.code, data.resolved_end_date)}>
                            查看 {row.current_count} 只
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {selectedRow ? (
                <div className="industry-stock-detail" data-testid="industry-stock-detail">
                  <div>
                    <span>当前截面入选股票</span>
                    <b>{selectedRow.name} · {selectedRow.current_count} 只</b>
                  </div>
                  <div>
                    {selectedRow.stocks.length
                      ? selectedRow.stocks.map(stock => (
                        <span key={stock.ts_code}><b>{stock.name}</b>{stock.code}<em>{stock.score.toFixed(1)}</em></span>
                      ))
                      : <p>当前截面无入选股票。</p>}
                  </div>
                </div>
              ) : null}
            </section>

            <footer className="industry-data-foot">
              <span>真实行业数：{data.scope.industry_count}</span>
              <span>采样节点：{data.sampling.sample_count}</span>
              <span>展示筛选：12 个活跃行业（不改变底层 31 行业）</span>
              <span>行情截止：{formatDate(data.as_of.daily)}</span>
              <span>
                本次读取：
                {data.client_cache_hit
                  ? "浏览器内存即时复用"
                  : `${((data.http_ms ?? data.elapsed_ms) / 1000).toFixed(1)} 秒`}
                {!data.client_cache_hit && data.cache_hit ? " · 服务端缓存" : ""}
              </span>
              {!data.client_cache_hit && !data.cache_hit ? <span>冷计算：{(data.elapsed_ms / 1000).toFixed(1)} 秒</span> : null}
            </footer>
          </>
        ) : null}
      </main>
    </div>
  );
}

function Metric({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note?: string;
  tone?: "rise" | "fall" | "secondary";
}) {
  return <article className={tone ? `metric-${tone}` : ""}><span>{label}</span><strong>{value}</strong>{note ? <small>{note}</small> : null}</article>;
}

function InfoTip({ label, text }: { label: string; text: string }) {
  const [open, setOpen] = useState(false);
  const tipId = useId();
  const wrapperRef = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (!wrapperRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [open]);
  return (
    <span
      ref={wrapperRef}
      className={`industry-info-tip ${open ? "open" : ""}`}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => {
        if (!wrapperRef.current?.contains(document.activeElement)) setOpen(false);
      }}
      onBlur={event => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-describedby={open ? tipId : undefined}
        onFocus={() => setOpen(true)}
        onClick={() => setOpen(true)}
        onKeyDown={event => {
          if (event.key === "Escape") {
            event.preventDefault();
            setOpen(false);
            event.currentTarget.blur();
          }
        }}
      >
        <CircleHelp aria-hidden="true" />
      </button>
      <span id={tipId} className="industry-info-popover" role="tooltip">{text}</span>
    </span>
  );
}

function HeatTimeAxis({ dates }: { dates: string[] }) {
  const labels = new Set([0, 5, 10, 15, 20, Math.max(0, dates.length - 1)]);
  return (
    <div className="heat-time-axis" aria-label="热力图时间轴">
      <span className="heat-axis-title">行业 · 近期速度</span>
      {dates.map((date, index) => labels.has(index) ? (
        <time key={date} style={{ gridColumn: index + 2 }}>
          {index === 0 ? "最新 " : ""}{formatDate(date).slice(5)}
        </time>
      ) : null)}
    </div>
  );
}

function HeatmapRow({
  row,
  dates,
  selectedIndustry,
  selectedDate,
  onPreview,
}: {
  row: IndustryStrengthRow;
  dates: string[];
  selectedIndustry: string;
  selectedDate: string;
  onPreview: (industryCode: string, date: string) => void;
}) {
  const pointsByDate = new Map(row.points.map(point => [point.date, point]));
  const latestDate = row.points.at(-1)?.date || "";
  const previewLatest = () => onPreview(row.code, latestDate);
  return (
    <>
      <button
        className={`heat-row-label ${selectedIndustry === row.code ? "selected" : ""}`}
        type="button"
        onMouseEnter={previewLatest}
        onFocus={previewLatest}
        onClick={previewLatest}
        aria-label={`${row.name} ${row.status} 近期速度${signed(row.recent_slope, 2)}只每采样点`}
      >
        <span><b>{row.name}</b><small>{row.status}</small></span>
        <em className={movementClass(row.recent_slope)}>{signed(row.recent_slope, 2)}</em>
      </button>
      {dates.map(date => {
        const point = pointsByDate.get(date);
        if (!point) return <span className="heat-cell heat-missing" key={date}>—</span>;
        const preview = () => onPreview(row.code, point.date);
        return (
          <button
            key={point.date}
            type="button"
            className={`heat-cell heat-${point.heat_level} ${selectedIndustry === row.code && selectedDate === point.date ? "selected" : ""}`}
            aria-label={`${row.name} ${formatDate(point.date, "-")} ${point.count}只 ${point.percent.toFixed(0)}% 较上期${signed(point.change)}`}
            title={`${row.name} · ${formatDate(point.date, "-")} · ${point.count}只 / ${point.percent.toFixed(0)}% · 较上期${signed(point.change)}`}
            onMouseEnter={preview}
            onFocus={preview}
            onClick={preview}
          >
            {point.count}
          </button>
        );
      })}
    </>
  );
}

function MiniTrend({ row }: { row: IndustryStrengthRow }) {
  const width = 260;
  const height = 66;
  const max = Math.max(10, ...row.counts);
  const x = (index: number) => 4 + index / Math.max(1, row.counts.length - 1) * (width - 8);
  const y = (value: number) => 4 + (1 - value / max) * (height - 8);
  return (
    <div className="industry-mini-trend">
      <span>完整 24 节点</span>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${row.name}完整24节点走势`}>
        <polyline points={row.counts.map((value, index) => `${x(index)},${y(value)}`).join(" ")} />
        <circle cx={x(row.counts.length - 1)} cy={y(row.current_count)} r="3.5" />
      </svg>
    </div>
  );
}

function PointDetail({ row, point }: { row: IndustryStrengthRow; point: IndustryStrengthPoint }) {
  const shownStocks = point.stocks.slice(0, 8);
  return (
    <div className="industry-point-detail" aria-live="polite" data-testid="industry-point-detail">
      <div className="point-detail-title">
        <span>悬停预览 · {formatDate(point.date, "-")}</span>
        <b>{row.name}</b>
        <em>{row.status} · {signed(row.recent_slope, 2)} 只/点</em>
      </div>
      <MiniTrend row={row} />
      <dl>
        <div><dt>当前数量 / 占比</dt><dd>{row.current_count} 只 / {row.current_percent.toFixed(0)}%</dd></div>
        <div><dt>悬停日期</dt><dd>{point.count} 只 · 较上期 {signed(point.change)}</dd></div>
        <div><dt>近 4 点变化</dt><dd className={movementClass(row.recent_change)}>{signed(row.recent_change)} 只</dd></div>
      </dl>
      <div className="point-stock-list">
        <strong>当日入选 {point.stocks.length} 只</strong>
        {shownStocks.length
          ? shownStocks.map(stock => <span key={stock.ts_code}>{stock.name} <small>{stock.code}</small></span>)
          : <span className="muted">当日无入选股票</span>}
        {point.stocks.length > shownStocks.length ? <small>另有 {point.stocks.length - shownStocks.length} 只</small> : null}
      </div>
    </div>
  );
}

function TrendChart({
  rows,
  allRows,
  dates,
  selectedCode,
  onSelect,
}: {
  rows: IndustryStrengthRow[];
  allRows: IndustryStrengthRow[];
  dates: string[];
  selectedCode: string;
  onSelect: (code: string) => void;
}) {
  const [highlightedCode, setHighlightedCode] = useState<string | null>(null);
  const [hoveredIndex, setHoveredIndex] = useState(Math.max(0, dates.length - 1));

  const highlightedRow = highlightedCode
    ? rows.find(row => row.code === highlightedCode) || null
    : null;
  const max = Math.max(10, ...rows.flatMap(row => row.counts));
  const width = 920;
  const height = 300;
  const left = 42;
  const right = 14;
  const top = 18;
  const bottom = 40;
  const innerWidth = width - left - right;
  const innerHeight = height - top - bottom;
  const x = (index: number) => left + index / Math.max(1, dates.length - 1) * innerWidth;
  const y = (value: number) => top + innerHeight - value / max * innerHeight;
  const updateHoveredDate = (event: ReactPointerEvent<SVGSVGElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const viewX = (event.clientX - bounds.left) / Math.max(1, bounds.width) * width;
    const index = Math.round((viewX - left) / Math.max(1, innerWidth) * (dates.length - 1));
    setHoveredIndex(Math.max(0, Math.min(dates.length - 1, index)));
  };
  const hoveredValue = highlightedRow?.counts[hoveredIndex] ?? 0;
  const labelX = Math.min(width - 258, Math.max(left + 6, x(hoveredIndex) + 8));
  const labelY = Math.max(4, Math.min(height - 64, y(hoveredValue) - 50));

  return (
    <div className="trend-layout">
      <div className="trend-chart-wrap">
        <div className="trend-focus-summary" aria-live="polite">
          {highlightedRow ? (
            <>
              <b>{highlightedRow.name}</b>
              <span>当前 {highlightedRow.current_count}</span>
              <span>{formatDate(dates[hoveredIndex] || "", "-")} · {hoveredValue}</span>
            </>
          ) : (
            <>
              <b>全部行业</b>
              <span>当前 {rows.length} 条线同等显示</span>
              <span>悬停或键盘聚焦后查看单线数值</span>
            </>
          )}
        </div>
        <div className="trend-legend" aria-label="当前显示行业">
          {rows.map((row, index) => (
            <button
              type="button"
              key={row.code}
              className={highlightedCode === row.code ? "active" : ""}
              onMouseEnter={() => setHighlightedCode(row.code)}
              onFocus={() => setHighlightedCode(row.code)}
              onMouseLeave={() => setHighlightedCode(null)}
              onBlur={() => setHighlightedCode(null)}
              onClick={() => onSelect(row.code)}
            >
              <i style={{ background: lineColors[index] }} />{row.name}<small>{row.current_count}</small>
            </button>
          ))}
        </div>
        <svg
          className="industry-trend-chart"
          data-focus-mode={highlightedCode ? "single" : "all"}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="行业24个采样点趋势，悬停或聚焦线条可高亮"
          onPointerMove={updateHoveredDate}
          onPointerLeave={() => {
            setHighlightedCode(null);
            setHoveredIndex(Math.max(0, dates.length - 1));
          }}
        >
          {[0, .25, .5, .75, 1].map(ratio => (
            <g key={ratio}>
              <line x1={left} x2={width - right} y1={top + innerHeight * ratio} y2={top + innerHeight * ratio} />
              <text x={left - 7} y={top + innerHeight * ratio + 4}>{Math.round(max * (1 - ratio))}</text>
            </g>
          ))}
          {rows.map((row, rowIndex) => {
            const points = row.counts.map((value, index) => `${x(index)},${y(value)}`).join(" ");
            const active = highlightedCode === row.code;
            const muted = highlightedCode !== null && !active;
            return (
              <g
                key={row.code}
                className={`trend-series ${active ? "active" : ""} ${muted ? "muted" : ""}`}
                style={{ color: lineColors[rowIndex] }}
              >
                <polyline className="trend-visible-line" points={points} />
                <polyline
                  className="trend-hit-line"
                  points={points}
                  tabIndex={0}
                  aria-label={`${row.name}，当前${row.current_count}，近期速度${signed(row.recent_slope, 2)}`}
                  onPointerEnter={() => setHighlightedCode(row.code)}
                  onPointerLeave={() => setHighlightedCode(null)}
                  onFocus={() => setHighlightedCode(row.code)}
                  onBlur={() => setHighlightedCode(null)}
                  onKeyDown={event => {
                    if (event.key === "Enter") onSelect(row.code);
                  }}
                />
                {active ? row.counts.map((value, index) => (
                  <circle key={dates[index]} cx={x(index)} cy={y(value)} r={index === hoveredIndex ? "4.4" : "2.8"} />
                )) : null}
              </g>
            );
          })}
          {highlightedRow ? (
            <g className="trend-direct-label" transform={`translate(${labelX} ${labelY})`}>
              <rect width="250" height="44" rx="6" />
              <text x="10" y="18">{highlightedRow.name} · 当前 {highlightedRow.current_count}</text>
              <text x="10" y="36">{formatDate(dates[hoveredIndex] || "", "-")} · {hoveredValue}</text>
            </g>
          ) : null}
          {dates.map((date, index) => index % 5 === 0 || index === dates.length - 1 ? (
            <text key={date} className="trend-date" x={x(index)} y={height - 8}>{formatDate(date).slice(5)}</text>
          ) : null)}
        </svg>
      </div>
      <IndustrySelector rows={allRows} selectedCode={selectedCode} onSelect={onSelect} />
    </div>
  );
}

function IndustrySelector({
  rows,
  selectedCode,
  onSelect,
}: {
  rows: IndustryStrengthRow[];
  selectedCode: string;
  onSelect: (code: string) => void;
}) {
  const selectedIndex = Math.max(0, rows.findIndex(row => row.code === selectedCode));
  const [cursor, setCursor] = useState(selectedIndex);
  const cursorRef = useRef(selectedIndex);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const move = (delta: number, commit: boolean) => {
    const next = Math.max(0, Math.min(rows.length - 1, cursorRef.current + delta));
    cursorRef.current = next;
    setCursor(next);
    itemRefs.current[next]?.scrollIntoView({ block: "nearest" });
    if (commit && rows[next]) onSelect(rows[next].code);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      move(event.key === "ArrowDown" ? 1 : -1, false);
    } else if (event.key === "Enter" && rows[cursorRef.current]) {
      event.preventDefault();
      onSelect(rows[cursorRef.current].code);
    }
  };
  const onWheel = (event: WheelEvent<HTMLDivElement>) => {
    if (event.deltaY === 0) return;
    event.preventDefault();
    const current = Math.max(0, rows.findIndex(row => row.code === selectedCode));
    const next = Math.max(0, Math.min(rows.length - 1, current + (event.deltaY > 0 ? 1 : -1)));
    cursorRef.current = next;
    setCursor(next);
    itemRefs.current[next]?.scrollIntoView({ block: "nearest" });
    if (rows[next]) onSelect(rows[next].code);
  };

  return (
    <aside className="industry-selector">
      <div>
        <span>全部一级行业</span>
        <b>选择并聚焦</b>
        <small>滚轮浏览 · ↑↓ 后按 Enter</small>
      </div>
      <div
        className="industry-selector-list"
        role="listbox"
        aria-label="行业选择器"
        data-cursor={cursor}
        tabIndex={0}
        aria-activedescendant={rows[cursor] ? `industry-option-${rows[cursor].code}` : undefined}
        onKeyDown={onKeyDown}
        onWheelCapture={onWheel}
      >
        {rows.map((row, index) => (
          <button
            id={`industry-option-${row.code}`}
            ref={node => { itemRefs.current[index] = node; }}
            role="option"
            aria-selected={row.code === selectedCode}
            type="button"
            key={row.code}
            className={`${row.code === selectedCode ? "selected" : ""} ${index === cursor ? "cursor" : ""}`}
            onMouseEnter={() => {
              cursorRef.current = index;
              setCursor(index);
            }}
            onClick={() => onSelect(row.code)}
          >
            <span><b>{row.name}</b><small>{row.status}</small></span>
            <em className={movementClass(row.recent_slope)}>{signed(row.recent_slope, 2)}</em>
          </button>
        ))}
      </div>
    </aside>
  );
}
