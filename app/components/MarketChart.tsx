"use client";

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type LogicalRange,
  type Time,
} from "lightweight-charts";
import type { Bar } from "../lib/types";

export type DrawingKind =
  | "line"
  | "trend"
  | "segment"
  | "ray"
  | "horizontal"
  | "vertical"
  | "fibonacci"
  | "curve"
  | "freehand"
  | "text"
  | "measure";

export type DrawingMode = DrawingKind | "select";

export type ChartPoint = { x: number; y: number };

export type ChartDrawing = {
  kind: DrawingKind;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  text?: string;
  /** New drawings use relative coordinates so they survive layout/fullscreen resizing. */
  coordinateSpace?: "pixel" | "relative";
  points?: ChartPoint[];
};

export type MarketChartHandle = {
  resize: () => void;
  fitContent: () => void;
  getChart: () => IChartApi | null;
  deleteSelectedDrawing: () => void;
};

type Props = {
  bars: Bar[];
  compact?: boolean;
  drawingMode?: DrawingMode | null;
  crosshairEnabled?: boolean;
  onDrawComplete?: (drawing: ChartDrawing) => void;
  drawings?: ChartDrawing[];
  selectedDrawingIndex?: number | null;
  onDrawingSelect?: (index: number | null) => void;
  onDrawingChange?: (index: number, drawing: ChartDrawing) => void;
  onDrawingDelete?: (index: number) => void;
  onDrawingsChange?: (drawings: ChartDrawing[]) => void;
  onRendered?: (durationMs: number) => void;
  /** Called as the visible window approaches the earliest loaded bar. */
  onNeedMoreHistory?: () => void;
  /** Same boundary notification with the oldest loaded date for paged loaders. */
  onNeedOlder?: (oldestTime?: string) => void;
  historyLoadThreshold?: number;
  /** Number of latest bars shown initially; all supplied bars remain scrollable. */
  visibleCount?: number;
  /** Disable only when a parent intentionally manages the logical range itself. */
  fitContentOnDataChange?: boolean;
};

export type NormalizedChartBar = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ma5: number | null;
  ma10: number | null;
  ma20: number | null;
};

const FIBONACCI_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1] as const;
const HIT_DISTANCE = 8;

