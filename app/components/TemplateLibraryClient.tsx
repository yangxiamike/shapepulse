"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
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
import type { TemplateDefinition, TemplateStock } from "../lib/types";
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
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const loadDetail = useCallback(async (id: string) => {
    setSelectedId(id);
    setDetailLoading(true);
    setError("");
    try {
      const [detail, ranked] = await Promise.all([api.template(id), api.templateStocks(id, 100)]);
      setSelected(detail);
      setEditingName(detail.name);
      setStocks(ranked.items);
      setTotal(ranked.total);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "模板详情读取失败");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const items = await api.templates();
      setTemplates(items);
      const query = typeof window === "undefined" ? "" : new URLSearchParams(window.location.search).get("template") || "";
      const first = items.find(item => item.id === query)?.id || items[0]?.id || "";
      if (first) await loadDetail(first);
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
              {detailLoading ? <StateCard title="正在分析模板" text="正在读取真实窗口与同模板 Top 股票。" /> :
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
                      <div><span>本模板内独立排名</span><h3>Top 股票</h3></div>
                      <small>整行可进入行情页，并保留模板与列表上下文。</small>
                    </div>
                    <div className={styles.stockTable}>
                      {stocks.map(item => (
                        <Link key={`${selected.id}-${item.ts_code}`} href={`/market?code=${encodeURIComponent(item.code)}&template=${encodeURIComponent(selected.id)}`}>
                          <b>{item.rank}</b>
                          <span><strong>{item.name}</strong><small>{item.code} · {item.industry || "行业待补"}</small></span>
                          <span className={styles.window}><strong>{item.score.toFixed(3)}</strong><small>{formatDate(item.start_date)} → {formatDate(item.end_date)}</small></span>
                          <CandlestickPreview className={styles.miniCandle} bars={item.bars} height={56} label={`${item.name}候选窗口真实前复权 K 线`} />
                          <ChevronRight aria-hidden="true" />
                        </Link>
                      ))}
                      {!stocks.length ? <p>这个模板暂时没有可展示的候选股票。</p> : null}
                    </div>
                  </section>
                </> : <StateCard title="请选择模板" text="从左侧选择冻结模板或自定义模板。" />}
            </section>
          </div>}
      </main>
    </div>
  );
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
