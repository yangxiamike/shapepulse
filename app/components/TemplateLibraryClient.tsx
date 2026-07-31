"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronRight,
  Edit3,
  LibraryBig,
  Plus,
  RotateCcw,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { api } from "../lib/api";
import type { Bar, TemplateDefinition, TemplateStock } from "../lib/types";
import { AppSidebar } from "./AppSidebar";
import { CandlestickPreview } from "./CandlestickPreview";
import styles from "./TemplateLibraryClient.module.css";

function formatDate(value?: string | null) {
  const text = String(value || "").replaceAll("-", "");
  return text.length === 8 ? `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6)}` : "—";
}

export function TemplateLibraryClient() {
  const [templates, setTemplates] = useState<TemplateDefinition[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [selected, setSelected] = useState<TemplateDefinition | null>(null);
  const [stocks, setStocks] = useState<TemplateStock[]>([]);
  const [total, setTotal] = useState(0);
  const [editingName, setEditingName] = useState("");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [rankingLoading, setRankingLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [rankingError, setRankingError] = useState("");
  const detailSequence = useRef(0);

  const loadDetail = useCallback(async (id: string) => {
    const sequence = ++detailSequence.current;
    setSelectedId(id);
    setSelected(null);
    setStocks([]);
    setTotal(0);
    setDetailLoading(true);
    setRankingLoading(true);
    setError("");
    setRankingError("");
    const detailTask = api.template(id)
      .then(detail => {
        if (sequence !== detailSequence.current) return;
        setSelected(detail);
        setEditingName(detail.name);
      })
      .catch(reason => {
        if (sequence === detailSequence.current) {
          setError(reason instanceof Error ? reason.message : "模板真实 K 线读取失败");
        }
      })
      .finally(() => {
        if (sequence === detailSequence.current) setDetailLoading(false);
      });
    const rankingTask = api.templateStocks(id, 100)
      .then(ranked => {
        if (sequence !== detailSequence.current) return;
        setStocks(ranked.items);
        setTotal(ranked.total);
      })
      .catch(reason => {
        if (sequence === detailSequence.current) {
          setRankingError(reason instanceof Error ? reason.message : "Top100 排名读取失败");
        }
      })
      .finally(() => {
        if (sequence === detailSequence.current) setRankingLoading(false);
      });
    await Promise.allSettled([detailTask, rankingTask]);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const items = await api.templates();
      setTemplates(items);
      const query = typeof window === "undefined" ? "" : new URLSearchParams(window.location.search).get("template") || "";
      const first = items.find(item => item.id === query)?.id || items[0]?.id || "";
      if (first) void loadDetail(first);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "模板库读取失败");
    } finally {
      setLoading(false);
    }
  }, [loadDetail]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const frozen = useMemo(() => templates.filter(item => item.kind === "frozen"), [templates]);
  const custom = useMemo(() => templates.filter(item => item.kind === "custom"), [templates]);

  async function renameSelected() {
    if (!selected || selected.kind !== "custom" || !editingName.trim()) return;
    setSaving(true);
    try {
      const next = await api.renameTemplate(selected.id, editingName.trim());
      setSelected(next);
      setTemplates(items => items.map(item => item.id === next.id ? { ...item, name: next.name } : item));
    } finally {
      setSaving(false);
    }
  }

  async function deleteSelected() {
    if (!selected || selected.kind !== "custom") return;
    if (!window.confirm(`删除自定义模板“${selected.name}”？此操作不可撤销。`)) return;
    setSaving(true);
    try {
      await api.deleteTemplate(selected.id);
      const next = templates.filter(item => item.id !== selected.id);
      setTemplates(next);
      setSelected(null);
      setStocks([]);
      if (next[0]) await loadDetail(next[0].id);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={`app-shell ${styles.shell}`}>
      <AppSidebar active="templates" />
      <main className={styles.main}>
        <header className={styles.pageHead}>
          <div>
            <span><LibraryBig aria-hidden="true" /> 真实前复权 K 线模板</span>
            <h1>模板库</h1>
            <p>浏览冻结四模板和自定义模板。匹配只比较窗口内形状，不使用未来表现。</p>
          </div>
          <Link className={styles.createLink} href="/templates/new"><Plus />新建模板</Link>
        </header>

        {loading ? <StateCard title="正在读取模板库" text="只读取本机行情与模板数据。" /> :
          error && !templates.length ? <StateCard title="模板库暂不可用" text={error} action={<button onClick={() => void load()}><RotateCcw />重试</button>} /> :
          <div className={styles.libraryLayout}>
            <aside className={styles.templateRail}>
              <TemplateGroup title="冻结四模板" note="定义固定，只读" items={frozen} selectedId={selectedId} onSelect={loadDetail} />
              <TemplateGroup title="我的模板" note={`${custom.length} 个已保存`} items={custom} selectedId={selectedId} onSelect={loadDetail} empty="暂无自定义模板，可从“新建模板”开始。" />
            </aside>

            <section className={styles.detailCard}>
              {detailLoading && !selected ? <StateCard title="正在读取模板 K 线" text="排名和缩略图不会阻塞这张主图。" /> :
                selected ? <>
                  <div className={styles.detailHead}>
                    <div>
                      <span>{selected.kind === "frozen" ? "冻结模板 · 只读" : "自定义模板"}</span>
                      <h2>{selected.name}</h2>
                      <p>{selected.description || selected.cue || "比较真实前复权 K 线的窗口内形状。"}</p>
                    </div>
                    {selected.kind === "custom" ? <div className={styles.templateActions}>
                      <label><span>名称</span><input value={editingName} onChange={event => setEditingName(event.target.value)} /></label>
                      <button disabled={saving || !editingName.trim()} onClick={() => void renameSelected()}><Edit3 />改名</button>
                      <button className={styles.deleteButton} disabled={saving} onClick={() => void deleteSelected()}><Trash2 />删除</button>
                    </div> : null}
                  </div>

                  <div className={styles.templateFacts}>
                    <span><small>模板窗口</small><strong>{selected.window_length || selected.bars.length} 个交易日</strong></span>
                    <span><small>来源股票</small><strong>{selected.source_name || selected.source_ts_code || "冻结定义"}</strong></span>
                    <span><small>起止日期</small><strong>{formatDate(selected.start_date)} 至 {formatDate(selected.end_date)}</strong></span>
                    <span><small>同模板候选</small><strong>{total} 只</strong></span>
                  </div>

                  <section className={styles.curveCard}>
                    <div>
                      <span>真实前复权 K 线</span>
                      <h3>模板起止窗口</h3>
                      <p>{formatDate(selected.start_date)} → {formatDate(selected.end_date)}。图中每根蜡烛均来自本机前复权日线。</p>
                    </div>
                    <CandlestickPreview bars={selected.bars} height={250} label={`${selected.name}真实前复权 K 线，${formatDate(selected.start_date)}至${formatDate(selected.end_date)}`} />
                  </section>

                  <section className={styles.stockSection}>
                    <div className={styles.stockHead}>
                      <div><span>本模板内独立排名</span><h3>Top100 股票</h3></div>
                      <small>{rankingLoading ? "正在读取预计算排名…" : rankingError ? rankingError : "排名已就绪 · 缩略图按可见行加载"}</small>
                    </div>
                    <div className={styles.stockTable}>
                      {stocks.map(item => (
                        <Link key={`${selected.id}-${item.ts_code}`} href={`/market?code=${encodeURIComponent(item.code)}&template=${encodeURIComponent(selected.id)}`}>
                          <b>{item.rank}</b>
                          <span><strong>{item.name}</strong><small>{item.code} · {item.industry || "行业待补"}</small></span>
                          <span className={styles.window}><strong>{item.score.toFixed(3)}</strong><small>{formatDate(item.start_date)} → {formatDate(item.end_date)}</small></span>
                          <LazyCandidatePreview item={item} />
                          <ChevronRight aria-hidden="true" />
                        </Link>
                      ))}
                      {rankingLoading ? <p className={styles.rankingState}>正在加载 Top100 排名，主模板 K 线可先查看。</p> : null}
                      {!rankingLoading && !stocks.length ? <p>这个模板暂时没有可展示的候选股票。</p> : null}
                    </div>
                  </section>
                </> : <StateCard title="请选择模板" text="从左侧选择冻结模板或自定义模板。" />}
            </section>
          </div>}
      </main>
    </div>
  );
}

function LazyCandidatePreview({ item }: { item: TemplateStock }) {
  const host = useRef<HTMLDivElement>(null);
  const [bars, setBars] = useState<Bar[]>(item.bars || []);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">(item.bars?.length ? "ready" : "idle");

  useEffect(() => {
    if (bars.length || !item.start_date || !item.end_date) return;
    const element = host.current;
    if (!element) return;
    let active = true;
    const load = () => {
      if (!active) return;
      setState("loading");
      void api.barsWindow(item.code, item.start_date!, item.end_date!, item.window_length || 240)
        .then(result => {
          if (!active) return;
          setBars(result.items);
          setState("ready");
        })
        .catch(() => {
          if (active) setState("error");
        });
    };
    if (!("IntersectionObserver" in window)) {
      load();
      return () => { active = false; };
    }
    const observer = new IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting)) return;
      observer.disconnect();
      load();
    }, { rootMargin: "240px 0px" });
    observer.observe(element);
    return () => {
      active = false;
      observer.disconnect();
    };
  }, [bars.length, item.code, item.end_date, item.start_date, item.window_length]);

  return <div ref={host} className={styles.thumbnailCell} data-thumbnail-state={state}>
    {bars.length
      ? <CandlestickPreview className={styles.miniCandle} bars={bars} height={56} label={`${item.name}候选窗口真实前复权 K 线`} />
      : <span>{state === "loading" ? "加载缩略图…" : state === "error" ? "缩略图稍后重试" : "滚动到此处加载缩略图"}</span>}
  </div>;
}

function TemplateGroup({ title, note, items, selectedId, onSelect, empty }: {
  title: string; note: string; items: TemplateDefinition[]; selectedId: string;
  onSelect: (id: string) => void; empty?: string;
}) {
  return <section className={styles.templateGroup}>
    <div><h2>{title}</h2><span>{note}</span></div>
    {items.length ? items.map(item => <button type="button" className={item.id === selectedId ? styles.active : ""} aria-pressed={item.id === selectedId} onClick={() => onSelect(item.id)} key={item.id}>
      <span><strong>{item.name}</strong><small>{item.source_ts_code || "冻结定义"} · {item.window_length} 日</small></span><ChevronRight />
    </button>) : <p>{empty || "暂无模板。"}</p>}
  </section>;
}

function StateCard({ title, text, action }: { title: string; text: string; action?: React.ReactNode }) {
  return <section className={styles.stateCard}><TriangleAlert /><strong>{title}</strong><span>{text}</span>{action}</section>;
}
