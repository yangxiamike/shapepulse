"use client";

import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Check,
  Gauge,
  LoaderCircle,
  RotateCcw,
  TriangleAlert,
} from "lucide-react";
import { AppSidebar } from "./AppSidebar";
import styles from "./TemplateBreadthV3Client.module.css";

type ChangeWindow = 10 | 20;
type Point = {
  date: string;
  count?: number;
  top100_count?: number;
  eligible_count?: number;
  selection_rate?: number;
};
type IndustryStock = {
  ts_code: string;
  code?: string;
  name: string;
  industry?: string;
  industry_code?: string;
  score?: number;
  rank?: number;
};
type ChangeData = {
  comparison_date: string;
  new_count: number;
  retained_count: number;
  exit_count: number;
  net_change: number;
  new_stocks?: IndustryStock[];
  retained_stocks?: IndustryStock[];
  exit_stocks?: IndustryStock[];
};
type Industry = {
  industry_code: string;
  industry: string;
  top100_count: number;
  top100_share?: number;
  eligible_count?: number;
  selection_rate?: number;
  neutral?: boolean;
  component_industry_count?: number;
  component_industry_codes?: string[];
  changes?: Record<string, ChangeData>;
  change_5d?: number;
  new_count?: number;
  retained_count?: number;
  exit_count?: number;
  current_stocks?: IndustryStock[];
  stocks?: IndustryStock[];
  series?: Point[];
  components?: Array<{
    industry_code: string;
    industry: string;
    top100_count: number;
    eligible_count?: number;
    changes?: Record<string, ChangeData>;
    current_stocks?: IndustryStock[];
  }>;
};
type TemplateData = {
  key: string;
  label: string;
  cue: string;
  accent: string;
  summary?: { count: number; eligibleCount: number };
  top100?: IndustryStock[];
  topStocks?: IndustryStock[];
  industries: Industry[];
  treemap_industries?: Industry[];
  detail_url?: string;
  timeline_url?: string;
  layout_order?: string[];
  timeline?: {
    start_date: string;
    end_date: string;
    history_trading_days: number;
    trading_day_step: number;
    sampled_points: number;
    latest_always_included: boolean;
    anchor?: string;
  };
  industrySeries?: Array<{
    industryCode: string;
    industry: string;
    points: Point[];
  }>;
};
type TimelineSnapshot = {
  date: string;
  comparison_dates: Record<string, string>;
  treemap_industries: Industry[];
};
type TimelinePayload = {
  version: string;
  as_of: string;
  template_id: string;
  start_date: string;
  end_date: string;
  layout_order: string[];
  sampling: {
    history_trading_days: number;
    trading_day_step: number;
    sampled_points: number;
    latest_always_included: boolean;
    anchor?: string;
  };
  snapshots: TimelineSnapshot[];
};
type Payload = {
  asOf: string;
  historyStart?: string;
  warning?: string;
  defaultChangeWindow?: ChangeWindow;
  changeWindows?: ChangeWindow[];
  selection?: {
    topK?: number;
    comparisonTradingDays?: number[];
    industryRateDenominator?: string;
  };
  templates: TemplateData[];
};
type DetailPayload = {
  industries?: Industry[];
  details?: Industry[];
  other?: Industry;
  template?: { industries?: Industry[] };
};
type Rect = {
  item: Industry;
  x: number;
  y: number;
  width: number;
  height: number;
};

function date(value?: string | null) {
  const text = String(value || "").replaceAll("-", "");
  return text.length === 8
    ? `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6)}`
    : value || "—";
}

function stockCode(item: IndustryStock) {
  return item.code || item.ts_code.split(".")[0];
}

function changeFor(item: Industry | null | undefined, window: ChangeWindow): ChangeData {
  const current = item?.changes?.[String(window)];
  if (current) return current;
  return {
    comparison_date: "",
    new_count: item?.new_count || 0,
    retained_count: item?.retained_count || 0,
    exit_count: item?.exit_count || 0,
    net_change: window === 10 ? item?.change_5d || 0 : 0,
  };
}

function changeLabel(item: Industry, window: ChangeWindow) {
  if (item.neutral || item.industry_code === "other") return "中性聚合";
  const value = changeFor(item, window).net_change;
  if (value > 0) return `↑ 净扩张 +${value}只`;
  if (value < 0) return `↓ 净收缩 ${value}只`;
  return "— 持平 0只";
}

function worst(row: Array<{ item: Industry; area: number }>, side: number) {
  if (!row.length) return Infinity;
  const sum = row.reduce((total, entry) => total + entry.area, 0);
  const min = Math.min(...row.map(entry => entry.area));
  const max = Math.max(...row.map(entry => entry.area));
  const side2 = side * side;
  return Math.max(
    (side2 * max) / (sum * sum),
    (sum * sum) / (side2 * min),
  );
}

