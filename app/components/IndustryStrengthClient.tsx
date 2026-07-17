"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  CalendarDays,
  ChevronDown,
  ChevronUp,
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

const lineColors = ["#1ca87a", "#285cf5", "#8554e8", "#d28b00", "#ed3f43"];

function inputDate(value: string) {
  return value ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}` : "";
}

function signed(value: number, suffix = "") {
  return `${value > 0 ? "+" : ""}${value}${suffix}`;
}

export function IndustryStrengthClient() {
  const [pattern, setPattern] = useState<PatternKey>("breakout");
  const [endDate, setEndDate] = useState("");
  const [data, setData] = useState<IndustryStrengthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [selectedIndustry, setSelectedIndustry] = useState("");
  const [selectedDate, setSelectedDate] = useState("");
  const heatScrollRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async (nextPattern: PatternKey, nextEndDate?: string) => {
    setLoading(true);
    setError("");
    try {
      const result = await api.industryStrength(nextPattern, nextEndDate);
      setData(result);
      setEndDate(inputDate(result.resolved_end_date));
      setExpanded(false);
      setSelectedIndustry(result.ranking[0]?.code || "");
      setSelectedDate(result.resolved_end_date);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "行业强弱数据加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load("breakout"), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const visibleRows = useMemo(() => {
    if (!data) return [];
    if (expanded) return data.industries;
    const visible = new Set(data.display.default_visible_codes);
    return data.industries.filter(row => visible.has(row.code));
  }, [data, expanded]);

  const selectedRow = useMemo(
    () => data?.ranking.find(row => row.code === selectedIndustry) || data?.ranking[0] || null,
    [data, selectedIndustry],
  );
  const selectedPoint = useMemo(
    () => selectedRow?.points.find(point => point.date === selectedDate)
      || selectedRow?.points.at(-1)
      || null,
    [selectedDate, selectedRow],
  );
  const trendRows = useMemo(() => {
    if (!data) return [];
    const rows = selectedRow ? [selectedRow] : [];
    for (const row of data.ranking) {
      if (rows.some(item => item.code === row.code)) continue;
      rows.push(row);
      if (rows.length === 5) break;
    }
    return rows;
  }, [data, selectedRow]);

  useEffect(() => {
    const node = heatScrollRef.current;
    if (!node || !data) return;
    const frame = window.requestAnimationFrame(() => {
      node.scrollLeft = node.scrollWidth - node.clientWidth;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [data, expanded]);

  return (
    <div className="app-shell industry-shell">
      <AppSidebar active="industry-strength" />
      <main className="industry-main">
        <header className="industry-page-head">
          <div>
            <span className="eyebrow"><Activity /> 市场结构</span>
            <h1>行业强弱</h1>
            <p>观察指定形态在申万一级行业中的集中、扩散与轮动。</p>
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
            <button type="button" disabled={loading} onClick={() => void load(pattern, endDate)}>
              {loading ? <LoaderCircle className="spin" /> : <RefreshCw />}
              刷新截面
            </button>
          </div>
        </header>

        <div className="fixed-scope" aria-label="固定统计口径">
          <span>Top 100</span>
          <span>申万一级行业</span>
          <span>过去 120 个交易日</span>
          <span>每 5 个交易日采样</span>
          <span>固定 24 个节点</span>
          <span>主板 · 剔除 ST</span>
        </div>

        {loading && !data ? (
          <section className="industry-loading" aria-live="polite">
            <LoaderCircle className="spin" />
            <h2>正在计算 24 个真实历史截面</h2>
            <p>首次计算会读取本地行情并执行形态评分，完成后同口径会命中缓存。</p>
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

            <section className="industry-metrics" aria-label="行业强弱概览">
              <Metric label="当前覆盖行业数" value={`${data.metrics.covered_industries}/${data.scope.industry_count}`} />
              <Metric label="最强行业" value={data.metrics.strongest_industry || "—"} note={`${data.metrics.strongest_count}%`} />
              <Metric label="近期增强最快" value={data.metrics.fastest_strengthening || "—"} note={signed(data.metrics.fastest_strengthening_change, " 只")} tone="up" />
              <Metric label="近期走弱最快" value={data.metrics.fastest_weakening || "—"} note={signed(data.metrics.fastest_weakening_change, " 只")} tone="down" />
              <Metric label="前三行业合计" value={`${data.metrics.top_three_percent.toFixed(0)}%`} note={data.metrics.concentration_state} />
              <Metric label="新进入前十" value={`${data.metrics.new_top_ten_count} 个`} note="较上一节点" />
            </section>

            <section className="industry-card analysis-card">
              <div className="industry-section-head">
                <div><span>自动分析</span><h2>{data.pattern_label} · {formatDate(data.resolved_end_date, "-")}</h2></div>
                <small>{data.rules.rapid_start_explanation}</small>
              </div>
              <div className="analysis-sentences">
                {data.analysis.map(item => <p key={item}>{item}</p>)}
              </div>
            </section>

            <section className="industry-card heatmap-card">
              <div className="industry-section-head">
                <div><span>一级行业历史热力图</span><h2>24 个固定采样节点</h2></div>
                <div className="heat-legend" aria-label="占比颜色图例">
                  {["0", "1–2%", "3–4%", "5–7%", "8–10%", "10%以上"].map((label, index) => (
                    <span key={label}><i className={`heat-${index}`} />{label}</span>
                  ))}
                </div>
              </div>
              <div className="industry-heat-scroll" ref={heatScrollRef}>
                <div className="industry-heat-grid">
                  <span className="heat-corner">行业 / 日期</span>
                  {data.sampling.dates.map(date => <time key={date}>{formatDate(date).slice(5)}</time>)}
                  {visibleRows.map(row => (
                    <HeatmapRow
                      key={row.code}
                      row={row}
                      selectedIndustry={selectedIndustry}
                      selectedDate={selectedDate}
                      onSelect={(industryCode, date) => {
                        setSelectedIndustry(industryCode);
                        setSelectedDate(date);
                      }}
                    />
                  ))}
                </div>
              </div>
              <button
                className="industry-fold-toggle"
                type="button"
                aria-expanded={expanded}
                onClick={() => setExpanded(value => !value)}
              >
                {expanded ? <ChevronUp /> : <ChevronDown />}
                {expanded
                  ? "收起为默认 16 个行业"
                  : `已折叠 ${data.display.folded_count} 个行业，本期合计占 Top 100 的 ${data.display.folded_current_percent.toFixed(0)}%，点击展开`}
              </button>
              {selectedRow && selectedPoint ? (
                <PointDetail row={selectedRow} point={selectedPoint} />
              ) : null}
            </section>

            <section className="industry-card trend-card">
              <div className="industry-section-head">
                <div><span>当前前 5 行业时间序列</span><h2>入选数量 / Top 100 占比</h2></div>
                <small>点击热力格可将行业加入对比焦点</small>
              </div>
              <TrendChart rows={trendRows} dates={data.sampling.dates} />
            </section>

            <section className="industry-card ranking-card">
              <div className="industry-section-head">
                <div><span>当前行业排名</span><h2>{formatDate(data.resolved_end_date, "-")} 收盘截面</h2></div>
                <small>数量与百分比一一对应，分母固定为 100</small>
              </div>
              <div className="industry-table-wrap">
                <table className="industry-ranking-table">
                  <thead>
                    <tr>
                      <th>排名</th><th>行业</th><th>入选数量</th><th>占比</th>
                      <th>较上一节点</th><th>近 4 个节点</th><th>状态</th><th>入选股票明细</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.ranking.map(row => (
                      <tr key={row.code} className={selectedIndustry === row.code ? "selected" : ""}>
                        <td><b className={row.rank <= 3 ? "top-rank rank" : "rank"}>{row.rank}</b></td>
                        <td><button type="button" onClick={() => {
                          setSelectedIndustry(row.code);
                          setSelectedDate(data.resolved_end_date);
                        }}>{row.name}<small>{row.code}</small></button></td>
                        <td><strong>{row.current_count}</strong> 只</td>
                        <td>{row.current_percent.toFixed(0)}%</td>
                        <td className={row.change_previous > 0 ? "up" : row.change_previous < 0 ? "down" : ""}>{signed(row.change_previous)}</td>
                        <td className={row.change_four_samples > 0 ? "up" : row.change_four_samples < 0 ? "down" : ""}>{signed(row.change_four_samples)}</td>
                        <td><span className={`industry-status status-${row.status}`}>{row.status}</span></td>
                        <td><button className="stock-detail-button" type="button" onClick={() => {
                          setSelectedIndustry(row.code);
                          setSelectedDate(data.resolved_end_date);
                        }}>查看 {row.current_count} 只</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {selectedRow ? (
                <div className="industry-stock-detail" data-testid="industry-stock-detail">
                  <div>
                    <span>入选股票明细</span>
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
              <span>行情截止：{formatDate(data.as_of.daily)}</span>
              <span>本次计算：{(data.elapsed_ms / 1000).toFixed(1)} 秒{data.cache_hit ? " · 已命中缓存" : ""}</span>
            </footer>
          </>
        ) : null}
      </main>
    </div>
  );
}

function Metric({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: "up" | "down" }) {
  return <article><span>{label}</span><strong>{value}</strong>{note ? <small className={tone}>{note}</small> : null}</article>;
}

function HeatmapRow({
  row,
  selectedIndustry,
  selectedDate,
  onSelect,
}: {
  row: IndustryStrengthRow;
  selectedIndustry: string;
  selectedDate: string;
  onSelect: (industryCode: string, date: string) => void;
}) {
  return (
    <>
      <button
        className={`heat-row-label ${selectedIndustry === row.code ? "selected" : ""}`}
        type="button"
        onClick={() => onSelect(row.code, row.points.at(-1)?.date || "")}
      >
        <b>{row.name}</b><small>累计 {row.cumulative_count}</small>
      </button>
      {row.points.map(point => (
        <button
          key={point.date}
          type="button"
          className={`heat-cell heat-${point.heat_level} ${selectedIndustry === row.code && selectedDate === point.date ? "selected" : ""}`}
          aria-label={`${row.name} ${formatDate(point.date, "-")} ${point.count}只 ${point.percent.toFixed(0)}% 较上期${signed(point.change)}`}
          title={`${row.name} · ${formatDate(point.date, "-")} · ${point.count}只 / ${point.percent.toFixed(0)}% · 较上期${signed(point.change)}`}
          onClick={() => onSelect(row.code, point.date)}
        >
          {point.count}
        </button>
      ))}
    </>
  );
}

function PointDetail({ row, point }: { row: IndustryStrengthRow; point: IndustryStrengthPoint }) {
  return (
    <div className="industry-point-detail" aria-live="polite" data-testid="industry-point-detail">
      <div><span>当前查看</span><b>{row.name} · {formatDate(point.date, "-")}</b></div>
      <dl>
        <div><dt>入选数量</dt><dd>{point.count} 只</dd></div>
        <div><dt>占 Top 100</dt><dd>{point.percent.toFixed(0)}%</dd></div>
        <div><dt>较上期</dt><dd className={point.change > 0 ? "up" : point.change < 0 ? "down" : ""}>{signed(point.change)} 只</dd></div>
      </dl>
      <div className="point-stock-list">
        {point.stocks.length
          ? point.stocks.map(stock => <span key={stock.ts_code}>{stock.name} <small>{stock.code}</small></span>)
          : <span className="muted">当日无入选股票</span>}
      </div>
    </div>
  );
}

function TrendChart({ rows, dates }: { rows: IndustryStrengthRow[]; dates: string[] }) {
  const max = Math.max(10, ...rows.flatMap(row => row.counts));
  const width = 920;
  const height = 230;
  const left = 42;
  const right = 12;
  const top = 14;
  const bottom = 32;
  const innerWidth = width - left - right;
  const innerHeight = height - top - bottom;
  const x = (index: number) => left + (dates.length <= 1 ? 0 : index / (dates.length - 1) * innerWidth);
  const y = (value: number) => top + innerHeight - value / max * innerHeight;
  return (
    <div className="trend-chart-wrap">
      <div className="trend-legend">
        {rows.map((row, index) => <span key={row.code}><i style={{ background: lineColors[index] }} />{row.name}</span>)}
      </div>
      <svg className="industry-trend-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="当前前五行业24个采样点趋势">
        {[0, .25, .5, .75, 1].map(ratio => (
          <g key={ratio}>
            <line x1={left} x2={width - right} y1={top + innerHeight * ratio} y2={top + innerHeight * ratio} />
            <text x={left - 7} y={top + innerHeight * ratio + 4}>{Math.round(max * (1 - ratio))}</text>
          </g>
        ))}
        {rows.map((row, rowIndex) => (
          <g key={row.code} style={{ color: lineColors[rowIndex] }}>
            <polyline points={row.counts.map((value, index) => `${x(index)},${y(value)}`).join(" ")} />
            {row.counts.map((value, index) => <circle key={dates[index]} cx={x(index)} cy={y(value)} r="2.8" />)}
          </g>
        ))}
        {dates.map((date, index) => index % 4 === 0 || index === dates.length - 1 ? (
          <text key={date} className="trend-date" x={x(index)} y={height - 8}>{formatDate(date).slice(5)}</text>
        ) : null)}
      </svg>
    </div>
  );
}
