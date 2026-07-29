"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { ArrowLeft, Check, LoaderCircle, Search, Save, TriangleAlert, X } from "lucide-react";
import { api } from "../lib/api";
import type { Bar, Stock } from "../lib/types";
import { AppSidebar } from "./AppSidebar";
import { CandlestickPreview } from "./CandlestickPreview";
import styles from "./NewTemplateClient.module.css";

const MIN_DAYS = 20;
const MAX_DAYS = 240;
type Handle = "start" | "end" | "window";

function compactDate(value?: string) {
  return String(value || "").replaceAll("-", "");
}

function readableDate(value?: string) {
  const text = compactDate(value);
  return text.length === 8 ? `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6)}` : "—";
}

export function NewTemplateClient() {
  const chartRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<{ handle: Handle; originIndex: number; start: number; end: number } | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Stock[]>([]);
  const [stock, setStock] = useState<Stock | null>(null);
  const [bars, setBars] = useState<Bar[]>([]);
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState(0);
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(async () => {
      if (!query.trim()) return setResults([]);
      try {
        const response = await api.search(query.trim());
        setResults(response.items.slice(0, 8));
      } catch { setResults([]); }
    }, 180);
    return () => window.clearTimeout(timer);
  }, [query]);

  async function chooseStock(item: Stock) {
    setStock(item);
    setQuery(`${item.name} ${item.code}`);
    setResults([]);
    setLoading(true);
    setError("");
    try {
      const response = await api.bars(item.code, "D", "ALL");
      const next = response.items;
      setBars(next);
      const nextEnd = Math.max(0, next.length - 1);
      setEnd(nextEnd);
      setStart(Math.max(0, nextEnd - 59));
      setName(`${item.name} 形态窗口`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "真实前复权日线读取失败");
    } finally {
      setLoading(false);
    }
  }

  const count = bars.length ? end - start + 1 : 0;
  const valid = count >= MIN_DAYS && count <= MAX_DAYS;
  const validation = count < MIN_DAYS
    ? `还差 ${MIN_DAYS - count} 个交易日，最少需要 ${MIN_DAYS} 日`
    : count > MAX_DAYS
      ? `超出 ${count - MAX_DAYS} 个交易日，最多允许 ${MAX_DAYS} 日`
      : `窗口有效：${count} 个实际交易日`;

  const geometry = useMemo(() => {
    const width = 1200;
    const height = 430;
    const pad = { left: 18, right: 18, top: 18, bottom: 28 };
    const min = Math.min(...bars.map(bar => bar.low));
    const max = Math.max(...bars.map(bar => bar.high));
    const spread = Math.max(max - min, Math.abs(max) * .001, .001);
    const step = (width - pad.left - pad.right) / Math.max(1, bars.length);
    const candleWidth = Math.max(.6, Math.min(5, step * .68));
    const x = (index: number) => pad.left + step * index + step / 2;
    const y = (value: number) => pad.top + (max - value) / spread * (height - pad.top - pad.bottom);
    return { width, height, pad, step, candleWidth, x, y };
  }, [bars]);

  function eventIndex(event: PointerEvent<SVGElement>) {
    const rect = chartRef.current?.getBoundingClientRect();
    if (!rect) return 0;
    const scaledX = (event.clientX - rect.left) / rect.width * geometry.width;
    return Math.max(0, Math.min(bars.length - 1, Math.round((scaledX - geometry.pad.left) / geometry.step)));
  }

  function beginDrag(event: PointerEvent<SVGElement>, handle: Handle) {
    if (!bars.length) return;
    dragRef.current = { handle, originIndex: eventIndex(event), start, end };
    chartRef.current?.setPointerCapture(event.pointerId);
  }

  function captureBoundaryHit(event: PointerEvent<SVGSVGElement>) {
    if (!bars.length || event.button !== 0) return;
    const rect = chartRef.current?.getBoundingClientRect();
    if (!rect) return;
    const startClientX = rect.left + selectionX / geometry.width * rect.width;
    const endClientX = rect.left + (selectionX + selectionWidth) / geometry.width * rect.width;
    const startDistance = Math.abs(event.clientX - startClientX);
    const endDistance = Math.abs(event.clientX - endClientX);
    if (Math.min(startDistance, endDistance) > 22) return;
    event.stopPropagation();
    beginDrag(event, startDistance <= endDistance ? "start" : "end");
  }

  function moveDrag(event: PointerEvent<SVGSVGElement>) {
    const drag = dragRef.current;
    if (!drag) return;
    const index = eventIndex(event);
    if (drag.handle === "start") setStart(Math.min(index, end));
    else if (drag.handle === "end") setEnd(Math.max(index, start));
    else {
      const delta = index - drag.originIndex;
      const length = drag.end - drag.start;
      const nextStart = Math.max(0, Math.min(bars.length - 1 - length, drag.start + delta));
      setStart(nextStart);
      setEnd(nextStart + length);
    }
  }

  function finishDrag(event: PointerEvent<SVGSVGElement>) {
    dragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }

  function moveBoundary(handle: "start" | "end", event: KeyboardEvent<SVGGElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const step = event.shiftKey ? 5 : 1;
    const delta = event.key === "ArrowLeft" ? -step : step;
    if (handle === "start") setStart(value => Math.max(0, Math.min(end, value + delta)));
    else setEnd(value => Math.max(start, Math.min(bars.length - 1, value + delta)));
  }

  async function save() {
    if (!stock || !valid || !name.trim()) return;
    setSaving(true);
    setError("");
    try {
      const template = await api.createTemplate({
        name: name.trim(),
        source_ts_code: stock.ts_code,
        start_date: compactDate(bars[start].trade_date || bars[start].time),
        end_date: compactDate(bars[end].trade_date || bars[end].time),
      });
      window.location.assign(`/templates?template=${encodeURIComponent(template.id)}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "模板保存失败");
      setSaving(false);
    }
  }

  const selectionX = bars.length ? geometry.x(start) - geometry.step / 2 : 0;
  const selectionWidth = bars.length ? (end - start + 1) * geometry.step : 0;

  return <div className={`app-shell ${styles.shell}`}>
    <AppSidebar active="templates" />
    <main className={styles.main}>
      <header className={styles.pageHead}>
        <div><span>真实 K 线框选</span><h1>新建模板</h1><p>先找股票，再拖动两个边界框出一段历史窗口。</p></div>
        <Link href="/templates"><ArrowLeft />返回模板库</Link>
      </header>

      <section className={styles.searchCard}>
        <label><span>1 · 搜索股票</span><div><Search /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="输入股票名称、代码或拼音首字母" />{query ? <button onClick={() => { setQuery(""); setResults([]); }} aria-label="清空"><X /></button> : null}</div></label>
        {results.length ? <div className={styles.results}>{results.map(item => <button key={item.ts_code} onClick={() => void chooseStock(item)}><span><strong>{item.name}</strong><small>{item.code} · {item.industry || "行业待补"}</small></span><Check /></button>)}</div> : null}
      </section>

      <section className={styles.chartCard}>
        <div className={styles.chartHead}>
          <div><span>2 · 框选历史窗口</span><h2>{stock ? `${stock.name} ${stock.code}` : "等待选择股票"}</h2></div>
          {bars.length ? <div className={valid ? styles.valid : styles.invalid}><strong>{count} 个交易日</strong><small>{validation}</small></div> : null}
        </div>
        {loading ? <div className={styles.state}><LoaderCircle className="spin" />正在读取完整前复权日线…</div> :
          bars.length ? <div className={styles.chartWrap}>
            <svg
              ref={chartRef}
              viewBox={`0 0 ${geometry.width} ${geometry.height}`}
              className={styles.chart}
              role="img"
              aria-label={`${stock?.name}完整前复权 K 线，可拖动左右边界选择模板窗口`}
              onPointerDownCapture={captureBoundaryHit}
              onPointerMove={moveDrag}
              onPointerUp={finishDrag}
              onPointerCancel={finishDrag}
            >
              {[.25, .5, .75].map(ratio => <line className={styles.grid} key={ratio} x1="0" x2={geometry.width} y1={geometry.height * ratio} y2={geometry.height * ratio} />)}
              {bars.map((bar, index) => {
                const x = geometry.x(index);
                const up = bar.close >= bar.open;
                const top = geometry.y(Math.max(bar.open, bar.close));
                const bottom = geometry.y(Math.min(bar.open, bar.close));
                return <g className={up ? styles.up : styles.down} key={`${bar.time}-${index}`}><line x1={x} x2={x} y1={geometry.y(bar.high)} y2={geometry.y(bar.low)} /><rect x={x - geometry.candleWidth / 2} y={top} width={geometry.candleWidth} height={Math.max(.8, bottom - top)} /></g>;
              })}
              <rect className={`${styles.selection} ${valid ? "" : styles.selectionInvalid}`} x={selectionX} y="0" width={selectionWidth} height={geometry.height} onPointerDown={event => beginDrag(event, "window")} />
              <g className={styles.handle} tabIndex={0} role="slider" aria-label="模板窗口开始边界" aria-valuemin={1} aria-valuemax={end + 1} aria-valuenow={start + 1} onKeyDown={event => moveBoundary("start", event)} onPointerDown={event => beginDrag(event, "start")}><rect x={selectionX - 16} y="0" width="32" height={geometry.height} /><line x1={selectionX} x2={selectionX} y1="0" y2={geometry.height} /></g>
              <g className={styles.handle} tabIndex={0} role="slider" aria-label="模板窗口结束边界" aria-valuemin={start + 1} aria-valuemax={bars.length} aria-valuenow={end + 1} onKeyDown={event => moveBoundary("end", event)} onPointerDown={event => beginDrag(event, "end")}><rect x={selectionX + selectionWidth - 16} y="0" width="32" height={geometry.height} /><line x1={selectionX + selectionWidth} x2={selectionX + selectionWidth} y1="0" y2={geometry.height} /></g>
              <text x={geometry.pad.left} y={geometry.height - 7}>{readableDate(bars[0].time)}</text>
              <text textAnchor="end" x={geometry.width - geometry.pad.right} y={geometry.height - 7}>{readableDate(bars.at(-1)?.time)}</text>
            </svg>
            <p className={styles.brushHint}>拖动左、右边界调整起止日；拖动框内可整体平移。键盘方向键移动 1 日，Shift + 方向键移动 5 日。</p>
            <figure className={styles.selectionPreview}>
              <figcaption><span>选中窗口局部预览</span><strong>{readableDate(bars[start]?.time)} → {readableDate(bars[end]?.time)} · {count} 日</strong></figcaption>
              <CandlestickPreview bars={bars.slice(start, end + 1)} height={190} label={`${stock?.name}选中模板窗口局部真实前复权 K 线`} />
            </figure>
          </div> : <div className={styles.state}>搜索并选择一只股票后，这里展示完整真实 K 线。</div>}
      </section>

      <section className={styles.saveCard}>
        <div><span>3 · 确认并保存</span><h2>{bars.length ? `${readableDate(bars[start]?.time)} 至 ${readableDate(bars[end]?.time)}` : "尚未选择窗口"}</h2><p>交易日数按本地真实日线计算；后端仍会再次校验 20–240 日限制。</p></div>
        <label><span>模板名称</span><input value={name} onChange={event => setName(event.target.value)} maxLength={80} placeholder="给这段形态起个名字" /></label>
        <button disabled={!stock || !valid || !name.trim() || saving} onClick={() => void save()}>{saving ? <LoaderCircle className="spin" /> : <Save />}保存模板</button>
        {error ? <p className={styles.error} role="alert"><TriangleAlert />{error}</p> : null}
      </section>
    </main>
  </div>;
}
