"use client";

import Link from "next/link";
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import {
  ArrowLeft,
  Check,
  Focus,
  LoaderCircle,
  RotateCcw,
  Save,
  Search,
  TriangleAlert,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { api } from "../lib/api";
import type { Bar, Stock } from "../lib/types";
import { AppSidebar } from "./AppSidebar";
import { CandlestickPreview } from "./CandlestickPreview";
import styles from "./NewTemplateClient.module.css";

const MIN_DAYS = 20;
const MAX_DAYS = 240;
const DEFAULT_FOCUS_DAYS = 160;
const MIN_FOCUS_DAYS = 20;
const MAX_FOCUS_DAYS = 720;

type Range = { start: number; end: number };
type DragHandle = "start" | "end" | "window" | "pan";
type DragState = {
  handle: DragHandle;
  originIndex: number;
  originClientX: number;
  selection: Range;
  viewport: Range;
};
type SearchState = "idle" | "loading" | "ready" | "empty" | "error";

function compactDate(value?: string) {
  return String(value || "").replaceAll("-", "");
}

function readableDate(value?: string) {
  const text = compactDate(value);
  return text.length === 8 ? `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6)}` : "—";
}

function dateOf(bar?: Bar) {
  return bar?.trade_date || bar?.time || "";
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.max(minimum, Math.min(maximum, value));
}

function boundedRange(rawStart: number, rawSpan: number, total: number): Range {
  if (!total) return { start: 0, end: 0 };
  const span = clamp(Math.round(rawSpan), 1, total);
  const start = clamp(Math.round(rawStart), 0, total - span);
  return { start, end: start + span - 1 };
}

export function NewTemplateClient() {
  const chartRef = useRef<SVGSVGElement>(null);
  const overviewRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<DragState | null>(null);
  const overviewDragRef = useRef<{ originClientX: number; viewport: Range } | null>(null);
  const selectedQueryRef = useRef("");
  const barsRequestRef = useRef(0);
  const resultsId = useId();
  const validationId = useId();
  const saveReasonId = useId();

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Stock[]>([]);
  const [searchState, setSearchState] = useState<SearchState>("idle");
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [activeResult, setActiveResult] = useState(0);
  const [stock, setStock] = useState<Stock | null>(null);
  const [bars, setBars] = useState<Bar[]>([]);
  const [selection, setSelection] = useState<Range>({ start: 0, end: 0 });
  const [viewport, setViewport] = useState<Range>({ start: 0, end: 0 });
  const [focusWidth, setFocusWidth] = useState(1000);
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [barError, setBarError] = useState("");
  const [saveError, setSaveError] = useState("");

  useEffect(() => {
    let active = true;
    const trimmed = query.trim();
    if (!trimmed || trimmed === selectedQueryRef.current) {
      setResults([]);
      setSearchState("idle");
      setSearchError("");
      return () => { active = false; };
    }

    setSearchState("loading");
    setSearchError("");
    const timer = window.setTimeout(() => {
      void api.search(trimmed).then(response => {
        if (!active) return;
        const items = response.items.slice(0, 8);
        setResults(items);
        setActiveResult(0);
        setSearchState(items.length ? "ready" : "empty");
      }).catch(reason => {
        if (!active) return;
        setResults([]);
        setSearchError(reason instanceof Error ? reason.message : "股票搜索失败");
        setSearchState("error");
      });
    }, 180);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [query]);

  useEffect(() => {
    if (!bars.length || !chartRef.current) return;
    const node = chartRef.current;
    const updateWidth = () => {
      const next = Math.max(280, Math.round(node.getBoundingClientRect().width));
      setFocusWidth(current => current === next ? current : next);
    };
    updateWidth();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateWidth);
      return () => window.removeEventListener("resize", updateWidth);
    }
    const observer = new ResizeObserver(updateWidth);
    observer.observe(node);
    return () => observer.disconnect();
  }, [bars.length]);

  async function chooseStock(item: Stock) {
    const requestId = ++barsRequestRef.current;
    const displayQuery = `${item.name} ${item.code}`;
    selectedQueryRef.current = displayQuery;
    setStock(item);
    setQuery(displayQuery);
    setResults([]);
    setSearchOpen(false);
    setSearchState("idle");
    setBars([]);
    setSelection({ start: 0, end: 0 });
    setViewport({ start: 0, end: 0 });
    setLoading(true);
    setBarError("");
    setSaveError("");
    setName(`${item.name} 形态窗口`);
    try {
      const response = await api.barsAll(item.code);
      if (requestId !== barsRequestRef.current) return;
      const next = response.items;
      if (!next.length) throw new Error("本地数据中没有这只股票的真实前复权日线");
      const nextEnd = next.length - 1;
      const nextStart = Math.max(0, nextEnd - 59);
      setBars(next);
      setSelection({ start: nextStart, end: nextEnd });
      setViewport(boundedRange(nextEnd - DEFAULT_FOCUS_DAYS + 1, DEFAULT_FOCUS_DAYS, next.length));
    } catch (reason) {
      if (requestId !== barsRequestRef.current) return;
      setBarError(reason instanceof Error ? reason.message : "真实前复权日线读取失败");
    } finally {
      if (requestId === barsRequestRef.current) setLoading(false);
    }
  }

  const start = selection.start;
  const end = selection.end;
  const viewStart = bars.length ? clamp(viewport.start, 0, bars.length - 1) : 0;
  const viewEnd = bars.length ? clamp(viewport.end, viewStart, bars.length - 1) : 0;
  const count = bars.length ? end - start + 1 : 0;
  const viewCount = bars.length ? viewEnd - viewStart + 1 : 0;
  const valid = count >= MIN_DAYS && count <= MAX_DAYS;
  const validation = !bars.length
    ? "选择股票后可框选 20–240 个实际交易日"
    : count < MIN_DAYS
      ? `还差 ${MIN_DAYS - count} 个交易日，最少需要 ${MIN_DAYS} 日`
      : count > MAX_DAYS
        ? `超出 ${count - MAX_DAYS} 个交易日，最多允许 ${MAX_DAYS} 日`
        : `窗口有效：${count} 个实际交易日`;

  const saveDisabledReason = saving
    ? "正在保存模板…"
    : !stock
      ? "请先搜索并选择股票"
      : loading
        ? "完整历史读取完成后才能保存"
        : !bars.length
          ? "没有可用的真实前复权日线"
          : !valid
            ? validation
            : !name.trim()
              ? "请填写模板名称"
              : "";

  const visibleBars = useMemo(
    () => bars.slice(viewStart, viewEnd + 1),
    [bars, viewEnd, viewStart],
  );

  const geometry = useMemo(() => {
    const width = focusWidth;
    const height = 390;
    const pad = { left: 18, right: 18, top: 16, bottom: 30 };
    const lows = visibleBars.map(bar => bar.low);
    const highs = visibleBars.map(bar => bar.high);
    const min = lows.length ? Math.min(...lows) : 0;
    const max = highs.length ? Math.max(...highs) : 1;
    const spread = Math.max(max - min, Math.abs(max) * .001, .001);
    const step = (width - pad.left - pad.right) / Math.max(1, visibleBars.length);
    const candleWidth = Math.max(.8, Math.min(14, step * .68));
    const x = (index: number) => pad.left + step * (index - viewStart + .5);
    const boundaryX = (index: number) => pad.left + step * (index - viewStart);
    const y = (value: number) => pad.top + (max - value) / spread * (height - pad.top - pad.bottom);
    return { width, height, pad, step, candleWidth, x, boundaryX, y };
  }, [focusWidth, viewStart, visibleBars]);

  const overviewGeometry = useMemo(() => {
    const width = focusWidth;
    const height = 112;
    const pad = { left: 18, right: 18, top: 12, bottom: 24 };
    const closes = bars.map(bar => bar.close);
    const min = closes.length ? Math.min(...closes) : 0;
    const max = closes.length ? Math.max(...closes) : 1;
    const spread = Math.max(max - min, Math.abs(max) * .001, .001);
    const step = (width - pad.left - pad.right) / Math.max(1, bars.length);
    const boundaryX = (index: number) => pad.left + step * index;
    const y = (value: number) => pad.top + (max - value) / spread * (height - pad.top - pad.bottom);
    const path = bars.map((bar, index) => `${index ? "L" : "M"}${boundaryX(index + .5).toFixed(2)},${y(bar.close).toFixed(2)}`).join(" ");
    return { width, height, pad, step, boundaryX, path };
  }, [bars, focusWidth]);

  const selectionX = bars.length ? geometry.boundaryX(start) : 0;
  const selectionWidth = bars.length ? count * geometry.step : 0;
  const selectionHitWidth = Math.max(44, selectionWidth);
  const selectionHitX = selectionX - (selectionHitWidth - selectionWidth) / 2;
  const overviewSelectionX = bars.length ? overviewGeometry.boundaryX(start) : 0;
  const overviewSelectionWidth = bars.length ? count * overviewGeometry.step : 0;
  const overviewViewportX = bars.length ? overviewGeometry.boundaryX(viewStart) : 0;
  const overviewViewportWidth = bars.length ? viewCount * overviewGeometry.step : 0;

  function setBoundedViewport(rawStart: number, span = viewCount) {
    setViewport(boundedRange(rawStart, Math.min(MAX_FOCUS_DAYS, span), bars.length));
  }

  function zoom(direction: "in" | "out", anchorIndex = (viewStart + viewEnd) / 2) {
    if (!bars.length) return;
    const maximum = Math.min(MAX_FOCUS_DAYS, bars.length);
    const minimum = Math.min(MIN_FOCUS_DAYS, maximum);
    const proposed = direction === "in" ? Math.round(viewCount * .76) : Math.round(viewCount * 1.32);
    const nextSpan = clamp(proposed === viewCount ? viewCount + (direction === "in" ? -1 : 1) : proposed, minimum, maximum);
    if (nextSpan === viewCount) return;
    const ratio = viewCount <= 1 ? .5 : clamp((anchorIndex - viewStart) / (viewCount - 1), 0, 1);
    setBoundedViewport(Math.round(anchorIndex - ratio * (nextSpan - 1)), nextSpan);
  }

  function fitSelection() {
    if (!bars.length) return;
    const padding = Math.max(4, Math.ceil(count * .12));
    const span = Math.min(MAX_FOCUS_DAYS, Math.max(MIN_FOCUS_DAYS, count + padding * 2));
    setBoundedViewport(start - Math.floor((span - count) / 2), span);
  }

  function resetView() {
    if (!bars.length) return;
    const span = Math.min(DEFAULT_FOCUS_DAYS, bars.length);
    const center = (start + end) / 2;
    setBoundedViewport(Math.round(center - (span - 1) / 2), span);
  }

  function eventIndex(event: PointerEvent<SVGElement>) {
    const rect = chartRef.current?.getBoundingClientRect();
    if (!rect || !bars.length) return 0;
    const scaledX = (event.clientX - rect.left) / rect.width * geometry.width;
    const localIndex = Math.round((scaledX - geometry.pad.left - geometry.step / 2) / geometry.step);
    return clamp(viewStart + localIndex, 0, bars.length - 1);
  }

  function beginDrag(event: PointerEvent<SVGElement>, handle: DragHandle) {
    if (!bars.length || (event.pointerType === "mouse" && event.button !== 0)) return;
    event.preventDefault();
    event.stopPropagation();
    dragRef.current = {
      handle,
      originIndex: eventIndex(event),
      originClientX: event.clientX,
      selection,
      viewport: { start: viewStart, end: viewEnd },
    };
    chartRef.current?.setPointerCapture(event.pointerId);
  }

  function captureBoundaryHit(event: PointerEvent<SVGSVGElement>) {
    if (!bars.length || (event.pointerType === "mouse" && event.button !== 0)) return;
    const rect = chartRef.current?.getBoundingClientRect();
    if (!rect) return;
    const startClientX = rect.left + selectionX / geometry.width * rect.width;
    const endClientX = rect.left + (selectionX + selectionWidth) / geometry.width * rect.width;
    const startDistance = Math.abs(event.clientX - startClientX);
    const endDistance = Math.abs(event.clientX - endClientX);
    if (Math.min(startDistance, endDistance) > 22) return;
    beginDrag(event, startDistance <= endDistance ? "start" : "end");
  }

  function moveDrag(event: PointerEvent<SVGSVGElement>) {
    const drag = dragRef.current;
    if (!drag) return;
    if (drag.handle === "pan") {
      const rect = chartRef.current?.getBoundingClientRect();
      if (!rect) return;
      const span = drag.viewport.end - drag.viewport.start + 1;
      const delta = Math.round(-(event.clientX - drag.originClientX) / rect.width * span);
      setViewport(boundedRange(drag.viewport.start + delta, span, bars.length));
      return;
    }
    const index = eventIndex(event);
    if (drag.handle === "start") {
      setSelection({ start: Math.min(index, drag.selection.end), end: drag.selection.end });
    } else if (drag.handle === "end") {
      setSelection({ start: drag.selection.start, end: Math.max(index, drag.selection.start) });
    } else {
      const delta = index - drag.originIndex;
      const length = drag.selection.end - drag.selection.start;
      const nextStart = clamp(drag.selection.start + delta, 0, bars.length - 1 - length);
      setSelection({ start: nextStart, end: nextStart + length });
    }
  }

  function finishDrag(event: PointerEvent<SVGSVGElement>) {
    dragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function moveBoundary(handle: "start" | "end", event: KeyboardEvent<SVGGElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const step = event.shiftKey ? 5 : 1;
    const delta = event.key === "ArrowLeft" ? -step : step;
    setSelection(current => handle === "start"
      ? { start: clamp(current.start + delta, 0, current.end), end: current.end }
      : { start: current.start, end: clamp(current.end + delta, current.start, bars.length - 1) });
  }

  function moveWholeWindow(event: KeyboardEvent<SVGGElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const amount = event.shiftKey ? 5 : 1;
    const delta = event.key === "ArrowLeft" ? -amount : amount;
    const length = end - start;
    const nextStart = clamp(start + delta, 0, bars.length - 1 - length);
    const next = { start: nextStart, end: nextStart + length };
    setSelection(next);
    if (next.start < viewStart) setBoundedViewport(next.start, viewCount);
    else if (next.end > viewEnd) setBoundedViewport(next.end - viewCount + 1, viewCount);
  }

  useEffect(() => {
    const node = chartRef.current;
    if (!node || !bars.length) return;
    const onWheel = (event: globalThis.WheelEvent) => {
      if (!event.deltaY) return;
      event.preventDefault();
      const rect = node.getBoundingClientRect();
      const maximum = Math.min(MAX_FOCUS_DAYS, bars.length);
      const minimum = Math.min(MIN_FOCUS_DAYS, maximum);
      const proposed = event.deltaY < 0 ? Math.round(viewCount * .76) : Math.round(viewCount * 1.32);
      const nextSpan = clamp(
        proposed === viewCount ? viewCount + (event.deltaY < 0 ? -1 : 1) : proposed,
        minimum,
        maximum,
      );
      if (nextSpan === viewCount) return;
      const pointerRatio = clamp((event.clientX - rect.left) / rect.width, 0, 1);
      const anchor = viewStart + pointerRatio * Math.max(0, viewCount - 1);
      const anchorRatio = viewCount <= 1 ? .5 : clamp((anchor - viewStart) / (viewCount - 1), 0, 1);
      setViewport(boundedRange(Math.round(anchor - anchorRatio * (nextSpan - 1)), nextSpan, bars.length));
    };
    node.addEventListener("wheel", onWheel, { passive: false });
    return () => node.removeEventListener("wheel", onWheel);
  }, [bars.length, viewCount, viewStart]);

  function overviewEventIndex(event: PointerEvent<SVGSVGElement>) {
    const rect = overviewRef.current?.getBoundingClientRect();
    if (!rect || !bars.length) return 0;
    const ratio = clamp((event.clientX - rect.left) / rect.width, 0, 1);
    return clamp(Math.round(ratio * (bars.length - 1)), 0, bars.length - 1);
  }

  function beginOverviewDrag(event: PointerEvent<SVGSVGElement>) {
    if (!bars.length || (event.pointerType === "mouse" && event.button !== 0)) return;
    event.preventDefault();
    const index = overviewEventIndex(event);
    const span = viewCount;
    const next = index >= viewStart && index <= viewEnd
      ? { start: viewStart, end: viewEnd }
      : boundedRange(index - Math.floor(span / 2), span, bars.length);
    setViewport(next);
    overviewDragRef.current = { originClientX: event.clientX, viewport: next };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveOverviewDrag(event: PointerEvent<SVGSVGElement>) {
    const drag = overviewDragRef.current;
    const rect = overviewRef.current?.getBoundingClientRect();
    if (!drag || !rect) return;
    const span = drag.viewport.end - drag.viewport.start + 1;
    const delta = Math.round((event.clientX - drag.originClientX) / rect.width * bars.length);
    setViewport(boundedRange(drag.viewport.start + delta, span, bars.length));
  }

  function finishOverviewDrag(event: PointerEvent<SVGSVGElement>) {
    overviewDragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function handleQueryChange(value: string) {
    selectedQueryRef.current = "";
    setQuery(value);
    setSearchOpen(Boolean(value.trim()));
    setActiveResult(0);
  }

  function handleSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      setSearchOpen(false);
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp" && event.key !== "Enter") return;
    if (event.key === "Enter") {
      if (searchOpen && searchState === "ready" && results[activeResult]) {
        event.preventDefault();
        void chooseStock(results[activeResult]);
      }
      return;
    }
    event.preventDefault();
    setSearchOpen(true);
    if (!results.length) return;
    setActiveResult(current => event.key === "ArrowDown"
      ? (current + 1) % results.length
      : (current - 1 + results.length) % results.length);
  }

  async function save() {
    if (!stock || !valid || !name.trim()) return;
    setSaving(true);
    setSaveError("");
    try {
      const template = await api.createTemplate({
        name: name.trim(),
        source_ts_code: stock.ts_code,
        start_date: compactDate(dateOf(bars[start])),
        end_date: compactDate(dateOf(bars[end])),
      });
      window.location.assign(`/templates?template=${encodeURIComponent(template.id)}`);
    } catch (reason) {
      setSaveError(reason instanceof Error ? reason.message : "模板保存失败");
      setSaving(false);
    }
  }

  return <div className={`app-shell ${styles.shell}`}>
    <AppSidebar active="templates" />
    <main className={styles.main}>
      <header className={styles.pageHead}>
        <div>
          <span>真实 K 线框选</span>
          <h1>新建模板</h1>
          <p>总览定位完整历史，在焦点图中缩放、平移并框出唯一模板窗口。</p>
        </div>
        <Link href="/templates"><ArrowLeft />返回模板库</Link>
      </header>

      <section className={styles.searchCard}>
        <label>
          <span>1 · 搜索股票</span>
          <div className={styles.searchField}>
            <Search />
            <input
              value={query}
              onChange={event => handleQueryChange(event.target.value)}
              onFocus={() => { if (query.trim() && query.trim() !== selectedQueryRef.current) setSearchOpen(true); }}
              onKeyDown={handleSearchKeyDown}
              placeholder="输入股票名称、代码或拼音首字母"
              role="combobox"
              aria-label="搜索股票"
              aria-autocomplete="list"
              aria-expanded={searchOpen}
              aria-controls={resultsId}
              aria-activedescendant={searchOpen && searchState === "ready" && results[activeResult] ? `${resultsId}-${activeResult}` : undefined}
              aria-busy={searchState === "loading"}
            />
            {query ? <button
              type="button"
              onClick={() => {
                selectedQueryRef.current = "";
                setQuery("");
                setResults([]);
                setSearchOpen(false);
                setSearchState("idle");
              }}
              aria-label="清空搜索"
            ><X /></button> : null}
          </div>
        </label>
        {searchOpen && query.trim() ? searchState === "ready" ? <div id={resultsId} className={styles.results} role="listbox" aria-label="股票搜索结果">
          {results.map((item, index) => <button
            id={`${resultsId}-${index}`}
            key={item.ts_code}
            type="button"
            role="option"
            aria-selected={activeResult === index}
            className={activeResult === index ? styles.activeResult : undefined}
            onPointerMove={() => setActiveResult(index)}
            onMouseDown={event => event.preventDefault()}
            onClick={() => void chooseStock(item)}
          >
            <span><strong>{item.name}</strong><small>{item.code} · {item.industry || "行业待补"}</small></span>
            <Check />
          </button>)}
        </div> : <div id={resultsId} className={styles.searchState} role={searchState === "error" ? "alert" : "status"}>
          {searchState === "loading" ? <><LoaderCircle className="spin" />正在搜索本地股票…</> : null}
          {searchState === "empty" ? "没有匹配的本地股票，换个名称或代码试试。" : null}
          {searchState === "error" ? <><TriangleAlert />搜索失败：{searchError}</> : null}
        </div> : null}
      </section>

      <section className={styles.chartCard}>
        <div className={styles.chartHead}>
          <div><span>2 · 框选历史窗口</span><h2>{stock ? `${stock.name} ${stock.code}` : "等待选择股票"}</h2></div>
          {bars.length ? <div className={valid ? styles.valid : styles.invalid}>
            <strong>{readableDate(dateOf(bars[start]))} → {readableDate(dateOf(bars[end]))}</strong>
            <small>{count} 个实际交易日</small>
          </div> : null}
        </div>

        {loading ? <div className={styles.state}><LoaderCircle className="spin" />正在读取完整真实前复权日线…</div> :
          barError ? <div className={`${styles.state} ${styles.loadError}`} role="alert"><TriangleAlert />{barError}</div> :
            bars.length ? <div className={styles.chartWrap}>
              <div className={styles.overviewHead}>
                <div><strong>完整历史总览</strong><span>{readableDate(dateOf(bars[0]))} → {readableDate(dateOf(bars.at(-1)))} · 共 {bars.length} 日</span></div>
                <small>浅色为模板选区，深色边框为焦点视窗；拖动总览可快速换年代。</small>
              </div>
              <svg
                ref={overviewRef}
                viewBox={`0 0 ${overviewGeometry.width} ${overviewGeometry.height}`}
                preserveAspectRatio="none"
                className={styles.overview}
                role="img"
                aria-label={`${stock?.name}完整前复权 K 线总览，包含全部 ${bars.length} 个交易日`}
                data-testid="history-overview"
                onPointerDown={beginOverviewDrag}
                onPointerMove={moveOverviewDrag}
                onPointerUp={finishOverviewDrag}
                onPointerCancel={finishOverviewDrag}
              >
                <rect className={styles.overviewSurface} x="0" y="0" width={overviewGeometry.width} height={overviewGeometry.height} />
                <path className={styles.overviewLine} d={overviewGeometry.path} />
                <rect className={`${styles.overviewSelection} ${valid ? "" : styles.overviewSelectionInvalid}`} x={overviewSelectionX} y={overviewGeometry.pad.top} width={Math.max(1, overviewSelectionWidth)} height={overviewGeometry.height - overviewGeometry.pad.top - overviewGeometry.pad.bottom} />
                <rect
                  className={styles.overviewViewport}
                  data-testid="overview-viewport"
                  x={overviewViewportX}
                  y={4}
                  width={Math.max(3, overviewViewportWidth)}
                  height={overviewGeometry.height - overviewGeometry.pad.bottom + 4}
                />
                <text x={overviewGeometry.pad.left} y={overviewGeometry.height - 6}>{readableDate(dateOf(bars[0]))}</text>
                <text textAnchor="end" x={overviewGeometry.width - overviewGeometry.pad.right} y={overviewGeometry.height - 6}>{readableDate(dateOf(bars.at(-1)))}</text>
              </svg>

              <div className={styles.focusToolbar}>
                <div className={styles.viewMeta}>
                  <strong>焦点蜡烛图</strong>
                  <span>当前视图 {viewCount} 日 · {readableDate(dateOf(bars[viewStart]))} → {readableDate(dateOf(bars[viewEnd]))}</span>
                </div>
                <div className={styles.zoomControls} aria-label="K 线视图控制">
                  <button type="button" onClick={() => zoom("out")} disabled={viewCount >= Math.min(MAX_FOCUS_DAYS, bars.length)} aria-label="缩小焦点视图"><ZoomOut /><span>缩小</span></button>
                  <button type="button" onClick={fitSelection} aria-label="焦点视图适配模板选区"><Focus /><span>适配选区</span></button>
                  <button type="button" onClick={() => zoom("in")} disabled={viewCount <= Math.min(MIN_FOCUS_DAYS, bars.length)} aria-label="放大焦点视图"><ZoomIn /><span>放大</span></button>
                  <button type="button" onClick={resetView} aria-label="重置焦点视图"><RotateCcw /><span>重置</span></button>
                </div>
              </div>

              <svg
                ref={chartRef}
                viewBox={`0 0 ${geometry.width} ${geometry.height}`}
                preserveAspectRatio="none"
                className={styles.chart}
                role="group"
                aria-label={`${stock?.name}焦点真实前复权 K 线，可缩放、平移和调整模板窗口`}
                data-testid="focus-kline"
                data-view-start={viewStart}
                data-view-end={viewEnd}
                data-selection-start={start}
                data-selection-end={end}
                onPointerDownCapture={captureBoundaryHit}
                onPointerDown={event => beginDrag(event, "pan")}
                onPointerMove={moveDrag}
                onPointerUp={finishDrag}
                onPointerCancel={finishDrag}
              >
                <rect className={styles.panSurface} x="0" y="0" width={geometry.width} height={geometry.height} />
                {[.25, .5, .75].map(ratio => <line className={styles.grid} key={ratio} x1="0" x2={geometry.width} y1={geometry.height * ratio} y2={geometry.height * ratio} />)}
                {visibleBars.map((bar, localIndex) => {
                  const index = viewStart + localIndex;
                  const x = geometry.x(index);
                  const up = bar.close >= bar.open;
                  const top = geometry.y(Math.max(bar.open, bar.close));
                  const bottom = geometry.y(Math.min(bar.open, bar.close));
                  return <g className={up ? styles.up : styles.down} key={`${dateOf(bar)}-${index}`}>
                    <line x1={x} x2={x} y1={geometry.y(bar.high)} y2={geometry.y(bar.low)} />
                    <rect x={x - geometry.candleWidth / 2} y={top} width={geometry.candleWidth} height={Math.max(.8, bottom - top)} />
                  </g>;
                })}
                <g
                  className={styles.selectionGroup}
                  tabIndex={0}
                  role="slider"
                  aria-label="整体移动模板窗口"
                  aria-valuemin={1}
                  aria-valuemax={bars.length}
                  aria-valuenow={start + 1}
                  aria-valuetext={`${readableDate(dateOf(bars[start]))} 至 ${readableDate(dateOf(bars[end]))}，${count} 日`}
                  onKeyDown={moveWholeWindow}
                  onPointerDown={event => beginDrag(event, "window")}
                >
                  <rect className={`${styles.selection} ${valid ? "" : styles.selectionInvalid}`} x={selectionX} y="0" width={selectionWidth} height={geometry.height} />
                  <rect className={styles.windowHit} x={selectionHitX} y="0" width={selectionHitWidth} height={geometry.height} />
                </g>
                <g
                  className={styles.handle}
                  tabIndex={0}
                  role="slider"
                  aria-label="模板窗口开始边界"
                  aria-valuemin={1}
                  aria-valuemax={end + 1}
                  aria-valuenow={start + 1}
                  aria-valuetext={readableDate(dateOf(bars[start]))}
                  onKeyDown={event => moveBoundary("start", event)}
                  onPointerDown={event => beginDrag(event, "start")}
                >
                  <rect className={styles.handleHit} x={selectionX - 22} y="0" width="44" height={geometry.height} />
                  <rect className={styles.handleGrip} x={selectionX - 4} y="10" width="8" height={geometry.height - 42} rx="4" />
                  <line x1={selectionX} x2={selectionX} y1="0" y2={geometry.height} />
                </g>
                <g
                  className={styles.handle}
                  tabIndex={0}
                  role="slider"
                  aria-label="模板窗口结束边界"
                  aria-valuemin={start + 1}
                  aria-valuemax={bars.length}
                  aria-valuenow={end + 1}
                  aria-valuetext={readableDate(dateOf(bars[end]))}
                  onKeyDown={event => moveBoundary("end", event)}
                  onPointerDown={event => beginDrag(event, "end")}
                >
                  <rect className={styles.handleHit} x={selectionX + selectionWidth - 22} y="0" width="44" height={geometry.height} />
                  <rect className={styles.handleGrip} x={selectionX + selectionWidth - 4} y="10" width="8" height={geometry.height - 42} rx="4" />
                  <line x1={selectionX + selectionWidth} x2={selectionX + selectionWidth} y1="0" y2={geometry.height} />
                </g>
                <text x={geometry.pad.left} y={geometry.height - 8}>{readableDate(dateOf(bars[viewStart]))}</text>
                <text textAnchor="end" x={geometry.width - geometry.pad.right} y={geometry.height - 8}>{readableDate(dateOf(bars[viewEnd]))}</text>
              </svg>

              <div className={styles.interactionLegend} aria-label="K 线交互说明">
                <span><i className={styles.edgeKey} />拖边界：改起止日</span>
                <span><i className={styles.windowKey} />拖框内：整体移动选区</span>
                <span><i className={styles.panKey} />拖空白：平移视图</span>
                <span>滚轮 / 触控板：缩放视图</span>
              </div>

              <div className={styles.selectionSummary}>
                <dl>
                  <div><dt>开始日期</dt><dd>{readableDate(dateOf(bars[start]))}</dd></div>
                  <div><dt>结束日期</dt><dd>{readableDate(dateOf(bars[end]))}</dd></div>
                  <div><dt>实际交易日</dt><dd>{count} 日</dd></div>
                </dl>
                <p id={validationId} className={valid ? styles.validationValid : styles.validationInvalid} role={valid ? "status" : "alert"} aria-live="polite">
                  {valid ? <Check /> : <TriangleAlert />}{validation}
                </p>
              </div>

              <p className={styles.brushHint}>边界或选区获得焦点后，方向键移动 1 日，Shift + 方向键移动 5 日。焦点视图最多展示 {Math.min(MAX_FOCUS_DAYS, bars.length)} 日，完整历史始终保留在上方总览。</p>
              <figure className={styles.selectionPreview}>
                <figcaption><span>选中窗口局部预览</span><strong>{readableDate(dateOf(bars[start]))} → {readableDate(dateOf(bars[end]))} · {count} 日</strong></figcaption>
                <CandlestickPreview bars={bars.slice(start, end + 1)} height={190} label={`${stock?.name}选中模板窗口局部真实前复权 K 线`} />
              </figure>
            </div> : <div className={styles.state}>搜索并选择一只股票后，这里展示完整真实前复权 K 线。</div>}
      </section>

      <section className={styles.saveCard}>
        <div>
          <span>3 · 确认并保存</span>
          <h2>{bars.length ? `${readableDate(dateOf(bars[start]))} 至 ${readableDate(dateOf(bars[end]))}` : "尚未选择窗口"}</h2>
          <p>交易日数按本地真实前复权日线计算；后端仍会再次校验 20–240 日限制。</p>
        </div>
        <label><span>模板名称</span><input value={name} onChange={event => setName(event.target.value)} maxLength={80} placeholder="给这段形态起个名字" aria-invalid={Boolean(bars.length && !name.trim())} /></label>
        <div className={styles.saveAction}>
          <button
            type="button"
            disabled={Boolean(saveDisabledReason)}
            aria-describedby={`${validationId} ${saveReasonId}`}
            onClick={() => void save()}
          >{saving ? <LoaderCircle className="spin" /> : <Save />}保存模板</button>
          <p id={saveReasonId}>{saveDisabledReason || "窗口和名称有效，可以保存"}</p>
        </div>
        {saveError ? <p className={styles.error} role="alert"><TriangleAlert />{saveError}</p> : null}
      </section>
    </main>
  </div>;
}