function squarify(
  items: Industry[],
  width: number,
  height: number,
  layoutOrder: string[] = [],
): Rect[] {
  const positions = new Map(
    layoutOrder.map((code, index) => [code, index]),
  );
  const weighted = items
    .filter(item => item.top100_count > 0)
    .sort(
      (a, b) =>
        (positions.get(a.industry_code) ?? Number.MAX_SAFE_INTEGER) -
          (positions.get(b.industry_code) ?? Number.MAX_SAFE_INTEGER) ||
        (layoutOrder.length
          ? a.industry.localeCompare(b.industry, "zh-CN")
          : b.top100_count - a.top100_count ||
            a.industry.localeCompare(b.industry, "zh-CN")),
    );
  const total = weighted.reduce((sum, item) => sum + item.top100_count, 0);
  if (!total || width <= 0 || height <= 0) return [];
  const pending = weighted.map(item => ({
    item,
    area: (item.top100_count / total) * width * height,
  }));
  const output: Rect[] = [];
  let box = { x: 0, y: 0, width, height };

  function layout(row: typeof pending) {
    const area = row.reduce((sum, entry) => sum + entry.area, 0);
    if (box.width >= box.height) {
      const rowWidth = area / Math.max(1, box.height);
      let y = box.y;
      row.forEach(entry => {
        const entryHeight = entry.area / Math.max(rowWidth, 0.001);
        output.push({
          item: entry.item,
          x: box.x,
          y,
          width: rowWidth,
          height: entryHeight,
        });
        y += entryHeight;
      });
      box = {
        x: box.x + rowWidth,
        y: box.y,
        width: Math.max(0, box.width - rowWidth),
        height: box.height,
      };
    } else {
      const rowHeight = area / Math.max(1, box.width);
      let x = box.x;
      row.forEach(entry => {
        const entryWidth = entry.area / Math.max(rowHeight, 0.001);
        output.push({
          item: entry.item,
          x,
          y: box.y,
          width: entryWidth,
          height: rowHeight,
        });
        x += entryWidth;
      });
      box = {
        x: box.x,
        y: box.y + rowHeight,
        width: box.width,
        height: Math.max(0, box.height - rowHeight),
      };
    }
  }

  let row: typeof pending = [];
  while (pending.length) {
    const next = pending[0];
    const side = Math.max(0.001, Math.min(box.width, box.height));
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

function detailRows(payload: DetailPayload) {
  const rows =
    payload.industries ||
    payload.details ||
    payload.template?.industries ||
    [];
  return payload.other &&
    !rows.some(item => item.industry_code === payload.other?.industry_code)
    ? [...rows, payload.other]
    : rows;
}

export function TemplateBreadthV3Client() {
  const mapRef = useRef<HTMLDivElement>(null);
  const detailCache = useRef(new Map<string, Industry[]>());
  const detailRequests = useRef(new Map<string, Promise<Industry[]>>());
  const detailLoadSequence = useRef(0);
  const timelineCache = useRef(new Map<string, TimelinePayload>());
  const timelineRequests = useRef(
    new Map<string, Promise<TimelinePayload>>(),
  );
  const timelineLoadSequence = useRef(0);
  const selectedKeyRef = useRef("");
  const [data, setData] = useState<Payload | null>(null);
  const [selectedKey, setSelectedKey] = useState("");
  const [selectedIndustry, setSelectedIndustry] = useState("");
  const [focusedIndustry, setFocusedIndustry] = useState("");
  const [changeWindow, setChangeWindow] = useState<ChangeWindow>(10);
  const [detailIndustries, setDetailIndustries] = useState<Industry[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [timeline, setTimeline] = useState<TimelinePayload | null>(null);
  const [timelineIndex, setTimelineIndex] = useState(0);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [timelineError, setTimelineError] = useState("");
  const [mapSize, setMapSize] = useState({ width: 1000, height: 560 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/template-breadth-v3.json", {
        cache: "force-cache",
      });
      if (!response.ok) throw new Error(`数据摘要返回 ${response.status}`);
      const payload = (await response.json()) as Payload;
      if (payload.templates?.length !== 4) {
        throw new Error("冻结四模板摘要不完整");
      }
      setData(payload);
      setChangeWindow(payload.defaultChangeWindow === 20 ? 20 : 10);
      setSelectedKey(key =>
        payload.templates.some(item => item.key === key)
          ? key
          : payload.templates[0].key,
      );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "本地 Top100 摘要读取失败",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    selectedKeyRef.current = selectedKey;
  }, [selectedKey]);

  useEffect(() => {
    const element = mapRef.current;
    if (!element) return;
    const update = () => {
      const box = element.getBoundingClientRect();
      if (box.width > 0 && box.height > 0) {
        setMapSize({ width: box.width, height: box.height });
      }
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [data, selectedKey]);

  const template = useMemo(
    () =>
      data?.templates.find(item => item.key === selectedKey) ||
      data?.templates[0] ||
      null,
    [data, selectedKey],
  );
  const loadTimeline = useCallback(async (item: TemplateData) => {
    const templateKey = item.key;
    const sequence = ++timelineLoadSequence.current;
    setTimelineError("");
    const cached = timelineCache.current.get(templateKey);
    if (cached) {
      if (
        sequence === timelineLoadSequence.current &&
        selectedKeyRef.current === templateKey
      ) {
        setTimeline(cached);
        setTimelineIndex(Math.max(0, cached.snapshots.length - 1));
      }
      return;
    }
    if (!item.timeline_url) {
      setTimeline(null);
      setTimelineError("该模板缺少历史时间轴地址");
      return;
    }
    setTimelineLoading(true);
    try {
      let pending = timelineRequests.current.get(templateKey);
      if (!pending) {
        pending = fetch(item.timeline_url, { cache: "force-cache" })
          .then(async response => {
            if (!response.ok) {
              throw new Error(`历史时间轴返回 ${response.status}`);
            }
            const payload = (await response.json()) as TimelinePayload;
            if (
              payload.template_id !== templateKey ||
              !payload.snapshots?.length
            ) {
              throw new Error("历史时间轴与当前模板不匹配");
            }
            timelineCache.current.set(templateKey, payload);
            return payload;
          })
          .finally(() => timelineRequests.current.delete(templateKey));
        timelineRequests.current.set(templateKey, pending);
      }
      const payload = await pending;
      if (
        sequence === timelineLoadSequence.current &&
        selectedKeyRef.current === templateKey
      ) {
        setTimeline(payload);
        setTimelineIndex(Math.max(0, payload.snapshots.length - 1));
      }
    } catch (reason) {
      if (
        sequence === timelineLoadSequence.current &&
        selectedKeyRef.current === templateKey
      ) {
        setTimeline(null);
        setTimelineError(
          reason instanceof Error ? reason.message : "历史时间轴加载失败",
        );
      }
    } finally {
      if (
        sequence === timelineLoadSequence.current &&
        selectedKeyRef.current === templateKey
      ) {
        setTimelineLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (!template) return;
    const timer = window.setTimeout(
      () => void loadTimeline(template),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [loadTimeline, template]);

  const activeSnapshot =
    timeline && timeline.template_id === template?.key
      ? timeline.snapshots[timelineIndex] ||
        timeline.snapshots.at(-1) ||
        null
      : null;
  const viewDate = activeSnapshot?.date || data?.asOf || "";
  const isLatestDate = Boolean(data && viewDate === data.asOf);
  const mapIndustries = useMemo(
    () =>
      activeSnapshot?.treemap_industries ||
      template?.treemap_industries ||
      template?.industries ||
      [],
    [activeSnapshot, template],
  );
  const rects = useMemo(
    () =>
      squarify(
        mapIndustries,
        mapSize.width,
        mapSize.height,
        timeline?.layout_order || template?.layout_order || [],
      ),
    [mapIndustries, mapSize, template?.layout_order, timeline?.layout_order],
  );
  const selectedSummary = useMemo(
    () =>
      mapIndustries.find(item => item.industry_code === selectedIndustry) ||
      null,
    [mapIndustries, selectedIndustry],
  );
  const selectedDetail = useMemo(
    () =>
      detailIndustries.find(
        item => item.industry_code === selectedIndustry,
      ) || null,
    [detailIndustries, selectedIndustry],
  );
  const selected = isLatestDate
    ? selectedDetail || selectedSummary
    : selectedSummary;
  const focusItem = useMemo(
    () =>
      mapIndustries.find(
        item => item.industry_code === (focusedIndustry || selectedIndustry),
      ) ||
      mapIndustries[0] ||
      null,
    [focusedIndustry, mapIndustries, selectedIndustry],
  );
  const widest = useMemo(
    () =>
      [...mapIndustries].sort(
        (a, b) => b.top100_count - a.top100_count,
      )[0],
    [mapIndustries],
  );
  const largestExpansion = useMemo(
    () =>
      [...mapIndustries]
        .filter(item => !item.neutral && item.industry_code !== "other")
        .sort(
          (a, b) =>
            changeFor(b, changeWindow).net_change -
            changeFor(a, changeWindow).net_change,
        )
        .find(item => changeFor(item, changeWindow).net_change > 0),
    [changeWindow, mapIndustries],
  );
  const largestContraction = useMemo(
    () =>
      [...mapIndustries]
        .filter(item => !item.neutral && item.industry_code !== "other")
        .sort(
          (a, b) =>
            changeFor(a, changeWindow).net_change -
            changeFor(b, changeWindow).net_change,
        )
        .find(item => changeFor(item, changeWindow).net_change < 0),
    [changeWindow, mapIndustries],
  );
  const comparisonDate =
    mapIndustries
      .map(item => changeFor(item, changeWindow).comparison_date)
      .find(Boolean) || "";
  const mapTotal = mapIndustries.reduce(
    (sum, item) => sum + item.top100_count,
    0,
  );

  const selectIndustry = useCallback(
    async (item: Industry) => {
      if (!template) return;
      const templateKey = template.key;
      const sequence = ++detailLoadSequence.current;
      setSelectedIndustry(item.industry_code);
      setFocusedIndustry(item.industry_code);
      setDetailError("");
      if (!isLatestDate) {
        setDetailLoading(false);
        return;
      }
      const cached = detailCache.current.get(templateKey);
      if (cached) {
        if (
          sequence === detailLoadSequence.current &&
          selectedKeyRef.current === templateKey
        ) {
          setDetailIndustries(cached);
        }
        return;
      }
      if (!template.detail_url) {
        const inline = template.industries || [];
        detailCache.current.set(templateKey, inline);
        if (
          sequence === detailLoadSequence.current &&
          selectedKeyRef.current === templateKey
        ) {
          setDetailIndustries(inline);
        }
        return;
      }
      setDetailLoading(true);
      try {
        let pending = detailRequests.current.get(templateKey);
        if (!pending) {
          pending = fetch(template.detail_url, { cache: "force-cache" })
            .then(async response => {
              if (!response.ok) {
                throw new Error(`行业明细返回 ${response.status}`);
              }
              const rows = detailRows(
                (await response.json()) as DetailPayload,
              );
              if (!rows.length) throw new Error("行业明细为空");
              detailCache.current.set(templateKey, rows);
              return rows;
            })
            .finally(() => detailRequests.current.delete(templateKey));
          detailRequests.current.set(templateKey, pending);
        }
        const rows = await pending;
        if (
          sequence === detailLoadSequence.current &&
          selectedKeyRef.current === templateKey
        ) {
          setDetailIndustries(rows);
        }
      } catch (reason) {
        if (
          sequence === detailLoadSequence.current &&
          selectedKeyRef.current === templateKey
        ) {
          setDetailError(
            reason instanceof Error ? reason.message : "行业明细加载失败",
          );
        }
      } finally {
        if (
          sequence === detailLoadSequence.current &&
          selectedKeyRef.current === templateKey
        ) {
          setDetailLoading(false);
        }
      }
    },
    [isLatestDate, template],
  );

  const previousLatest = useRef(true);
  useEffect(() => {
    const returnedToLatest = isLatestDate && !previousLatest.current;
    previousLatest.current = isLatestDate;
    if (returnedToLatest && selectedSummary) {
      void selectIndustry(selectedSummary);
    }
  }, [isLatestDate, selectIndustry, selectedSummary]);

  function switchTemplate(key: string) {
    ++detailLoadSequence.current;
    ++timelineLoadSequence.current;
    selectedKeyRef.current = key;
    setSelectedKey(key);
    setSelectedIndustry("");
    setFocusedIndustry("");
    setDetailIndustries(detailCache.current.get(key) || []);
    setDetailError("");
    setDetailLoading(false);
    const cachedTimeline = timelineCache.current.get(key) || null;
    setTimeline(cachedTimeline);
    setTimelineIndex(
      cachedTimeline ? Math.max(0, cachedTimeline.snapshots.length - 1) : 0,
    );
    setTimelineError("");
    setTimelineLoading(!cachedTimeline);
  }

  const chooseTimelineIndex = useCallback(
    (nextIndex: number) => {
      if (!timeline?.snapshots.length) return;
      const clamped = Math.max(
        0,
        Math.min(nextIndex, timeline.snapshots.length - 1),
      );
      const nextSnapshot = timeline.snapshots[clamped];
      setTimelineIndex(clamped);
      if (!data || nextSnapshot.date === data.asOf) return;
      ++detailLoadSequence.current;
      setDetailLoading(false);
      setDetailError("");
    },
    [data, timeline],
  );

  return (
    <div className={`app-shell ${styles.shell}`}>
      <AppSidebar active="template-breadth-v3" />
      <main
        className={styles.main}
        style={{ "--accent": template?.accent || "#138563" } as CSSProperties}
      >
        <header className={styles.pageHead}>
          <div>
            <span>
              <Gauge aria-hidden="true" /> 每模板每日固定 Top100
            </span>
            <h1>Top100 行业宽度</h1>
            <p>
              面积只看当日入选数量；颜色和文字看相对 10 或 20
              个实际交易日前的净变化。
            </p>
          </div>
          {data ? (
            <time>
              {isLatestDate ? "最新交易日" : "回溯交易日"} {date(viewDate)}
            </time>
          ) : null}
        </header>

        {loading ? (
          <State
            title="正在读取本地 Top100 摘要"
            text="先显示轻量行业摘要，股票与时间序列在点击后读取。"
          />
        ) : error ? (
          <State
            title="Top100 数据暂不可用"
            text={error}
            action={
              <button onClick={() => void load()}>
                <RotateCcw aria-hidden="true" />
                重试
              </button>
            }
          />
        ) : template && data ? (
          <>
            <nav className={styles.tabs} aria-label="冻结四模板切换">
              {data.templates.map(item => (
                <button
                  key={item.key}
                  className={item.key === template.key ? styles.active : ""}
                  aria-pressed={item.key === template.key}
                  onClick={() => switchTemplate(item.key)}
                >
                  <i style={{ background: item.accent }} />
                  <span>
                    <strong>{item.label}</strong>
                    <small>{item.cue}</small>
                  </span>
                </button>
              ))}
            </nav>

            <section
              className={styles.summary}
              aria-label={`${template.label} Top100 行业摘要`}
            >
              <article>
                <span>当前模板</span>
                <strong>{template.label}</strong>
                <small>冻结定义 · 本模板内独立 Pearson 排名</small>
              </article>
              <article>
                <span>最宽行业块</span>
                <strong>
                  {widest
                    ? `${widest.industry} ${widest.top100_count}只`
                    : "—"}
                </strong>
                <small>面积只由所选日期 Top100 数量决定</small>
              </article>
              <article>
                <span>{changeWindow}日净扩张最多</span>
                <strong>
                  {largestExpansion
                    ? `${largestExpansion.industry} +${
                        changeFor(largestExpansion, changeWindow).net_change
                      }只`
                    : "无净扩张"}
                </strong>
                <small>仅描述行业数量变化，不作预测结论</small>
              </article>
              <article>
                <span>{changeWindow}日净收缩最多</span>
                <strong>
                  {largestContraction
                    ? `${largestContraction.industry} ${
                        changeFor(largestContraction, changeWindow).net_change
                      }只`
                    : "无净收缩"}
                </strong>
                <small>退出不计入当前块面积</small>
              </article>
            </section>

            <div className={styles.workspace}>
              <section className={styles.mapCard}>
                <div className={styles.sectionHead}>
                  <div>
                    <span>所选日期宽度 · 申万一级行业</span>
                    <h2>Top100 行业空间</h2>
                    <p>
                      面积 = {date(viewDate)} 当日 Top100 行业数量（只）；
                      颜色 = 相对 {changeWindow} 个实际交易日前净变化。
                    </p>
                  </div>
                  <small>
                    {date(viewDate)} vs {date(comparisonDate)} ·
                    当日合计 {mapTotal}只
                  </small>
                </div>
                <div className={styles.legend}>
                  <span>
                    <i className={styles.legendArea} />
                    面积：当前数量
                  </span>
                  <span>
                    <i className={styles.legendExpand} />红 ↑ 净扩张
                  </span>
                  <span>
                    <i className={styles.legendContract} />绿 ↓ 净收缩
                  </span>
                  <span>
                    <i className={styles.legendNeutral} />灰 — 持平 /
                    其他行业
                  </span>
                </div>
                <div
                  ref={mapRef}
                  className={[
                    styles.treemap,
                    timeline ? styles.treemapAnimated : "",
                  ].join(" ")}
                  role="group"
                  aria-label={`${template.label} Top100 行业矩形树图`}
                  data-total={mapTotal}
                >
                  {rects.map(rect => {
                    const industry = rect.item;
                    const change = changeFor(industry, changeWindow);
                    const direction =
                      industry.neutral || industry.industry_code === "other"
                        ? "neutral"
                        : change.net_change > 0
                          ? "expand"
                          : change.net_change < 0
                            ? "contract"
                            : "neutral";
                    const enoughForThreeLines =
                      rect.width >= 118 && rect.height >= 72;
                    const enoughForName =
                      rect.width >= 64 && rect.height >= 44;
                    const otherText =
                      industry.industry_code === "other"
                        ? `${industry.component_industry_count || 0}个行业`
                        : changeLabel(industry, changeWindow);
                    return (
                      <button
                        key={industry.industry_code}
                        type="button"
                        className={[
                          styles.mapBlock,
                          styles[direction],
                          industry.industry_code === selectedIndustry
                            ? styles.selected
                            : "",
                        ].join(" ")}
                        style={{
                          left: `${rect.x}px`,
                          top: `${rect.y}px`,
                          width: `${rect.width}px`,
                          height: `${rect.height}px`,
                        }}
                        data-direction={direction}
                        data-industry-code={industry.industry_code}
                        data-count={industry.top100_count}
                        title={`${industry.industry}｜当日 ${industry.top100_count}只｜${otherText}｜${date(viewDate)} vs ${date(change.comparison_date)}`}
                        aria-label={`${industry.industry}，当日 Top100 ${industry.top100_count}只，${otherText}，点击查看行业统计`}
                        aria-pressed={
                          industry.industry_code === selectedIndustry
                        }
                        onMouseEnter={() =>
                          setFocusedIndustry(industry.industry_code)
                        }
                        onFocus={() =>
                          setFocusedIndustry(industry.industry_code)
                        }
                        onClick={() => void selectIndustry(industry)}
                      >
                        {enoughForName ? (
                          <strong>{industry.industry}</strong>
                        ) : null}
                        <b>{industry.top100_count}只</b>
                        {enoughForThreeLines ? (
                          <small>{otherText}</small>
                        ) : null}
                        {industry.industry_code === selectedIndustry ? (
                          <Check
                            className={styles.selectedMark}
                            aria-hidden="true"
                          />
                        ) : null}
                      </button>
                    );
                  })}
                </div>
                <Timeline
                  payload={timeline}
                  index={timelineIndex}
                  loading={timelineLoading}
                  error={timelineError}
                  onChange={chooseTimelineIndex}
                  onRetry={() => template && void loadTimeline(template)}
                />
                {focusItem ? (
                  <div className={styles.focusStrip}>
                    <strong>{focusItem.industry}</strong>
                    <span>{date(viewDate)} · {focusItem.top100_count}只</span>
                    <span>{changeLabel(focusItem, changeWindow)}</span>
                    {focusItem.industry_code === "other" ? (
                      <span>
                        合计 {focusItem.top100_count}只 ·{" "}
                        {focusItem.component_industry_count || 0}个行业
                      </span>
                    ) : (
                      <span>
                        入选率{" "}
                        {focusItem.eligible_count
                          ? `${(
                              (focusItem.top100_count /
                                focusItem.eligible_count) *
                              100
                            ).toFixed(1)}%（${focusItem.top100_count}/${focusItem.eligible_count}）`
                          : "—（当日可选数缺失）"}
                      </span>
                    )}
                  </div>
                ) : null}
              </section>

              <aside className={styles.changeCard}>
                <div className={styles.sectionHead}>
                  <div>
                    <span>最近变化 · 实际交易日</span>
                    <h2>行业净扩张 / 收缩</h2>
                    <p>切换窗口只改变变化口径，不改变 Treemap 面积。</p>
                  </div>
                  <div
                    className={styles.windowSwitch}
                    role="group"
                    aria-label="行业变化窗口"
                  >
                    {([10, 20] as ChangeWindow[]).map(value => (
                      <button
                        type="button"
                        key={value}
                        className={
                          changeWindow === value ? styles.windowActive : ""
                        }
                        aria-pressed={changeWindow === value}
                        onClick={() => setChangeWindow(value)}
                      >
                        {value}日
                      </button>
                    ))}
                  </div>
                </div>
                <div className={styles.changeList}>
                  {[...mapIndustries]
                    .sort(
                      (a, b) =>
                        Math.abs(changeFor(b, changeWindow).net_change) -
                          Math.abs(changeFor(a, changeWindow).net_change) ||
                        b.top100_count - a.top100_count,
                    )
                    .map(item => {
                      const change = changeFor(item, changeWindow);
                      const total = Math.max(
                        1,
                        change.new_count +
                          change.retained_count +
                          change.exit_count,
                      );
                      return (
                        <button
                          type="button"
                          key={item.industry_code}
                          onClick={() => void selectIndustry(item)}
                          className={
                            item.industry_code === selectedIndustry
                              ? styles.active
                              : ""
                          }
                          aria-pressed={
                            item.industry_code === selectedIndustry
                          }
                        >
                          <span>
                            <strong>
                              {item.industry}
                              {item.industry_code === selectedIndustry ? (
                                <Check aria-hidden="true" />
                              ) : null}
                            </strong>
                            <small>{changeLabel(item, changeWindow)}</small>
                          </span>
                          <b>{item.top100_count}只</b>
                          <div
                            aria-label={`新进入 ${change.new_count}只，保留 ${change.retained_count}只，退出 ${change.exit_count}只`}
                          >
                            <i
                              className={styles.new}
                              style={{
                                width: `${(change.new_count / total) * 100}%`,
                              }}
                            />
                            <i
                              className={styles.kept}
                              style={{
                                width: `${(change.retained_count / total) * 100}%`,
                              }}
                            />
                            <i
                              className={styles.exit}
                              style={{
                                width: `${(change.exit_count / total) * 100}%`,
                              }}
                            />
                          </div>
                          <em>
                            <b>新 {change.new_count}</b>
                            <b>留 {change.retained_count}</b>
                            <b>退 {change.exit_count}</b>
                          </em>
                        </button>
                      );
                    })}
                </div>
              </aside>
            </div>

            <section className={styles.detail}>
              {selected ? (
                <>
                  <div className={styles.detailHead}>
                    <div>
                      <span>
                        已选行业 · {date(viewDate)} · {changeWindow}日变化
                      </span>
                      <h2>
                        {selected.industry}
                        {selected.industry_code === "other"
                          ? `（${selected.component_industry_count || selected.components?.length || 0}个行业，${selected.top100_count}只）`
                          : ""}
                      </h2>
                      <p>
                        {date(viewDate)}：当日 Top100{" "}
                        {selected.top100_count}只；比较日{" "}
                        {date(
                          changeFor(selected, changeWindow).comparison_date,
                        )}{" "}
                        （{changeWindow}个实际交易日）；
                        {selected.industry_code === "other"
                          ? "该聚合块使用中性色，不以颜色表达变化。"
                          : `行业当日可选 ${selected.eligible_count ?? "—"}只；入选率 ${
                              selected.eligible_count
                                ? `${(
                                    (selected.top100_count /
                                      selected.eligible_count) *
                                    100
                                  ).toFixed(1)}%（${selected.top100_count}/${selected.eligible_count}）`
                                : "—（当日可选数缺失）"
                            }。`}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedIndustry("");
                        setFocusedIndustry("");
                      }}
                    >
                      返回全行业
                    </button>
                  </div>

                  {!isLatestDate ? (
                    <div className={styles.historyDetail}>
                      <div className={styles.historyNotice} role="status">
                        <TriangleAlert aria-hidden="true" />
                        <p>
                          <strong>历史日期仅显示行业统计。</strong>
                          逐股名单只支持最新交易日 {date(data.asOf)}；
                          这里不会用最新股票清单代替 {date(viewDate)} 的历史清单。
                        </p>
                      </div>
                      <div
                        className={styles.historyMetrics}
                        aria-label={`${selected.industry} ${date(viewDate)} 行业统计`}
                      >
                        <article>
                          <span>当日 Top100 数量</span>
                          <strong>{selected.top100_count}只</strong>
                        </article>
                        <article>
                          <span>{changeWindow}日新进入</span>
                          <strong>
                            {changeFor(selected, changeWindow).new_count}只
                          </strong>
                        </article>
                        <article>
                          <span>{changeWindow}日保留</span>
                          <strong>
                            {changeFor(selected, changeWindow).retained_count}只
                          </strong>
                        </article>
                        <article>
                          <span>{changeWindow}日退出</span>
                          <strong>
                            {changeFor(selected, changeWindow).exit_count}只
                          </strong>
                        </article>
                      </div>
                    </div>
                  ) : detailLoading ? (
                    <div className={styles.detailState} role="status">
                      <LoaderCircle className="spin" aria-hidden="true" />
                      行业摘要已显示，正在加载股票与时间序列…
                    </div>
                  ) : detailError ? (
                    <div className={styles.detailState} role="alert">
                      <TriangleAlert aria-hidden="true" />
                      <span>{detailError}</span>
                      <button
                        type="button"
                        onClick={() => void selectIndustry(selected)}
                      >
                        <RotateCcw aria-hidden="true" />
                        重试明细
                      </button>
                    </div>
                  ) : (
                    <>
                      {selected.components?.length ? (
                        <div className={styles.otherComponents}>
                          <h3>“其他行业”具体构成</h3>
                          <div>
                            {selected.components.map(component => (
                              <article key={component.industry_code}>
                                <strong>{component.industry}</strong>
                                <span>{component.top100_count}只</span>
                                <small>
                                  {changeLabel(
                                    {
                                      ...component,
                                      neutral: false,
                                      top100_share: 0,
                                    },
                                    changeWindow,
                                  )}
                                </small>
                              </article>
                            ))}
                          </div>
                        </div>
                      ) : null}
                      <div className={styles.detailGrid}>
                        <div className={styles.currentStocks}>
                          <h3>最新交易日入选股票</h3>
                          <StockList
                            items={
                              selected.current_stocks ||
                              selected.stocks ||
                              []
                            }
                            templateId={template.key}
                            industryCode={selected.industry_code}
                            changeWindow={changeWindow}
                            empty="当前股票明细为空。"
                            showIndustry={
                              selected.industry_code === "other"
                            }
                          />
                        </div>
                        <div className={styles.transitions}>
                          <h3>{changeWindow}日进入 / 保留 / 退出</h3>
                          <Transition
                            title="新进入"
                            icon={<ArrowUp aria-hidden="true" />}
                            count={
                              changeFor(selected, changeWindow).new_count
                            }
                            items={
                              changeFor(selected, changeWindow).new_stocks ||
                              []
                            }
                            templateId={template.key}
                            industryCode={selected.industry_code}
                            changeWindow={changeWindow}
                            showIndustry={
                              selected.industry_code === "other"
                            }
                          />
                          <Transition
                            title="保留"
                            icon={<ArrowRight aria-hidden="true" />}
                            count={
                              changeFor(selected, changeWindow).retained_count
                            }
                            items={
                              changeFor(selected, changeWindow)
                                .retained_stocks || []
                            }
                            templateId={template.key}
                            industryCode={selected.industry_code}
                            changeWindow={changeWindow}
                            showIndustry={
                              selected.industry_code === "other"
                            }
                          />
                          <Transition
                            title="退出"
                            icon={<ArrowDown aria-hidden="true" />}
                            count={
                              changeFor(selected, changeWindow).exit_count
                            }
                            items={
                              changeFor(selected, changeWindow).exit_stocks ||
                              []
                            }
                            templateId={template.key}
                            industryCode={selected.industry_code}
                            changeWindow={changeWindow}
                            showIndustry={
                              selected.industry_code === "other"
                            }
                          />
                        </div>
                        <div className={styles.series}>
                          <h3>行业 Top100 数量时间序列</h3>
                          <Series
                            points={
                              selected.series ||
                              template.industrySeries?.find(
                                item =>
                                  item.industryCode ===
                                  selected.industry_code,
                              )?.points ||
                              []
                            }
                            industry={selected.industry}
                          />
                        </div>
                      </div>
                    </>
                  )}
                </>
              ) : (
                <div className={styles.prompt}>
                  <strong>点击行业块查看所选日期统计</strong>
                  <span>
                    最新交易日可按需加载股票与时间序列；历史日期只显示
                    行业统计，不会混用最新清单。
                  </span>
                </div>
              )}
            </section>

            <section className={styles.note}>
              <TriangleAlert aria-hidden="true" />
              <p>
                <strong>口径边界：</strong>
                Top100 是每个模板当日按前复权 log-close、窗口内独立 z、
                单窗口 Pearson 排名固定取前 100；不跨模板综合排名，不使用
                0.80 线，也不使用未来收益、IC 或策略表现。行业宽度只描述
                当前数量与 10/20 个实际交易日的净变化，不据此推导市场阶段。
              </p>
            </section>
          </>
        ) : null}
      </main>
    </div>
  );
}

function Timeline({
  payload,
  index,
  loading,
  error,
  onChange,
  onRetry,
}: {
  payload: TimelinePayload | null;
  index: number;
  loading: boolean;
  error: string;
  onChange: (index: number) => void;
  onRetry: () => void;
}) {
  if (loading && !payload) {
    return (
      <section className={styles.timelineState} role="status">
        <LoaderCircle className="spin" aria-hidden="true" />
        正在读取一年行业历史摘要…
      </section>
    );
  }
  if (error && !payload) {
    return (
      <section className={styles.timelineState} role="alert">
        <TriangleAlert aria-hidden="true" />
        <span>{error}</span>
        <button type="button" onClick={onRetry}>
          <RotateCcw aria-hidden="true" />
          重试
        </button>
      </section>
    );
  }
  if (!payload?.snapshots.length) return null;

  const max = payload.snapshots.length - 1;
  const current = payload.snapshots[Math.min(index, max)];
  const progress = max ? (Math.min(index, max) / max) * 100 : 100;
  const monthTicks = payload.snapshots.reduce<
    Array<{ index: number; label: string }>
  >((ticks, snapshot, snapshotIndex) => {
    const normalized = date(snapshot.date);
    const month = normalized.slice(0, 7);
    const prior = ticks.at(-1);
    const priorMonth = prior
      ? date(payload.snapshots[prior.index].date).slice(0, 7)
      : "";
    if (month === priorMonth) return ticks;
    const monthNumber = Number(month.slice(5, 7));
    ticks.push({
      index: snapshotIndex,
      label:
        snapshotIndex === 0 || monthNumber === 1
          ? `${month.slice(0, 4)}年${monthNumber}月`
          : `${monthNumber}月`,
    });
    return ticks;
  }, []);

  return (
    <section
      className={styles.timeline}
      aria-label="Top100 行业空间一年回溯"
    >
      <div className={styles.timelineHead}>
        <div>
          <span>一年回溯 · 每 5 个实际交易日采样</span>
          <strong>{date(current.date)}</strong>
        </div>
        <output aria-live="off">
          第 {Math.min(index, max) + 1} / {payload.snapshots.length} 个采样点
        </output>
      </div>
      <div
        className={styles.timelineControl}
        style={
          {
            "--timeline-progress": `${progress}%`,
          } as CSSProperties
        }
      >
        <div className={styles.timelineTicks} aria-hidden="true">
          {monthTicks.map(tick => (
            <i
              key={`${tick.index}-${tick.label}`}
              style={{
                left: `${max ? (tick.index / max) * 100 : 0}%`,
              }}
            >
              <span>{tick.label}</span>
            </i>
          ))}
        </div>
        <input
          type="range"
          min={0}
          max={max}
          step={1}
          value={Math.min(index, max)}
          aria-label="选择行业空间历史交易日"
          aria-valuetext={`${date(current.date)}，第 ${Math.min(index, max) + 1} 个采样点，共 ${payload.snapshots.length} 个`}
          onChange={event => onChange(Number(event.currentTarget.value))}
        />
      </div>
      <div className={styles.timelineFoot}>
        <time>{date(payload.start_date)}</time>
        <span>点击或拖动；左右方向键逐采样点移动</span>
        <time>{date(payload.end_date)}</time>
      </div>
    </section>
  );
}

function StockList({
  items,
  templateId,
  industryCode,
  changeWindow,
  empty,
  showIndustry,
}: {
  items: IndustryStock[];
  templateId: string;
  industryCode: string;
  changeWindow: ChangeWindow;
  empty: string;
  showIndustry?: boolean;
}) {
  if (!items.length) return <p>{empty}</p>;
  return (
    <div>
      {items.map(item => (
        <Link
          href={`/market?code=${encodeURIComponent(stockCode(item))}&template=${encodeURIComponent(templateId)}&from=breadth&industry=${encodeURIComponent(industryCode)}&window=${changeWindow}`}
          key={item.ts_code}
        >
          <span>
            <strong>{item.name}</strong>
            <small>
              {item.ts_code}
              {showIndustry && item.industry ? ` · ${item.industry}` : ""}
            </small>
          </span>
          {item.score != null ? <b>{item.score.toFixed(3)}</b> : null}
          <ArrowRight aria-hidden="true" />
        </Link>
      ))}
    </div>
  );
}

function Transition({
  title,
  icon,
  count,
  items,
  templateId,
  industryCode,
  changeWindow,
  showIndustry,
}: {
  title: string;
  icon: React.ReactNode;
  count: number;
  items: IndustryStock[];
  templateId: string;
  industryCode: string;
  changeWindow: ChangeWindow;
  showIndustry?: boolean;
}) {
  return (
    <details open>
      <summary>
        {icon}
        <strong>{title}</strong>
        <b>{count}只</b>
      </summary>
      <StockList
        items={items}
        templateId={templateId}
        industryCode={industryCode}
        changeWindow={changeWindow}
        empty="本组没有股票。"
        showIndustry={showIndustry}
      />
    </details>
  );
}

function Series({ points, industry }: { points: Point[]; industry: string }) {
  const values = points.map(point => point.top100_count ?? point.count ?? 0);
  if (!points.length) return <p>暂无时间序列。</p>;
  const width = 760;
  const height = 220;
  const pad = { left: 45, right: 18, top: 18, bottom: 34 };
  const max = Math.max(1, ...values);
  const x = (index: number) =>
    pad.left +
    index *
      ((width - pad.left - pad.right) / Math.max(1, values.length - 1));
  const y = (value: number) =>
    height -
    pad.bottom -
    (value / max) * (height - pad.top - pad.bottom);
  const path = values
    .map((value, index) => `${index ? "L" : "M"}${x(index)},${y(value)}`)
    .join(" ");
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`${industry} Top100 数量时间序列，单位为只`}
    >
      <line
        x1={pad.left}
        x2={width - pad.right}
        y1={height - pad.bottom}
        y2={height - pad.bottom}
      />
      <line
        x1={pad.left}
        x2={pad.left}
        y1={pad.top}
        y2={height - pad.bottom}
      />
      <path d={path} />
      {points.map((point, index) => (
        <circle
          key={`${point.date}-${index}`}
          cx={x(index)}
          cy={y(values[index])}
          r="4"
          tabIndex={0}
          aria-label={`${date(point.date)}，${values[index]}只`}
        >
          <title>
            {date(point.date)} · {values[index]}只
          </title>
        </circle>
      ))}
      <text x={8} y={14}>
        Top100数量（只）
      </text>
      <text x={pad.left} y={height - 8}>
        {date(points[0].date)}
      </text>
      <text textAnchor="end" x={width - pad.right} y={height - 8}>
        {date(points.at(-1)?.date)}
      </text>
      <text x={pad.left - 8} y={y(max) + 4} textAnchor="end">
        {max}
      </text>
      <text
        x={pad.left - 8}
        y={height - pad.bottom + 4}
        textAnchor="end"
      >
        0
      </text>
    </svg>
  );
}

function State({
  title,
  text,
  action,
}: {
  title: string;
  text: string;
  action?: React.ReactNode;
}) {
  return (
    <section className={styles.state}>
      <LoaderCircle className="spin" aria-hidden="true" />
      <strong>{title}</strong>
      <span>{text}</span>
      {action}
    </section>
  );
}
