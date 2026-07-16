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

type Props = {
  bars: Bar[];
  compact?: boolean;
  drawingMode?: string | null;
  onDrawComplete?: (line: { x1: number; y1: number; x2: number; y2: number }) => void;
  drawings?: Array<{ x1: number; y1: number; x2: number; y2: number }>;
};

export function MarketChart({ bars, compact = false, drawingMode, onDrawComplete, drawings = [] }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const overlay = useRef<HTMLCanvasElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const startPoint = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const chart = createChart(host.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#fcfbf8" }, textColor: "#4f5354", fontFamily: '"Microsoft YaHei UI", sans-serif', fontSize: 11 },
      grid: { vertLines: { color: "#ece9e2", style: 1 }, horzLines: { color: "#e8e5de", style: 1 } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: "#656868", style: 3 }, horzLine: { color: "#656868", style: 3 } },
      rightPriceScale: { borderColor: "#d8d5cd", scaleMargins: compact ? { top: 0.12, bottom: 0.26 } : { top: 0.08, bottom: 0.28 } },
      timeScale: { borderColor: "#d8d5cd", timeVisible: false, rightOffset: 4, barSpacing: compact ? 7 : 5, minBarSpacing: 1.5 },
      handleScale: true,
      handleScroll: true,
    });
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#f04444", downColor: "#20aa7b", borderUpColor: "#f04444", borderDownColor: "#20aa7b", wickUpColor: "#f04444", wickDownColor: "#20aa7b",
    });
    const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "volume", lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    const ma5 = chart.addSeries(LineSeries, { color: "#34bc92", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const ma10 = chart.addSeries(LineSeries, { color: "#2864ff", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const ma20 = chart.addSeries(LineSeries, { color: "#8856e8", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    candles.setData(bars.map(b => ({ time: b.time as Time, open: b.open, high: b.high, low: b.low, close: b.close })));
    volume.setData(bars.map(b => ({ time: b.time as Time, value: b.volume, color: b.close >= b.open ? "rgba(240,68,68,.78)" : "rgba(32,170,123,.78)" })));
    ma5.setData(bars.filter(b => b.ma5 != null).map(b => ({ time: b.time as Time, value: b.ma5! })));
    ma10.setData(bars.filter(b => b.ma10 != null).map(b => ({ time: b.time as Time, value: b.ma10! })));
    ma20.setData(bars.filter(b => b.ma20 != null).map(b => ({ time: b.time as Time, value: b.ma20! })));
    chart.timeScale().fitContent();
    chartRef.current = chart;
    candleRef.current = candles;
    const ro = new ResizeObserver(() => paintDrawings());
    ro.observe(host.current);
    function paintDrawings() {
      const canvas = overlay.current;
      const container = host.current;
      if (!canvas || !container) return;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = container.clientWidth * ratio;
      canvas.height = container.clientHeight * ratio;
      canvas.style.width = `${container.clientWidth}px`;
      canvas.style.height = `${container.clientHeight}px`;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.scale(ratio, ratio);
      ctx.strokeStyle = "#111315";
      ctx.lineWidth = 1.5;
      drawings.forEach(d => { ctx.beginPath(); ctx.moveTo(d.x1, d.y1); ctx.lineTo(d.x2, d.y2); ctx.stroke(); });
    }
    paintDrawings();
    return () => { ro.disconnect(); chart.remove(); chartRef.current = null; candleRef.current = null; };
  }, [bars, compact, drawings]);

  function pointerDown(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!drawingMode) return;
    startPoint.current = { x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY };
    e.currentTarget.setPointerCapture(e.pointerId);
  }

  function pointerUp(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!drawingMode || !startPoint.current) return;
    const end = { x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY };
    onDrawComplete?.({ x1: startPoint.current.x, y1: startPoint.current.y, x2: end.x, y2: end.y });
    startPoint.current = null;
  }

  return (
    <div ref={host} className={`market-chart ${compact ? "compact" : ""}`}>
      <canvas ref={overlay} className={`drawing-overlay ${drawingMode ? "drawing" : ""}`} onPointerDown={pointerDown} onPointerUp={pointerUp} />
    </div>
  );
}
