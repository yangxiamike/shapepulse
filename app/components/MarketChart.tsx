"use client";

import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import type { Bar } from "../lib/types";

export type DrawingKind = "line" | "horizontal" | "text" | "measure";
export type ChartDrawing = {
  kind: DrawingKind;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  text?: string;
};

type Props = {
  bars: Bar[];
  compact?: boolean;
  drawingMode?: DrawingKind | null;
  crosshairEnabled?: boolean;
  onDrawComplete?: (drawing: ChartDrawing) => void;
  drawings?: ChartDrawing[];
  onRendered?: (durationMs: number) => void;
};

export function MarketChart({
  bars,
  compact = false,
  drawingMode,
  crosshairEnabled = true,
  onDrawComplete,
  drawings = [],
  onRendered,
}: Props) {
  const host = useRef<HTMLDivElement>(null);
  const overlay = useRef<HTMLCanvasElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const ma5Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ma10Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ma20Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const startPoint = useRef<{ x: number; y: number } | null>(null);
  const previewPoint = useRef<{ x: number; y: number } | null>(null);
  const drawingsRef = useRef(drawings);
  const modeRef = useRef(drawingMode);

  function paintDrawings() {
    const canvas = overlay.current;
    const container = host.current;
    if (!canvas || !container) return;
    const ratio = window.devicePixelRatio || 1;
    const width = container.clientWidth;
    const height = container.clientHeight;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(ratio, ratio);
    ctx.strokeStyle = "#111315";
    ctx.fillStyle = "#111315";
    ctx.lineWidth = 1.5;
    ctx.font = '13px "Microsoft YaHei UI", sans-serif';
    const all = [...drawingsRef.current];
    if (startPoint.current && previewPoint.current && modeRef.current) {
      all.push({ kind: modeRef.current, x1: startPoint.current.x, y1: startPoint.current.y, x2: previewPoint.current.x, y2: previewPoint.current.y });
    }
    all.forEach(drawing => {
      if (drawing.kind === "text") {
        ctx.fillText(drawing.text || "文本标记", drawing.x1 + 5, drawing.y1 - 5);
        ctx.beginPath();
        ctx.arc(drawing.x1, drawing.y1, 3, 0, Math.PI * 2);
        ctx.fill();
        return;
      }
      ctx.save();
      if (drawing.kind === "measure") ctx.setLineDash([5, 4]);
      ctx.beginPath();
      ctx.moveTo(drawing.x1, drawing.y1);
      ctx.lineTo(drawing.x2, drawing.kind === "horizontal" ? drawing.y1 : drawing.y2);
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
      ctx.restore();
    });
  }

  useEffect(() => {
    if (!host.current) return;
    const chart = createChart(host.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#fcfbf8" }, textColor: "#4f5354", fontFamily: '"Microsoft YaHei UI", sans-serif', fontSize: 12 },
      grid: { vertLines: { color: "#ece9e2", style: 1 }, horzLines: { color: "#e8e5de", style: 1 } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: "#656868", style: 3 }, horzLine: { color: "#656868", style: 3 } },
      rightPriceScale: { borderColor: "#d8d5cd", scaleMargins: { top: 0.08, bottom: 0.28 } },
      timeScale: { borderColor: "#d8d5cd", timeVisible: false, rightOffset: 4, barSpacing: 6, minBarSpacing: 1.8 },
      handleScale: true,
      handleScroll: true,
    });
    chartRef.current = chart;
    candleRef.current = chart.addSeries(CandlestickSeries, { upColor: "#f04444", downColor: "#20aa7b", borderUpColor: "#f04444", borderDownColor: "#20aa7b", wickUpColor: "#f04444", wickDownColor: "#20aa7b" });
    volumeRef.current = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "volume", lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    ma5Ref.current = chart.addSeries(LineSeries, { color: "#34bc92", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    ma10Ref.current = chart.addSeries(LineSeries, { color: "#2864ff", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    ma20Ref.current = chart.addSeries(LineSeries, { color: "#8856e8", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const ro = new ResizeObserver(paintDrawings);
    ro.observe(host.current);
    return () => { ro.disconnect(); chart.remove(); chartRef.current = null; };
  }, []);

  useEffect(() => {
    const started = performance.now();
    candleRef.current?.setData(bars.map(b => ({ time: b.time as Time, open: b.open, high: b.high, low: b.low, close: b.close })));
    volumeRef.current?.setData(bars.map(b => ({ time: b.time as Time, value: b.volume, color: b.close >= b.open ? "rgba(240,68,68,.78)" : "rgba(32,170,123,.78)" })));
    ma5Ref.current?.setData(bars.filter(b => b.ma5 != null).map(b => ({ time: b.time as Time, value: b.ma5! })));
    ma10Ref.current?.setData(bars.filter(b => b.ma10 != null).map(b => ({ time: b.time as Time, value: b.ma10! })));
    ma20Ref.current?.setData(bars.filter(b => b.ma20 != null).map(b => ({ time: b.time as Time, value: b.ma20! })));
    chartRef.current?.timeScale().fitContent();
    requestAnimationFrame(() => requestAnimationFrame(() => onRendered?.(performance.now() - started)));
  }, [bars, onRendered]);

  useEffect(() => {
    chartRef.current?.applyOptions({
      crosshair: { mode: crosshairEnabled ? CrosshairMode.Normal : CrosshairMode.Hidden },
      rightPriceScale: { scaleMargins: compact ? { top: 0.1, bottom: 0.28 } : { top: 0.08, bottom: 0.28 } },
      timeScale: { barSpacing: compact ? 7 : 6 },
    });
  }, [compact, crosshairEnabled]);

  useEffect(() => {
    drawingsRef.current = drawings;
    modeRef.current = drawingMode;
    paintDrawings();
  }, [drawings, drawingMode]);

  function point(e: React.PointerEvent<HTMLCanvasElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function pointerDown(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!drawingMode) return;
    startPoint.current = point(e);
    previewPoint.current = startPoint.current;
    e.currentTarget.setPointerCapture(e.pointerId);
    paintDrawings();
  }

  function pointerMove(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!drawingMode || !startPoint.current) return;
    previewPoint.current = point(e);
    paintDrawings();
  }

  function pointerUp(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!drawingMode || !startPoint.current) return;
    const end = point(e);
    const start = startPoint.current;
    onDrawComplete?.({ kind: drawingMode, x1: start.x, y1: start.y, x2: end.x, y2: drawingMode === "horizontal" ? start.y : end.y, text: drawingMode === "text" ? "文本标记" : undefined });
    startPoint.current = null;
    previewPoint.current = null;
    paintDrawings();
  }

  return <div ref={host} className={`market-chart ${compact ? "compact" : ""}`} data-bars={bars.length}>
    <canvas ref={overlay} className={`drawing-overlay ${drawingMode ? "drawing" : ""}`} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} />
  </div>;
}
