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
  type MouseEvent as ReactMouseEvent,
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
  type Logical,
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
  | "fibonacci-extension"
  | "rectangle"
  | "curve"
  | "freehand"
  | "text"
  | "measure";

export type DrawingMode = DrawingKind | "select";

export type ChartPoint = { x: number; y: number };

export type FibonacciLevel = {
  id: string;
  value: number;
  enabled: boolean;
  custom?: boolean;
};

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
  control?: ChartPoint;
  color?: string;
  lineWidth?: number;
  fibonacciLevels?: FibonacciLevel[];
};

export type MarketChartHandle = {
  resize: () => void;
  fitContent: () => void;
  resetDefault: () => void;
  getChart: () => IChartApi | null;
  deleteSelectedDrawing: () => void;
};

type PriceScaleMode = "auto" | "locked" | "free";

type Props = {
  bars: Bar[];
  /** Immutable series arrays shared by every pane in a multi-chart layout. */
  preparedData?: PreparedChartData;
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
  onDrawingDoubleClick?: (index: number, point: { clientX: number; clientY: number }) => void;
  onRendered?: (durationMs: number) => void;
  drawingColor?: string;
  drawingLineWidth?: number;
  drawingText?: string;
  fibonacciLevels?: FibonacciLevel[];
  /** Called as the visible window approaches the earliest loaded bar. */
  onNeedMoreHistory?: () => void;
  /** Same boundary notification with the oldest loaded date for paged loaders. */
  onNeedOlder?: (oldestTime?: string) => void;
  historyLoadThreshold?: number;
  /** Number of latest bars shown initially; all supplied bars remain scrollable. */
  visibleCount?: number;
  /** Empty logical bars kept after the latest candle. */
  rightPaddingBars?: number;
  /** Disable only when a parent intentionally manages the logical range itself. */
  fitContentOnDataChange?: boolean;
  /** The main terminal supplies this to restore its canonical D/6M parent state. */
  onResetDefault?: () => void;
  enablePriceScaleMenu?: boolean;
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

export type PreparedChartData = {
  normalizedBars: NormalizedChartBar[];
  timeline: string[];
  candles: Array<{ time: Time; open: number; high: number; low: number; close: number }>;
  volumes: Array<{ time: Time; value: number; color: string }>;
  ma5: Array<{ time: Time; value: number }>;
  ma10: Array<{ time: Time; value: number }>;
  ma20: Array<{ time: Time; value: number }>;
};

const FIBONACCI_RETRACEMENT_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1] as const;
const FIBONACCI_EXTENSION_LEVELS = [0, 0.618, 1, 1.272, 1.618, 2, 2.618] as const;
const HIT_DISTANCE = 8;

export function defaultFibonacciLevels(kind: "fibonacci" | "fibonacci-extension"): FibonacciLevel[] {
  const levels = kind === "fibonacci-extension" ? FIBONACCI_EXTENSION_LEVELS : FIBONACCI_RETRACEMENT_LEVELS;
  return levels.map(value => ({ id: `default-${value}`, value, enabled: true }));
}

