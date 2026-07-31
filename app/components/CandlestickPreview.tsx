"use client";

import { useMemo } from "react";
import type { Bar } from "../lib/types";

type Props = {
  bars: Bar[];
  label: string;
  className?: string;
  height?: number;
};

export function CandlestickPreview({ bars, label, className = "", height = 150 }: Props) {
  const geometry = useMemo(() => {
    const clean = bars.filter(bar =>
      [bar.open, bar.high, bar.low, bar.close].every(Number.isFinite),
    );
    const width = 720;
    const padding = 10;
    const min = Math.min(...clean.map(bar => bar.low));
    const max = Math.max(...clean.map(bar => bar.high));
    const spread = Math.max(max - min, Math.abs(max) * 0.001, 0.001);
    const step = (width - padding * 2) / Math.max(1, clean.length);
    const candleWidth = Math.max(1.2, Math.min(8, step * 0.62));
    const y = (value: number) => padding + (max - value) / spread * (height - padding * 2);
    return { clean, width, padding, step, candleWidth, y };
  }, [bars, height]);

  if (!geometry.clean.length) {
    return <div className={`candle-preview-empty ${className}`}>真实 K 线暂不可用</div>;
  }

  return (
    <svg
      className={`candle-preview ${className}`}
      viewBox={`0 0 ${geometry.width} ${height}`}
      role="img"
      aria-label={label}
      preserveAspectRatio="none"
    >
      <line className="candle-grid" x1="0" x2={geometry.width} y1={height / 2} y2={height / 2} />
      {geometry.clean.map((bar, index) => {
        const x = geometry.padding + geometry.step * index + geometry.step / 2;
        const up = bar.close >= bar.open;
        const bodyTop = geometry.y(Math.max(bar.open, bar.close));
        const bodyBottom = geometry.y(Math.min(bar.open, bar.close));
        return (
          <g className={up ? "candle-up" : "candle-down"} key={`${bar.time}-${index}`}>
            <line x1={x} x2={x} y1={geometry.y(bar.high)} y2={geometry.y(bar.low)} />
            <rect
              x={x - geometry.candleWidth / 2}
              y={bodyTop}
              width={geometry.candleWidth}
              height={Math.max(1, bodyBottom - bodyTop)}
            />
          </g>
        );
      })}
    </svg>
  );
}