function finitePositive(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function normalizeDate(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const raw = value.trim();
  const match = /^(\d{4})[-/]?(\d{2})[-/]?(\d{2})$/.exec(raw);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return `${match[1]}-${match[2]}-${match[3]}`;
}

function normalizeMovingAverage(value: unknown, low: number, high: number): number | null {
  if (!finitePositive(value)) return null;
  // A wildly different moving-average scale usually means mixed adjustment factors.
  // Excluding only that indicator prevents it from flattening an otherwise valid candle series.
  return value >= low / 4 && value <= high * 4 ? value : null;
}

/**
 * Produces one sorted, de-duplicated timeline shared by candles, volume and averages.
 * Invalid OHLC rows are omitted; malformed highs/lows are repaired from the four prices.
 */
export function normalizeChartBars(bars: readonly Bar[]): NormalizedChartBar[] {
  const byDate = new Map<string, NormalizedChartBar>();
  for (const bar of bars) {
    const time = normalizeDate(bar.time) ?? normalizeDate(bar.trade_date);
    if (!time || !finitePositive(bar.open) || !finitePositive(bar.high) || !finitePositive(bar.low) || !finitePositive(bar.close)) continue;
    const high = Math.max(bar.open, bar.high, bar.low, bar.close);
    const low = Math.min(bar.open, bar.high, bar.low, bar.close);
    byDate.set(time, {
      time,
      open: bar.open,
      high,
      low,
      close: bar.close,
      volume: typeof bar.volume === "number" && Number.isFinite(bar.volume) ? Math.max(0, bar.volume) : 0,
      ma5: normalizeMovingAverage(bar.ma5, low, high),
      ma10: normalizeMovingAverage(bar.ma10, low, high),
      ma20: normalizeMovingAverage(bar.ma20, low, high),
    });
  }
  return [...byDate.values()].sort((left, right) => left.time.localeCompare(right.time));
}

type ScreenDrawing = Omit<ChartDrawing, "coordinateSpace">;
type EditState = {
  index: number;
  handle: "start" | "end" | "move";
  origin: ChartPoint;
  drawing: ScreenDrawing;
};

function toScreenPoint(point: ChartPoint, relative: boolean, width: number, height: number): ChartPoint {
  return relative ? { x: point.x * width, y: point.y * height } : point;
}

function toScreenDrawing(drawing: ChartDrawing, width: number, height: number): ScreenDrawing {
  const relative = drawing.coordinateSpace === "relative";
  const start = toScreenPoint({ x: drawing.x1, y: drawing.y1 }, relative, width, height);
  const end = toScreenPoint({ x: drawing.x2, y: drawing.y2 }, relative, width, height);
  return {
    ...drawing,
    x1: start.x,
    y1: start.y,
    x2: end.x,
    y2: end.y,
    points: drawing.points?.map(point => toScreenPoint(point, relative, width, height)),
  };
}

function fromScreenDrawing(drawing: ScreenDrawing, width: number, height: number, coordinateSpace: "pixel" | "relative" = "relative"): ChartDrawing {
  if (coordinateSpace === "pixel") return { ...drawing, coordinateSpace };
  const safeWidth = Math.max(1, width);
  const safeHeight = Math.max(1, height);
  return {
    ...drawing,
    x1: drawing.x1 / safeWidth,
    y1: drawing.y1 / safeHeight,
    x2: drawing.x2 / safeWidth,
    y2: drawing.y2 / safeHeight,
    coordinateSpace,
    points: drawing.points?.map(point => ({ x: point.x / safeWidth, y: point.y / safeHeight })),
  };
}

function distance(left: ChartPoint, right: ChartPoint) {
  return Math.hypot(left.x - right.x, left.y - right.y);
}

function distanceToSegment(point: ChartPoint, start: ChartPoint, end: ChartPoint) {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  if (dx === 0 && dy === 0) return distance(point, start);
  const ratio = Math.max(0, Math.min(1, ((point.x - start.x) * dx + (point.y - start.y) * dy) / (dx * dx + dy * dy)));
  return distance(point, { x: start.x + ratio * dx, y: start.y + ratio * dy });
}

function extendedLine(drawing: ScreenDrawing, width: number, height: number, ray: boolean): [ChartPoint, ChartPoint] {
  const start = { x: drawing.x1, y: drawing.y1 };
  const dx = drawing.x2 - drawing.x1;
  const dy = drawing.y2 - drawing.y1;
  if (Math.abs(dx) + Math.abs(dy) < 0.01) return [start, { x: drawing.x2, y: drawing.y2 }];
  const candidates: number[] = [];
  if (dx !== 0) candidates.push((0 - start.x) / dx, (width - start.x) / dx);
  if (dy !== 0) candidates.push((0 - start.y) / dy, (height - start.y) / dy);
  const valid = candidates.filter(t => {
    const x = start.x + dx * t;
    const y = start.y + dy * t;
    return x >= -0.5 && x <= width + 0.5 && y >= -0.5 && y <= height + 0.5;
  });
  if (!valid.length) return [start, { x: drawing.x2, y: drawing.y2 }];
  const from = ray ? 0 : Math.min(...valid);
  const to = Math.max(...valid.filter(value => !ray || value >= 0), ray ? 1 : -Infinity);
  return [
    { x: start.x + dx * from, y: start.y + dy * from },
    { x: start.x + dx * to, y: start.y + dy * to },
  ];
}

function lineEndpoints(drawing: ScreenDrawing, width: number, height: number): [ChartPoint, ChartPoint] {
  if (drawing.kind === "horizontal") return [{ x: 0, y: drawing.y1 }, { x: width, y: drawing.y1 }];
  if (drawing.kind === "vertical") return [{ x: drawing.x1, y: 0 }, { x: drawing.x1, y: height }];
  if (drawing.kind === "trend") return extendedLine(drawing, width, height, false);
  if (drawing.kind === "ray") return extendedLine(drawing, width, height, true);
  return [{ x: drawing.x1, y: drawing.y1 }, { x: drawing.x2, y: drawing.y2 }];
}

function hitDrawing(point: ChartPoint, drawing: ScreenDrawing, width: number, height: number) {
  const start = { x: drawing.x1, y: drawing.y1 };
  const end = { x: drawing.x2, y: drawing.y2 };
  if (distance(point, start) <= HIT_DISTANCE) return "start" as const;
  if (distance(point, end) <= HIT_DISTANCE) return "end" as const;
  if (drawing.kind === "freehand" && drawing.points?.length) {
    for (let index = 1; index < drawing.points.length; index += 1) {
      if (distanceToSegment(point, drawing.points[index - 1], drawing.points[index]) <= HIT_DISTANCE) return "move" as const;
    }
    return null;
  }
  if (drawing.kind === "fibonacci") {
    for (const level of FIBONACCI_LEVELS) {
      const y = drawing.y1 + (drawing.y2 - drawing.y1) * level;
      if (distanceToSegment(point, { x: drawing.x1, y }, { x: drawing.x2, y }) <= HIT_DISTANCE) return "move" as const;
    }
    return null;
  }
  if (drawing.kind === "text") return Math.abs(point.x - drawing.x1) < 90 && Math.abs(point.y - drawing.y1) < 24 ? "move" as const : null;
  const [lineStart, lineEnd] = lineEndpoints(drawing, width, height);
  return distanceToSegment(point, lineStart, lineEnd) <= HIT_DISTANCE ? "move" as const : null;
}

function drawHandle(ctx: CanvasRenderingContext2D, point: ChartPoint) {
  ctx.beginPath();
  ctx.fillStyle = "#fcfbf8";
  ctx.strokeStyle = "#2864ff";
  ctx.arc(point.x, point.y, 4.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
}

function paintOneDrawing(ctx: CanvasRenderingContext2D, drawing: ScreenDrawing, width: number, height: number, selected: boolean) {
  const start = { x: drawing.x1, y: drawing.y1 };
  const end = { x: drawing.x2, y: drawing.y2 };
  ctx.save();
  ctx.strokeStyle = selected ? "#2864ff" : "#111315";
  ctx.fillStyle = selected ? "#2864ff" : "#111315";
  ctx.lineWidth = selected ? 2 : 1.5;

  if (drawing.kind === "text") {
    ctx.fillText(drawing.text || "文本标记", drawing.x1 + 5, drawing.y1 - 5);
    ctx.beginPath();
    ctx.arc(drawing.x1, drawing.y1, 3, 0, Math.PI * 2);
    ctx.fill();
  } else if (drawing.kind === "fibonacci") {
    for (const level of FIBONACCI_LEVELS) {
      const y = drawing.y1 + (drawing.y2 - drawing.y1) * level;
      ctx.beginPath();
      ctx.moveTo(drawing.x1, y);
      ctx.lineTo(drawing.x2, y);
      ctx.stroke();
      ctx.fillText(`${(level * 100).toFixed(level === 0 || level === 1 ? 0 : 1)}%`, Math.min(drawing.x1, drawing.x2) + 4, y - 3);
    }
  } else if (drawing.kind === "curve") {
    const controlX = (drawing.x1 + drawing.x2) / 2;
    const controlY = Math.min(drawing.y1, drawing.y2) - Math.max(28, Math.abs(drawing.x2 - drawing.x1) * 0.16);
    ctx.beginPath();
    ctx.moveTo(drawing.x1, drawing.y1);
    ctx.quadraticCurveTo(controlX, controlY, drawing.x2, drawing.y2);
    ctx.stroke();
  } else if (drawing.kind === "freehand" && drawing.points?.length) {
    ctx.beginPath();
    ctx.moveTo(drawing.points[0].x, drawing.points[0].y);
    drawing.points.slice(1).forEach(point => ctx.lineTo(point.x, point.y));
    ctx.stroke();
  } else {
    if (drawing.kind === "measure") ctx.setLineDash([5, 4]);
    const [lineStart, lineEnd] = lineEndpoints(drawing, width, height);
    ctx.beginPath();
    ctx.moveTo(lineStart.x, lineStart.y);
    ctx.lineTo(lineEnd.x, lineEnd.y);
    ctx.stroke();
    if (drawing.kind === "measure") {
      const dx = Math.abs(drawing.x2 - drawing.x1);
      const dy = Math.abs(drawing.y2 - drawing.y1);
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(8,10,13,.86)";
      ctx.fillRect(Math.min(drawing.x1, drawing.x2), Math.min(drawing.y1, drawing.y2) - 24, 112, 21);
      ctx.fillStyle = "#fff";
      ctx.fillText(`${Math.round(dx)}px × ${Math.round(dy)}px`, Math.min(drawing.x1, drawing.x2) + 6, Math.min(drawing.y1, drawing.y2) - 9);
    }
  }

  if (selected) {
    drawHandle(ctx, start);
    if (drawing.kind !== "horizontal" && drawing.kind !== "vertical" && drawing.kind !== "text") drawHandle(ctx, end);
  }
  ctx.restore();
}

export const MarketChart = forwardRef<MarketChartHandle, Props>(function MarketChart({
  bars,
  compact = false,
  drawingMode,
  crosshairEnabled = true,
  onDrawComplete,
  drawings = [],
  selectedDrawingIndex,
  onDrawingSelect,
  onDrawingChange,
  onDrawingDelete,
  onDrawingsChange,
  onRendered,
  onNeedMoreHistory,
  onNeedOlder,
  historyLoadThreshold = 8,
  visibleCount,
  fitContentOnDataChange = true,
}, forwardedRef) {
  const host = useRef<HTMLDivElement>(null);
  const overlay = useRef<HTMLCanvasElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const ma5Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ma10Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ma20Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const startPoint = useRef<ChartPoint | null>(null);
  const previewDrawing = useRef<ScreenDrawing | null>(null);
  const editState = useRef<EditState | null>(null);
  const drawingsRef = useRef(drawings);
  const selectedRef = useRef<number | null>(selectedDrawingIndex ?? null);
  const onNeedMoreHistoryRef = useRef(onNeedMoreHistory);
  const onNeedOlderRef = useRef(onNeedOlder);
  const historyLoadThresholdRef = useRef(historyLoadThreshold);
  const earliestRequestRef = useRef<string | null>(null);
  const resizeFrame = useRef<number | null>(null);
  const previousTimeline = useRef<string[]>([]);
  const [internalSelected, setInternalSelected] = useState<number | null>(null);
  const activeSelected = selectedDrawingIndex === undefined ? internalSelected : selectedDrawingIndex;
  const normalizedBars = useMemo(() => normalizeChartBars(bars), [bars]);

  const paintDrawings = useCallback(() => {
    const canvas = overlay.current;
    const container = host.current;
    if (!canvas || !container) return;
    const ratio = window.devicePixelRatio || 1;
    const width = container.clientWidth;
    const height = container.clientHeight;
    canvas.width = Math.max(1, Math.round(width * ratio));
    canvas.height = Math.max(1, Math.round(height * ratio));
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(ratio, ratio);
    ctx.font = '13px "Microsoft YaHei UI", sans-serif';
    drawingsRef.current.forEach((drawing, index) => paintOneDrawing(ctx, toScreenDrawing(drawing, width, height), width, height, index === selectedRef.current));
    if (previewDrawing.current) paintOneDrawing(ctx, previewDrawing.current, width, height, false);
  }, []);

  const resize = useCallback(() => {
    if (resizeFrame.current != null) cancelAnimationFrame(resizeFrame.current);
    resizeFrame.current = requestAnimationFrame(() => {
      resizeFrame.current = null;
      const container = host.current;
      if (!container) return;
      chartRef.current?.resize(Math.max(1, container.clientWidth), Math.max(1, container.clientHeight));
      paintDrawings();
    });
  }, [paintDrawings]);

  const selectDrawing = useCallback((index: number | null) => {
    selectedRef.current = index;
    if (selectedDrawingIndex === undefined) setInternalSelected(index);
    onDrawingSelect?.(index);
  }, [onDrawingSelect, selectedDrawingIndex]);

  const deleteSelectedDrawing = useCallback(() => {
    const index = selectedRef.current;
    if (index == null || !drawingsRef.current[index]) return;
    const next = drawingsRef.current.filter((_, drawingIndex) => drawingIndex !== index);
    onDrawingDelete?.(index);
    onDrawingsChange?.(next);
    selectDrawing(null);
  }, [onDrawingDelete, onDrawingsChange, selectDrawing]);

  useImperativeHandle(forwardedRef, () => ({
    resize,
    fitContent: () => chartRef.current?.timeScale().fitContent(),
    getChart: () => chartRef.current,
    deleteSelectedDrawing,
  }), [deleteSelectedDrawing, resize]);

  useEffect(() => {
    if (!host.current) return;
    const container = host.current;
    const chart = createChart(container, {
      width: Math.max(1, container.clientWidth),
      height: Math.max(1, container.clientHeight),
      layout: { background: { type: ColorType.Solid, color: "#fcfbf8" }, textColor: "#4f5354", fontFamily: '"Microsoft YaHei UI", sans-serif', fontSize: 12 },
      grid: { vertLines: { color: "#ece9e2", style: 1 }, horzLines: { color: "#e8e5de", style: 1 } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: "#656868", style: 3 }, horzLine: { color: "#656868", style: 3 } },
      rightPriceScale: { borderColor: "#d8d5cd", autoScale: true, scaleMargins: { top: 0.08, bottom: 0.28 } },
      timeScale: { borderColor: "#d8d5cd", timeVisible: false, rightOffset: 4, barSpacing: 6, minBarSpacing: 1.8, fixLeftEdge: false },
      handleScale: true,
      handleScroll: true,
    });
    chartRef.current = chart;
    candleRef.current = chart.addSeries(CandlestickSeries, {
      upColor: "#f04444",
      downColor: "#20aa7b",
      borderUpColor: "#f04444",
      borderDownColor: "#20aa7b",
      wickUpColor: "#f04444",
      wickDownColor: "#20aa7b",
      priceScaleId: "right",
    });
    volumeRef.current = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "volume", lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("volume").applyOptions({ autoScale: true, scaleMargins: { top: 0.8, bottom: 0 } });
    ma5Ref.current = chart.addSeries(LineSeries, { color: "#34bc92", lineWidth: 1, priceScaleId: "right", priceLineVisible: false, lastValueVisible: false });
    ma10Ref.current = chart.addSeries(LineSeries, { color: "#2864ff", lineWidth: 1, priceScaleId: "right", priceLineVisible: false, lastValueVisible: false });
    ma20Ref.current = chart.addSeries(LineSeries, { color: "#8856e8", lineWidth: 1, priceScaleId: "right", priceLineVisible: false, lastValueVisible: false });

    const visibleRangeChanged = (range: LogicalRange | null) => {
      if (!range || range.from > historyLoadThresholdRef.current || (!onNeedMoreHistoryRef.current && !onNeedOlderRef.current)) return;
      const earliest = previousTimeline.current[0];
      if (!earliest || earliestRequestRef.current === earliest) return;
      earliestRequestRef.current = earliest;
      onNeedMoreHistoryRef.current?.();
      onNeedOlderRef.current?.(earliest);
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(visibleRangeChanged);

    const observer = new ResizeObserver(resize);
    observer.observe(container);
    window.addEventListener("resize", resize);
    document.addEventListener("fullscreenchange", resize);
    resize();
    return () => {
      if (resizeFrame.current != null) cancelAnimationFrame(resizeFrame.current);
      observer.disconnect();
      window.removeEventListener("resize", resize);
      document.removeEventListener("fullscreenchange", resize);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(visibleRangeChanged);
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
      ma5Ref.current = null;
      ma10Ref.current = null;
      ma20Ref.current = null;
    };
  }, [resize]);

  useEffect(() => {
    const started = performance.now();
    const timeline = normalizedBars.map(bar => bar.time);
    const previous = previousTimeline.current;
    const logicalRange = chartRef.current?.timeScale().getVisibleLogicalRange();
    const prepended = previous.length > 0 && timeline.at(-1) === previous.at(-1) ? Math.max(0, timeline.indexOf(previous[0])) : 0;

    candleRef.current?.setData(normalizedBars.map(bar => ({ time: bar.time as Time, open: bar.open, high: bar.high, low: bar.low, close: bar.close })));
    volumeRef.current?.setData(normalizedBars.map(bar => ({ time: bar.time as Time, value: bar.volume, color: bar.close >= bar.open ? "rgba(240,68,68,.78)" : "rgba(32,170,123,.78)" })));
    ma5Ref.current?.setData(normalizedBars.filter(bar => bar.ma5 != null).map(bar => ({ time: bar.time as Time, value: bar.ma5! })));
    ma10Ref.current?.setData(normalizedBars.filter(bar => bar.ma10 != null).map(bar => ({ time: bar.time as Time, value: bar.ma10! })));
    ma20Ref.current?.setData(normalizedBars.filter(bar => bar.ma20 != null).map(bar => ({ time: bar.time as Time, value: bar.ma20! })));

    if (logicalRange && prepended > 0) {
      chartRef.current?.timeScale().setVisibleLogicalRange({ from: logicalRange.from + prepended, to: logicalRange.to + prepended });
    } else if (fitContentOnDataChange) {
      const count = visibleCount == null ? timeline.length : Math.max(1, Math.floor(visibleCount));
      if (timeline.length > 0 && count < timeline.length) {
        chartRef.current?.timeScale().setVisibleLogicalRange({ from: timeline.length - count, to: timeline.length - 1 });
      } else {
        chartRef.current?.timeScale().fitContent();
      }
    }
    if (timeline[0] !== previous[0]) earliestRequestRef.current = null;
    previousTimeline.current = timeline;
    requestAnimationFrame(() => requestAnimationFrame(() => onRendered?.(performance.now() - started)));
  }, [fitContentOnDataChange, normalizedBars, onRendered, visibleCount]);

  useEffect(() => {
    chartRef.current?.applyOptions({
      crosshair: { mode: crosshairEnabled ? CrosshairMode.Normal : CrosshairMode.Hidden },
      rightPriceScale: { autoScale: true, scaleMargins: compact ? { top: 0.1, bottom: 0.28 } : { top: 0.08, bottom: 0.28 } },
      timeScale: { barSpacing: compact ? 7 : 6 },
    });
    resize();
  }, [compact, crosshairEnabled, resize]);

  useEffect(() => {
    drawingsRef.current = drawings;
    if (activeSelected != null && !drawings[activeSelected]) selectDrawing(null);
    selectedRef.current = activeSelected;
    paintDrawings();
  }, [activeSelected, drawingMode, drawings, paintDrawings, selectDrawing]);

  useEffect(() => {
    onNeedMoreHistoryRef.current = onNeedMoreHistory;
    onNeedOlderRef.current = onNeedOlder;
    historyLoadThresholdRef.current = historyLoadThreshold;
  }, [historyLoadThreshold, onNeedMoreHistory, onNeedOlder]);

  function point(event: ReactPointerEvent<HTMLCanvasElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  function pointerDown(event: ReactPointerEvent<HTMLCanvasElement>) {
    const current = point(event);
    const width = event.currentTarget.clientWidth;
    const height = event.currentTarget.clientHeight;
    event.currentTarget.focus();
    if (drawingMode === "select") {
      let match: EditState | null = null;
      for (let index = drawingsRef.current.length - 1; index >= 0; index -= 1) {
        const drawing = toScreenDrawing(drawingsRef.current[index], width, height);
        const handle = hitDrawing(current, drawing, width, height);
        if (handle) {
          match = { index, handle, origin: current, drawing };
          break;
        }
      }
      editState.current = match;
      selectDrawing(match?.index ?? null);
      if (match) event.currentTarget.setPointerCapture(event.pointerId);
      paintDrawings();
      return;
    }
    if (!drawingMode) return;
    startPoint.current = current;
    previewDrawing.current = {
      kind: drawingMode,
      x1: current.x,
      y1: current.y,
      x2: current.x,
      y2: current.y,
      text: drawingMode === "text" ? "文本标记" : undefined,
      points: drawingMode === "freehand" ? [current] : undefined,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    paintDrawings();
  }

  function pointerMove(event: ReactPointerEvent<HTMLCanvasElement>) {
    const current = point(event);
    const width = event.currentTarget.clientWidth;
    const height = event.currentTarget.clientHeight;
    if (drawingMode === "select" && editState.current) {
      const edit = editState.current;
      const dx = current.x - edit.origin.x;
      const dy = current.y - edit.origin.y;
      let next: ScreenDrawing;
      if (edit.handle === "start") {
        next = { ...edit.drawing, x1: current.x, y1: current.y };
        if (next.kind === "freehand" && next.points?.length) next.points = [current, ...next.points.slice(1)];
      } else if (edit.handle === "end") {
        next = { ...edit.drawing, x2: current.x, y2: current.y };
        if (next.kind === "freehand" && next.points?.length) next.points = [...next.points.slice(0, -1), current];
      } else {
        next = {
          ...edit.drawing,
          x1: edit.drawing.x1 + dx,
          y1: edit.drawing.y1 + dy,
          x2: edit.drawing.x2 + dx,
          y2: edit.drawing.y2 + dy,
          points: edit.drawing.points?.map(item => ({ x: item.x + dx, y: item.y + dy })),
        };
      }
      const originalSpace = drawingsRef.current[edit.index].coordinateSpace ?? "pixel";
      const converted = fromScreenDrawing(next, width, height, originalSpace);
      const nextDrawings = drawingsRef.current.map((drawing, index) => index === edit.index ? converted : drawing);
      drawingsRef.current = nextDrawings;
      onDrawingChange?.(edit.index, converted);
      onDrawingsChange?.(nextDrawings);
      paintDrawings();
      return;
    }
    if (!drawingMode || drawingMode === "select" || !startPoint.current || !previewDrawing.current) return;
    previewDrawing.current.x2 = current.x;
    previewDrawing.current.y2 = drawingMode === "horizontal" ? startPoint.current.y : current.y;
    if (drawingMode === "vertical") previewDrawing.current.x2 = startPoint.current.x;
    if (drawingMode === "freehand") previewDrawing.current.points = [...(previewDrawing.current.points ?? []), current];
    paintDrawings();
  }

  function pointerUp(event: ReactPointerEvent<HTMLCanvasElement>) {
    if (drawingMode === "select") {
      editState.current = null;
      if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
      return;
    }
    if (!drawingMode || !startPoint.current || !previewDrawing.current) return;
    const completed = fromScreenDrawing(previewDrawing.current, event.currentTarget.clientWidth, event.currentTarget.clientHeight);
    onDrawComplete?.(completed);
    startPoint.current = null;
    previewDrawing.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    paintDrawings();
  }

  function keyDown(event: ReactKeyboardEvent<HTMLCanvasElement>) {
    if (drawingMode !== "select") return;
    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      deleteSelectedDrawing();
    } else if (event.key === "Escape") {
      selectDrawing(null);
      paintDrawings();
    }
  }

  const normalizedCount = normalizedBars.length;
  const interactive = Boolean(drawingMode);
  return <div
    ref={host}
    className={`market-chart ${compact ? "compact" : ""}`}
    data-bars={visibleCount == null ? normalizedCount : Math.min(normalizedCount, visibleCount)}
    data-effective-bars={normalizedCount}
    data-source-bars={bars.length}
    data-dropped-bars={bars.length - normalizedCount}
    data-first-time={normalizedBars[0]?.time}
    data-last-time={normalizedBars.at(-1)?.time}
    data-drawing-mode={drawingMode ?? "pan"}
  >
    <canvas
      ref={overlay}
      className={`drawing-overlay ${interactive ? "drawing" : ""}`}
      aria-label={drawingMode === "select" ? "选择和调整画线" : drawingMode ? `绘制${drawingMode}` : undefined}
      tabIndex={interactive ? 0 : -1}
      onKeyDown={keyDown}
      onPointerDown={pointerDown}
      onPointerMove={pointerMove}
      onPointerUp={pointerUp}
      onPointerCancel={pointerUp}
    />
  </div>;
});