function finitePositive(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function uiFontAdjustment() {
  if (typeof document === "undefined") return 0;
  return document.documentElement.dataset.fontSize === "large"
    ? 2
    : document.documentElement.dataset.fontSize === "small" ? -1 : 0;
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

export function prepareChartData(bars: readonly Bar[]): PreparedChartData {
  const normalizedBars = normalizeChartBars(bars);
  return {
    normalizedBars,
    timeline: normalizedBars.map(bar => bar.time),
    candles: normalizedBars.map(bar => ({
      time: bar.time as Time,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    })),
    volumes: normalizedBars.map(bar => ({
      time: bar.time as Time,
      value: bar.volume,
      color: bar.close >= bar.open
        ? "rgba(240,68,68,.78)"
        : "rgba(32,170,123,.78)",
    })),
    ma5: normalizedBars
      .filter(bar => bar.ma5 != null)
      .map(bar => ({ time: bar.time as Time, value: bar.ma5! })),
    ma10: normalizedBars
      .filter(bar => bar.ma10 != null)
      .map(bar => ({ time: bar.time as Time, value: bar.ma10! })),
    ma20: normalizedBars
      .filter(bar => bar.ma20 != null)
      .map(bar => ({ time: bar.time as Time, value: bar.ma20! })),
  };
}

type ScreenDrawing = Omit<ChartDrawing, "coordinateSpace">;
type EditState = {
  index: number;
  handle: "start" | "end" | "control" | "move";
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
    control: drawing.control ? toScreenPoint(drawing.control, relative, width, height) : undefined,
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
    control: drawing.control ? { x: drawing.control.x / safeWidth, y: drawing.control.y / safeHeight } : undefined,
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

function curveControl(drawing: ScreenDrawing): ChartPoint {
  return drawing.control ?? {
    x: (drawing.x1 + drawing.x2) / 2,
    y: Math.min(drawing.y1, drawing.y2) - Math.max(28, Math.abs(drawing.x2 - drawing.x1) * 0.16),
  };
}

function distanceToCurve(point: ChartPoint, drawing: ScreenDrawing) {
  const control = curveControl(drawing);
  let closest = Number.POSITIVE_INFINITY;
  let previous = { x: drawing.x1, y: drawing.y1 };
  for (let step = 1; step <= 28; step += 1) {
    const t = step / 28;
    const inverse = 1 - t;
    const current = {
      x: inverse * inverse * drawing.x1 + 2 * inverse * t * control.x + t * t * drawing.x2,
      y: inverse * inverse * drawing.y1 + 2 * inverse * t * control.y + t * t * drawing.y2,
    };
    closest = Math.min(closest, distanceToSegment(point, previous, current));
    previous = current;
  }
  return closest;
}

function fibonacciLevels(drawing: ScreenDrawing) {
  if (drawing.fibonacciLevels?.length) return drawing.fibonacciLevels.filter(level => level.enabled).map(level => level.value);
  return drawing.kind === "fibonacci-extension" ? FIBONACCI_EXTENSION_LEVELS : FIBONACCI_RETRACEMENT_LEVELS;
}

function usesTwoPointPlacement(kind: DrawingKind) {
  return kind === "line"
    || kind === "trend"
    || kind === "segment"
    || kind === "ray"
    || kind === "fibonacci"
    || kind === "fibonacci-extension"
    || kind === "rectangle"
    || kind === "curve"
    || kind === "measure";
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
  if (drawing.kind === "curve") {
    if (distance(point, curveControl(drawing)) <= HIT_DISTANCE) return "control" as const;
    return distanceToCurve(point, drawing) <= HIT_DISTANCE ? "move" as const : null;
  }
  if (drawing.kind === "freehand" && drawing.points?.length) {
    for (let index = 1; index < drawing.points.length; index += 1) {
      if (distanceToSegment(point, drawing.points[index - 1], drawing.points[index]) <= HIT_DISTANCE) return "move" as const;
    }
    return null;
  }
  if (drawing.kind === "fibonacci" || drawing.kind === "fibonacci-extension") {
    for (const level of fibonacciLevels(drawing)) {
      const y = drawing.y1 + (drawing.y2 - drawing.y1) * level;
      if (distanceToSegment(point, { x: drawing.x1, y }, { x: drawing.x2, y }) <= HIT_DISTANCE) return "move" as const;
    }
    return null;
  }
  if (drawing.kind === "rectangle") {
    const left = Math.min(drawing.x1, drawing.x2);
    const right = Math.max(drawing.x1, drawing.x2);
    const top = Math.min(drawing.y1, drawing.y2);
    const bottom = Math.max(drawing.y1, drawing.y2);
    const onEdge = distanceToSegment(point, { x: left, y: top }, { x: right, y: top }) <= HIT_DISTANCE
      || distanceToSegment(point, { x: right, y: top }, { x: right, y: bottom }) <= HIT_DISTANCE
      || distanceToSegment(point, { x: right, y: bottom }, { x: left, y: bottom }) <= HIT_DISTANCE
      || distanceToSegment(point, { x: left, y: bottom }, { x: left, y: top }) <= HIT_DISTANCE;
    return onEdge || (point.x > left && point.x < right && point.y > top && point.y < bottom) ? "move" as const : null;
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
  const color = drawing.color || "#111315";
  const lineWidth = Math.max(1, Math.min(6, drawing.lineWidth || 1.5));
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = lineWidth;
  if (selected) {
    ctx.shadowColor = "rgba(40,100,255,.3)";
    ctx.shadowBlur = 2;
  }

  if (drawing.kind === "text") {
    ctx.fillText(drawing.text || "文本标记", drawing.x1 + 5, drawing.y1 - 5);
    ctx.beginPath();
    ctx.arc(drawing.x1, drawing.y1, 3, 0, Math.PI * 2);
    ctx.fill();
  } else if (drawing.kind === "fibonacci" || drawing.kind === "fibonacci-extension") {
    for (const level of fibonacciLevels(drawing)) {
      const y = drawing.y1 + (drawing.y2 - drawing.y1) * level;
      ctx.beginPath();
      ctx.moveTo(drawing.x1, y);
      ctx.lineTo(drawing.x2, y);
      ctx.stroke();
      ctx.fillText(`${(level * 100).toFixed(level === 0 || level === 1 ? 0 : 1)}%`, Math.min(drawing.x1, drawing.x2) + 4, y - 3);
    }
  } else if (drawing.kind === "curve") {
    const control = curveControl(drawing);
    ctx.beginPath();
    ctx.moveTo(drawing.x1, drawing.y1);
    ctx.quadraticCurveTo(control.x, control.y, drawing.x2, drawing.y2);
    ctx.stroke();
  } else if (drawing.kind === "freehand" && drawing.points?.length) {
    ctx.beginPath();
    ctx.moveTo(drawing.points[0].x, drawing.points[0].y);
    drawing.points.slice(1).forEach(point => ctx.lineTo(point.x, point.y));
    ctx.stroke();
  } else if (drawing.kind === "rectangle") {
    const left = Math.min(drawing.x1, drawing.x2);
    const top = Math.min(drawing.y1, drawing.y2);
    const rectangleWidth = Math.abs(drawing.x2 - drawing.x1);
    const rectangleHeight = Math.abs(drawing.y2 - drawing.y1);
    ctx.save();
    ctx.globalAlpha = 0.08;
    ctx.fillRect(left, top, rectangleWidth, rectangleHeight);
    ctx.restore();
    ctx.strokeRect(left, top, rectangleWidth, rectangleHeight);
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
    ctx.shadowColor = "transparent";
    drawHandle(ctx, start);
    if (drawing.kind !== "horizontal" && drawing.kind !== "vertical" && drawing.kind !== "text") drawHandle(ctx, end);
    if (drawing.kind === "curve") {
      const control = curveControl(drawing);
      ctx.save();
      ctx.setLineDash([3, 4]);
      ctx.strokeStyle = "rgba(40,100,255,.65)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(start.x, start.y);
      ctx.lineTo(control.x, control.y);
      ctx.lineTo(end.x, end.y);
      ctx.stroke();
      ctx.restore();
      drawHandle(ctx, control);
    }
  }
  ctx.restore();
}

export const MarketChart = forwardRef<MarketChartHandle, Props>(function MarketChart({
  bars,
  preparedData,
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
  onDrawingDoubleClick,
  onRendered,
  drawingColor = "#2864ff",
  drawingLineWidth = 2,
  drawingText = "文本标记",
  fibonacciLevels: incomingFibonacciLevels,
  onNeedMoreHistory,
  onNeedOlder,
  historyLoadThreshold = 8,
  visibleCount,
  rightPaddingBars,
  fitContentOnDataChange = true,
  onResetDefault,
  enablePriceScaleMenu = false,
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
  const placementGesture = useRef<{ phase: "first" | "second"; origin: ChartPoint; moved: boolean } | null>(null);
  const previousDrawingMode = useRef<DrawingMode | null | undefined>(drawingMode);
  const drawingsRef = useRef(drawings);
  const selectedRef = useRef<number | null>(selectedDrawingIndex ?? null);
  const onNeedMoreHistoryRef = useRef(onNeedMoreHistory);
  const onNeedOlderRef = useRef(onNeedOlder);
  const historyLoadThresholdRef = useRef(historyLoadThreshold);
  const earliestRequestRef = useRef<string | null>(null);
  const resizeFrame = useRef<number | null>(null);
  const previousTimeline = useRef<string[]>([]);
  const fontAdjustmentRef = useRef(0);
  const [internalSelected, setInternalSelected] = useState<number | null>(null);
  const [priceScaleMode, setPriceScaleMode] = useState<PriceScaleMode>("auto");
  const [priceMenu, setPriceMenu] = useState<{ left: number; top: number } | null>(null);
  const activeSelected = selectedDrawingIndex === undefined ? internalSelected : selectedDrawingIndex;
  const prepared = useMemo(
    () => preparedData ?? prepareChartData(bars),
    [bars, preparedData],
  );
  const normalizedBars = prepared.normalizedBars;

  const paintDrawings = useCallback(() => {
    const canvas = overlay.current;
    const container = host.current;
    if (!canvas || !container) return;
    const ratio = window.devicePixelRatio || 1;
    const width = container.clientWidth;
    const height = container.clientHeight;
    const pixelWidth = Math.max(1, Math.round(width * ratio));
    const pixelHeight = Math.max(1, Math.round(height * ratio));
    if (canvas.width !== pixelWidth) canvas.width = pixelWidth;
    if (canvas.height !== pixelHeight) canvas.height = pixelHeight;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.font = `${13 + fontAdjustmentRef.current}px "Microsoft YaHei UI", sans-serif`;
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

  const syncPriceGeometry = useCallback(() => {
    const container = host.current;
    const chart = chartRef.current;
    if (!container || !chart) return;
    const range = chart.priceScale("right").getVisibleRange();
    if (range) {
      container.dataset.priceFrom = range.from.toFixed(4);
      container.dataset.priceTo = range.to.toFixed(4);
      container.dataset.priceSpan = Math.abs(range.to - range.from).toFixed(4);
    }
  }, []);

  const resetDefault = useCallback(() => {
    const chart = chartRef.current;
    if (!chart) return;
    setPriceScaleMode("auto");
    chart.applyOptions({
      handleScale: {
        mouseWheel: true,
        pinch: true,
        axisPressedMouseMove: { time: true, price: true },
        axisDoubleClickReset: { time: true, price: true },
      },
    });
    chart.priceScale("right").setAutoScale(true);
    const count = visibleCount == null ? normalizedBars.length : Math.max(1, Math.floor(visibleCount));
    const padding = Math.max(0, Math.floor(rightPaddingBars || 0));
    if (normalizedBars.length > 0 && (count < normalizedBars.length || padding > 0)) {
      chart.timeScale().setVisibleLogicalRange({
        from: Math.max(0, normalizedBars.length - count),
        to: normalizedBars.length - 1 + padding,
      });
    } else {
      chart.timeScale().fitContent();
    }
    requestAnimationFrame(syncPriceGeometry);
  }, [normalizedBars.length, rightPaddingBars, syncPriceGeometry, visibleCount]);

  const changePriceScaleMode = useCallback((mode: PriceScaleMode) => {
    const chart = chartRef.current;
    if (!chart) return;
    if (mode === "auto") {
      resetDefault();
      onResetDefault?.();
    } else {
      chart.priceScale("right").setAutoScale(false);
      chart.applyOptions({
        handleScale: {
          mouseWheel: true,
          pinch: true,
          axisPressedMouseMove: { time: true, price: mode === "free" },
          axisDoubleClickReset: { time: true, price: mode === "free" },
        },
      });
      setPriceScaleMode(mode);
      requestAnimationFrame(syncPriceGeometry);
    }
    setPriceMenu(null);
  }, [onResetDefault, resetDefault, syncPriceGeometry]);

  useImperativeHandle(forwardedRef, () => ({
    resize,
    fitContent: () => chartRef.current?.timeScale().fitContent(),
    resetDefault,
    getChart: () => chartRef.current,
    deleteSelectedDrawing,
  }), [deleteSelectedDrawing, resetDefault, resize]);

  useEffect(() => {
    if (!priceMenu) return;
    const close = () => setPriceMenu(null);
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("pointerdown", close);
    window.addEventListener("blur", close);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("blur", close);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [priceMenu]);

  useEffect(() => {
    if (!host.current) return;
    const container = host.current;
    fontAdjustmentRef.current = uiFontAdjustment();
    container.dataset.uiFontSize = String(12 + fontAdjustmentRef.current);
    const chart = createChart(container, {
      width: Math.max(1, container.clientWidth),
      height: Math.max(1, container.clientHeight),
      layout: { background: { type: ColorType.Solid, color: "#fcfbf8" }, textColor: "#4f5354", fontFamily: '"Microsoft YaHei UI", sans-serif', fontSize: 12 + fontAdjustmentRef.current },
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
      if (range) {
        container.dataset.visibleFrom = range.from.toFixed(3);
        container.dataset.visibleTo = range.to.toFixed(3);
        const latestIndex = previousTimeline.current.length - 1;
        const visibleFirstIndex = Math.max(
          0,
          Math.min(latestIndex, Math.ceil(range.from)),
        );
        const visibleLastIndex = Math.max(
          0,
          Math.min(latestIndex, Math.floor(range.to)),
        );
        container.dataset.visibleFirstTime =
          previousTimeline.current[visibleFirstIndex] || "";
        container.dataset.visibleLastTime =
          previousTimeline.current[visibleLastIndex] || "";
        container.dataset.visibleRightPadding = latestIndex >= 0 ? (range.to - latestIndex).toFixed(3) : "0";
        const latestX = latestIndex >= 0 ? chart.timeScale().logicalToCoordinate(latestIndex as Logical) : null;
        if (latestX != null) container.dataset.latestBarRightGap = (container.clientWidth - latestX).toFixed(1);
      }
      if (!range || range.from > historyLoadThresholdRef.current || (!onNeedMoreHistoryRef.current && !onNeedOlderRef.current)) return;
      const earliest = previousTimeline.current[0];
      if (!earliest || earliestRequestRef.current === earliest) return;
      earliestRequestRef.current = earliest;
      onNeedMoreHistoryRef.current?.();
      onNeedOlderRef.current?.(earliest);
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(visibleRangeChanged);
    const updateGeometryAfterGesture = () => {
      requestAnimationFrame(() => requestAnimationFrame(syncPriceGeometry));
    };
    container.addEventListener("pointerup", updateGeometryAfterGesture, true);
    container.addEventListener("wheel", updateGeometryAfterGesture, true);

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
      container.removeEventListener("pointerup", updateGeometryAfterGesture, true);
      container.removeEventListener("wheel", updateGeometryAfterGesture, true);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(visibleRangeChanged);
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
      ma5Ref.current = null;
      ma10Ref.current = null;
      ma20Ref.current = null;
    };
  }, [resize, syncPriceGeometry]);

  useEffect(() => {
    const syncFontSize = () => {
      fontAdjustmentRef.current = uiFontAdjustment();
      if (host.current) host.current.dataset.uiFontSize = String(12 + fontAdjustmentRef.current);
      chartRef.current?.applyOptions({ layout: { fontSize: 12 + fontAdjustmentRef.current } });
      resize();
    };
    syncFontSize();
    window.addEventListener("ui-font-size-change", syncFontSize);
    return () => window.removeEventListener("ui-font-size-change", syncFontSize);
  }, [resize]);

  useEffect(() => {
    const started = performance.now();
    const timeline = prepared.timeline;
    const previous = previousTimeline.current;
    const logicalRange = chartRef.current?.timeScale().getVisibleLogicalRange();
    const prepended = previous.length > 0 && timeline.at(-1) === previous.at(-1) ? Math.max(0, timeline.indexOf(previous[0])) : 0;

    candleRef.current?.setData(prepared.candles);
    volumeRef.current?.setData(prepared.volumes);
    ma5Ref.current?.setData(prepared.ma5);
    ma10Ref.current?.setData(prepared.ma10);
    ma20Ref.current?.setData(prepared.ma20);

    previousTimeline.current = timeline;
    if (logicalRange && prepended > 0) {
      chartRef.current?.timeScale().setVisibleLogicalRange({ from: logicalRange.from + prepended, to: logicalRange.to + prepended });
    } else if (fitContentOnDataChange) {
      const count = visibleCount == null ? timeline.length : Math.max(1, Math.floor(visibleCount));
      const padding = Math.max(0, Math.floor(rightPaddingBars || 0));
      if (timeline.length > 0 && (count < timeline.length || padding > 0)) {
        chartRef.current?.timeScale().setVisibleLogicalRange({
          from: Math.max(0, timeline.length - count),
          to: timeline.length - 1 + padding,
        });
      } else {
        chartRef.current?.timeScale().fitContent();
      }
      setPriceScaleMode("auto");
      chartRef.current?.priceScale("right").setAutoScale(true);
    }
    if (timeline[0] !== previous[0]) earliestRequestRef.current = null;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      syncPriceGeometry();
      onRendered?.(performance.now() - started);
    }));
  }, [fitContentOnDataChange, normalizedBars, onRendered, prepared, rightPaddingBars, syncPriceGeometry, visibleCount]);

  useEffect(() => {
    chartRef.current?.applyOptions({
      crosshair: { mode: crosshairEnabled ? CrosshairMode.Normal : CrosshairMode.Hidden },
      rightPriceScale: { autoScale: priceScaleMode === "auto", scaleMargins: compact ? { top: 0.1, bottom: 0.28 } : { top: 0.08, bottom: 0.28 } },
      timeScale: { barSpacing: compact ? 7 : 6 },
    });
    resize();
  }, [compact, crosshairEnabled, priceScaleMode, resize]);

  useEffect(() => {
    drawingsRef.current = drawings;
    if (activeSelected != null && !drawings[activeSelected]) selectDrawing(null);
    selectedRef.current = activeSelected;
    paintDrawings();
  }, [activeSelected, drawingMode, drawings, paintDrawings, selectDrawing]);

  useEffect(() => {
    if (previousDrawingMode.current === drawingMode) return;
    previousDrawingMode.current = drawingMode;
    startPoint.current = null;
    previewDrawing.current = null;
    placementGesture.current = null;
    if (overlay.current) delete overlay.current.dataset.drawingPhase;
    paintDrawings();
  }, [drawingMode, paintDrawings]);

  useEffect(() => {
    onNeedMoreHistoryRef.current = onNeedMoreHistory;
    onNeedOlderRef.current = onNeedOlder;
    historyLoadThresholdRef.current = historyLoadThreshold;
  }, [historyLoadThreshold, onNeedMoreHistory, onNeedOlder]);

  function point(event: { currentTarget: HTMLCanvasElement; clientX: number; clientY: number }) {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  function cursorFor(handle: EditState["handle"] | null, drawing?: ScreenDrawing, dragging = false) {
    if (!handle) return "default";
    if (handle === "move" || handle === "control") return dragging ? "grabbing" : "grab";
    if (drawing?.kind === "horizontal") return "ns-resize";
    if (drawing?.kind === "vertical") return "ew-resize";
    return handle === "start" ? "nwse-resize" : "nesw-resize";
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
      if (match) {
        event.currentTarget.setPointerCapture(event.pointerId);
        event.currentTarget.style.cursor = cursorFor(match.handle, match.drawing, true);
        event.currentTarget.dataset.hitTarget = match.handle;
      } else {
        event.currentTarget.style.cursor = "default";
        delete event.currentTarget.dataset.hitTarget;
      }
      paintDrawings();
      return;
    }
    if (!drawingMode) return;
    if (usesTwoPointPlacement(drawingMode) && startPoint.current && previewDrawing.current) {
      previewDrawing.current.x2 = current.x;
      previewDrawing.current.y2 = current.y;
      placementGesture.current = { phase: "second", origin: current, moved: false };
      event.currentTarget.setPointerCapture(event.pointerId);
      event.currentTarget.dataset.drawingPhase = "placing-second-point";
      paintDrawings();
      return;
    }
    startPoint.current = current;
    previewDrawing.current = {
      kind: drawingMode,
      x1: current.x,
      y1: current.y,
      x2: current.x,
      y2: current.y,
      text: drawingMode === "text" ? drawingText : undefined,
      points: drawingMode === "freehand" ? [current] : undefined,
      color: drawingColor,
      lineWidth: drawingLineWidth,
      fibonacciLevels: drawingMode === "fibonacci" || drawingMode === "fibonacci-extension"
        ? (incomingFibonacciLevels || defaultFibonacciLevels(drawingMode)).map(level => ({ ...level }))
        : undefined,
    };
    placementGesture.current = { phase: "first", origin: current, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.currentTarget.dataset.drawingPhase = usesTwoPointPlacement(drawingMode) ? "placing-first-point" : "drawing";
    paintDrawings();
  }

  function pointerMove(event: ReactPointerEvent<HTMLCanvasElement>) {
    const current = point(event);
    const width = event.currentTarget.clientWidth;
    const height = event.currentTarget.clientHeight;
    if (drawingMode === "select" && editState.current) {
      const edit = editState.current;
      event.currentTarget.style.cursor = cursorFor(edit.handle, edit.drawing, true);
      const dx = current.x - edit.origin.x;
      const dy = current.y - edit.origin.y;
      let next: ScreenDrawing;
      if (edit.handle === "start") {
        next = { ...edit.drawing, x1: current.x, y1: current.y };
        if (next.kind === "freehand" && next.points?.length) next.points = [current, ...next.points.slice(1)];
      } else if (edit.handle === "end") {
        next = { ...edit.drawing, x2: current.x, y2: current.y };
        if (next.kind === "freehand" && next.points?.length) next.points = [...next.points.slice(0, -1), current];
      } else if (edit.handle === "control") {
        next = { ...edit.drawing, control: current };
      } else {
        next = {
          ...edit.drawing,
          x1: edit.drawing.x1 + dx,
          y1: edit.drawing.y1 + dy,
          x2: edit.drawing.x2 + dx,
          y2: edit.drawing.y2 + dy,
          points: edit.drawing.points?.map(item => ({ x: item.x + dx, y: item.y + dy })),
          control: edit.drawing.control ? { x: edit.drawing.control.x + dx, y: edit.drawing.control.y + dy } : undefined,
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
    if (drawingMode === "select") {
      let hovered: { handle: EditState["handle"]; drawing: ScreenDrawing } | null = null;
      for (let index = drawingsRef.current.length - 1; index >= 0; index -= 1) {
        const drawing = toScreenDrawing(drawingsRef.current[index], width, height);
        const handle = hitDrawing(current, drawing, width, height);
        if (handle) {
          hovered = { handle, drawing };
          break;
        }
      }
      event.currentTarget.style.cursor = cursorFor(hovered?.handle ?? null, hovered?.drawing);
      if (hovered) event.currentTarget.dataset.hitTarget = hovered.handle;
      else delete event.currentTarget.dataset.hitTarget;
      return;
    }
    if (!drawingMode || !startPoint.current || !previewDrawing.current) return;
    const gesture = placementGesture.current;
    if (gesture && distance(gesture.origin, current) >= 5) gesture.moved = true;
    previewDrawing.current.x2 = current.x;
    previewDrawing.current.y2 = drawingMode === "horizontal" ? startPoint.current.y : current.y;
    if (drawingMode === "vertical") previewDrawing.current.x2 = startPoint.current.x;
    if (drawingMode === "freehand") previewDrawing.current.points?.push(current);
    paintDrawings();
  }

  function pointerUp(event: ReactPointerEvent<HTMLCanvasElement>) {
    if (drawingMode === "select") {
      const edit = editState.current;
      editState.current = null;
      if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
      event.currentTarget.style.cursor = cursorFor(edit?.handle ?? null, edit?.drawing);
      return;
    }
    if (!drawingMode || !startPoint.current || !previewDrawing.current) return;
    const gesture = placementGesture.current;
    if (usesTwoPointPlacement(drawingMode) && gesture?.phase === "first" && !gesture.moved) {
      placementGesture.current = null;
      event.currentTarget.dataset.drawingPhase = "awaiting-second-point";
      if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
      paintDrawings();
      return;
    }
    const completed = fromScreenDrawing(previewDrawing.current, event.currentTarget.clientWidth, event.currentTarget.clientHeight);
    onDrawComplete?.(completed);
    startPoint.current = null;
    previewDrawing.current = null;
    placementGesture.current = null;
    delete event.currentTarget.dataset.drawingPhase;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    paintDrawings();
  }

  function pointerLeave(event: ReactPointerEvent<HTMLCanvasElement>) {
    if (!editState.current) {
      event.currentTarget.style.cursor = drawingMode && drawingMode !== "select" ? "crosshair" : "default";
      delete event.currentTarget.dataset.hitTarget;
    }
  }

  function keyDown(event: ReactKeyboardEvent<HTMLCanvasElement>) {
    if (event.key === "Escape" && drawingMode !== "select") {
      startPoint.current = null;
      previewDrawing.current = null;
      placementGesture.current = null;
      delete event.currentTarget.dataset.drawingPhase;
      paintDrawings();
      return;
    }
    if (drawingMode !== "select") return;
    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      deleteSelectedDrawing();
    } else if (event.key === "Escape") {
      selectDrawing(null);
      paintDrawings();
    }
  }

  function doubleClick(event: ReactMouseEvent<HTMLCanvasElement>) {
    if (drawingMode !== "select") return;
    const current = point(event);
    const width = event.currentTarget.clientWidth;
    const height = event.currentTarget.clientHeight;
    for (let index = drawingsRef.current.length - 1; index >= 0; index -= 1) {
      const drawing = toScreenDrawing(drawingsRef.current[index], width, height);
      if (drawing.kind !== "fibonacci" && drawing.kind !== "fibonacci-extension") continue;
      if (!hitDrawing(current, drawing, width, height)) continue;
      selectDrawing(index);
      onDrawingDoubleClick?.(index, { clientX: event.clientX, clientY: event.clientY });
      event.preventDefault();
      return;
    }
  }

  function openPriceScaleMenu(event: ReactMouseEvent<HTMLDivElement>) {
    if (!enablePriceScaleMenu) return;
    const chart = chartRef.current;
    const container = host.current;
    if (!chart || !container) return;
    const bounds = container.getBoundingClientRect();
    const priceScaleWidth = chart.priceScale("right").width();
    if (event.clientX < bounds.right - priceScaleWidth - 2) return;
    event.preventDefault();
    event.stopPropagation();
    setPriceMenu({
      left: Math.max(8, Math.min(event.clientX, window.innerWidth - 244)),
      top: Math.max(8, Math.min(event.clientY, window.innerHeight - 220)),
    });
  }

  const normalizedCount = normalizedBars.length;
  const interactive = Boolean(drawingMode && (drawingMode !== "select" || drawings.length > 0));
  return <div
    ref={host}
    className={`market-chart ${compact ? "compact" : ""}`}
    data-bars={visibleCount == null ? normalizedCount : Math.min(normalizedCount, visibleCount)}
    data-effective-bars={normalizedCount}
    data-source-bars={bars.length}
    data-dropped-bars={bars.length - normalizedCount}
    data-first-time={normalizedBars[0]?.time}
    data-last-time={normalizedBars.at(-1)?.time}
    data-right-padding-bars={rightPaddingBars ?? 0}
    data-drawing-mode={drawingMode ?? "pan"}
    data-drawings={drawings.length}
    data-drawing-kinds={drawings.map(drawing => drawing.kind).join(",")}
    data-drawing-styles={drawings.map(drawing => `${drawing.color || "#111315"}:${drawing.lineWidth || 1.5}`).join(",")}
    data-selected-drawing={activeSelected ?? ""}
    data-price-scale-mode={priceScaleMode}
    onContextMenuCapture={openPriceScaleMenu}
  >
    <canvas
      ref={overlay}
      className={`drawing-overlay ${interactive ? drawingMode === "select" ? "selecting" : "drawing" : ""}`}
      aria-label={drawingMode === "select" ? "选择和调整画线" : drawingMode ? `绘制${drawingMode}` : undefined}
      tabIndex={interactive ? 0 : -1}
      onKeyDown={keyDown}
      onPointerDown={pointerDown}
      onPointerMove={pointerMove}
      onPointerUp={pointerUp}
      onPointerCancel={pointerUp}
      onPointerLeave={pointerLeave}
      onDoubleClick={doubleClick}
    />
    {enablePriceScaleMenu && priceMenu && <div
      className="price-scale-menu"
      role="menu"
      aria-label="价格刻度设置"
      style={{ left: priceMenu.left, top: priceMenu.top }}
      onPointerDown={event => event.stopPropagation()}
    >
      <b>价格刻度</b>
      <button role="menuitemradio" aria-checked={priceScaleMode === "auto"} onClick={() => changePriceScaleMode("auto")}>
        <span>自动适配 / 恢复默认</span><small>6个月视窗、右侧留白、当前价格范围</small>
      </button>
      <button role="menuitemradio" aria-checked={priceScaleMode === "locked"} onClick={() => changePriceScaleMode("locked")}>
        <span>锁定价格比例</span><small>保持纵向比例，可水平拖动时间轴</small>
      </button>
      <button role="menuitemradio" aria-checked={priceScaleMode === "free"} onClick={() => changePriceScaleMode("free")}>
        <span>自由价格比例</span><small>可拖动右侧价格轴改变纵向范围</small>
      </button>
    </div>}
  </div>;
});
