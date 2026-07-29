"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import Link from "next/link";
import {
  CalendarRange,
  ChevronRight,
  Edit3,
  LibraryBig,
  LoaderCircle,
  Plus,
  RotateCcw,
  Save,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { AppSidebar } from "./AppSidebar";
import { api, formatDate } from "../lib/api";
import type {
  TemplateDefinition,
  TemplateStock,
} from "../lib/types";
import styles from "./TemplateLibraryClient.module.css";

const DEFAULT_TEMPLATE = "fresh_breakout";

function compactDate(value?: string | null) {
  return value ? value.replaceAll("-", "") : "";
}

function inputDate(value?: string | null) {
  const date = compactDate(value);
  return date.length === 8 ? `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}` : "";
}

function curveAnalysis(values: number[]) {
  if (values.length < 2) return "模板曲线尚未完整加载。";
  const change = values.at(-1)! - values[0];
  const peakIndex = values.indexOf(Math.max(...values));
  const troughIndex = values.indexOf(Math.min(...values));
  const direction = change > .6 ? "整体向上" : change < -.6 ? "整体向下" : "首尾接近";
  const timing = peakIndex > values.length * .75
    ? "高点靠近窗口后段"
    : troughIndex > values.length * .65
      ? "低点靠近窗口后段"
      : "高低点分布较均匀";
  return `${direction}，${timing}。这只是形状说明，不代表之后一定上涨或下跌。`;
}

export function TemplateLibraryClient() {
  const [templates, setTemplates] = useState<TemplateDefinition[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [selected, setSelected] = useState<TemplateDefinition | null>(null);
  const [stocks, setStocks] = useState<TemplateStock[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [formError, setFormError] = useState("");
  const [name, setName] = useState("");
  const [sourceCode, setSourceCode] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [editingName, setEditingName] = useState("");

  const frozen = useMemo(() => templates.filter(item => item.kind === "frozen"), [templates]);
  const custom = useMemo(() => templates.filter(item => item.kind === "custom"), [templates]);

  const loadDetail = useCallback(async (id: string) => {
    setSelectedId(id);
    setDetailLoading(true);
    setError("");
    try {
      const [definition, result] = await Promise.all([
        api.template(id),
        api.templateStocks(id, 100),
      ]);
      setSelected(definition);
      setStocks(result.items);
      setTotal(result.total);
      setEditingName(definition.name);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "模板详情读取失败");
      setSelected(null);
      setStocks([]);
      setTotal(0);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const load = useCallback(async (preferredId?: string) => {
    setLoading(true);
    setError("");
    try {
      const items = await api.templates();
      setTemplates(items);
      const next = items.find(item => item.id === preferredId || item.key === preferredId)
        || items.find(item => item.key === DEFAULT_TEMPLATE)
        || items[0];
      if (next) await loadDetail(next.id);
      else {
        setSelected(null);
        setStocks([]);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "模板库读取失败");
    } finally {
      setLoading(false);
    }
  }, [loadDetail]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setName(params.get("name") || "");
    setSourceCode(params.get("source_ts_code") || "");
    setStartDate(inputDate(params.get("start_date")));
    setEndDate(inputDate(params.get("end_date")));
    void load(params.get("template") || undefined);
  }, [load]);

  async function createTemplate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");
    if (!name.trim() || !sourceCode.trim() || !startDate || !endDate) {
      setFormError("请填写名称、股票代码和起止日期。");
      return;
    }
    if (startDate > endDate) {
      setFormError("开始日期不能晚于结束日期。");
      return;
    }
    setSaving(true);
    try {
      const created = await api.createTemplate({
        name: name.trim(),
        source_ts_code: sourceCode.trim(),
        start_date: compactDate(startDate),
        end_date: compactDate(endDate),
      });
      setName("");
      await load(created.id);
    } catch (reason) {
      setFormError(reason instanceof Error ? reason.message : "模板保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function renameSelected() {
    if (!selected || selected.kind !== "custom" || !editingName.trim()) return;
    setSaving(true);
    setFormError("");
    try {
      await api.renameTemplate(selected.id, editingName.trim());
      await load(selected.id);
    } catch (reason) {
      setFormError(reason instanceof Error ? reason.message : "重命名失败");
    } finally {
      setSaving(false);
    }
  }

  async function deleteSelected() {
    if (!selected || selected.kind !== "custom") return;
    if (!window.confirm(`确定删除自定义模板“${selected.name}”吗？删除后不能恢复。`)) return;
    setSaving(true);
    setFormError("");
    try {
      await api.deleteTemplate(selected.id);
      await load(DEFAULT_TEMPLATE);
    } catch (reason) {
      setFormError(reason instanceof Error ? reason.message : "删除失败");
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
            <span><LibraryBig aria-hidden="true" /> K 线模板</span>
            <h1>模板库</h1>
            <p>先看冻结四模板，也可以把一只股票的真实历史区间保存成自己的模板。</p>
          </div>
          <Link href="/market">打开行情详情<ChevronRight aria-hidden="true" /></Link>
        </header>

        <section className={styles.createCard}>
          <div className={styles.createCopy}>
            <span><Plus aria-hidden="true" /> 自定义模板</span>
            <h2>保存一段你看得懂的 K 线</h2>
            <p>输入股票和起止日期。系统保存这段窗口，之后用同样长度寻找最相似的股票。</p>
          </div>
          <form onSubmit={createTemplate}>
            <label><span>模板名称</span><input value={name} onChange={event => setName(event.target.value)} placeholder="例如：平台突破后的稳步上涨" maxLength={40} /></label>
            <label><span>股票代码</span><input value={sourceCode} onChange={event => setSourceCode(event.target.value)} placeholder="例如 000001.SZ" /></label>
            <label><span>开始日期</span><input type="date" value={startDate} onChange={event => setStartDate(event.target.value)} /></label>
            <label><span>结束日期</span><input type="date" value={endDate} onChange={event => setEndDate(event.target.value)} /></label>
            <button type="submit" disabled={saving}>{saving ? <LoaderCircle className="spin" /> : <Save />}保存并分析</button>
            {formError ? <p role="alert">{formError}</p> : null}
          </form>
        </section>

        {loading ? (
          <StateCard icon={<LoaderCircle className="spin" />} title="正在读取模板库" text="只使用本机模板与行情数据。" />
        ) : error && !templates.length ? (
          <StateCard
            icon={<TriangleAlert />}
            title="模板库暂时不可用"
            text={error}
            action={<button type="button" onClick={() => void load()}><RotateCcw />重新读取</button>}
          />
        ) : (
          <div className={styles.libraryLayout}>
            <aside className={styles.templateRail}>
              <TemplateGroup title="冻结四模板" note="定义固定，不在这里修改" items={frozen} selectedId={selectedId} onSelect={id => void loadDetail(id)} />
              <TemplateGroup title="我的自定义模板" note={custom.length ? `${custom.length} 个已保存` : "还没有保存"} items={custom} selectedId={selectedId} onSelect={id => void loadDetail(id)} empty="从上方输入股票与日期开始。" />
            </aside>

            <section className={styles.detailCard}>
              {detailLoading ? (
                <StateCard icon={<LoaderCircle className="spin" />} title="正在分析模板" text="正在读取相似股票列表。" />
              ) : selected ? (
                <>
                  <div className={styles.detailHead}>
                    <div>
                      <span>{selected.kind === "frozen" ? "冻结模板" : "自定义模板"}</span>
                      <h2>{selected.name}</h2>
                      <p>{selected.description || selected.cue || "比较价格走势本身，不引入未来收益。"}</p>
                    </div>
                    {selected.kind === "custom" ? (
                      <div className={styles.templateActions}>
                        <label><span>名称</span><input value={editingName} onChange={event => setEditingName(event.target.value)} /></label>
                        <button type="button" disabled={saving || !editingName.trim()} onClick={() => void renameSelected()}><Edit3 />重命名</button>
                        <button className={styles.deleteButton} type="button" disabled={saving} onClick={() => void deleteSelected()}><Trash2 />删除</button>
                      </div>
                    ) : null}
                  </div>

                  <div className={styles.templateFacts}>
                    <span><small>窗口长度</small><strong>{selected.window_length || selected.curve.length} 个交易日</strong></span>
                    <span><small>来源股票</small><strong>{selected.source_name || selected.source_ts_code || "冻结定义"}</strong></span>
                    <span><small>模板区间</small><strong>{selected.start_date ? `${formatDate(selected.start_date, "-")} 至 ${formatDate(selected.end_date, "-")}` : "固定历史窗口"}</strong></span>
                    <span><small>相似股票</small><strong>{total} 只</strong></span>
                  </div>

                  <section className={styles.curveCard}>
                    <div><span>模板曲线</span><h3>只比较窗口内的相对形状</h3><p>{selected.description || curveAnalysis(selected.curve)}</p><p className={styles.analysisNote}>{curveAnalysis(selected.curve)}</p></div>
                    <NormalizedCurve values={selected.curve} label={`${selected.name}模板归一化曲线`} />
                  </section>

                  <section className={styles.stockSection}>
                    <div className={styles.stockHead}><div><span>按相似度排序</span><h3>Top 股票</h3></div><small>点击后进入 K 线，并保留当前模板与股票列表。</small></div>
                    <div className={styles.stockTable}>
                      {stocks.length ? stocks.map(item => (
                        <Link key={`${selected.id}-${item.ts_code}`} href={`/market?code=${encodeURIComponent(item.code)}&template=${encodeURIComponent(selected.id)}`}>
                          <b>{item.rank}</b>
                          <span><strong>{item.name}</strong><small>{item.code} · {item.industry || "行业待补"}</small></span>
                          <em>{item.score.toFixed(3)}</em>
                          <small>{item.start_date ? `${formatDate(item.start_date)}—${formatDate(item.end_date)}` : `${selected.window_length} 日窗口`}</small>
                          <ChevronRight aria-hidden="true" />
                        </Link>
                      )) : <p>这个模板暂时没有可展示的相似股票。</p>}
                    </div>
                  </section>
                </>
              ) : <StateCard icon={<TriangleAlert />} title="请选择模板" text="从左侧选择冻结模板或自定义模板。" />}
            </section>
          </div>
        )}
      </main>
    </div>
  );
}

function TemplateGroup({
  title,
  note,
  items,
  selectedId,
  onSelect,
  empty,
}: {
  title: string;
  note: string;
  items: TemplateDefinition[];
  selectedId: string;
  onSelect: (id: string) => void;
  empty?: string;
}) {
  return (
    <section className={styles.templateGroup}>
      <div><h2>{title}</h2><span>{note}</span></div>
      {items.length ? items.map(item => (
        <button type="button" className={item.id === selectedId ? styles.active : ""} aria-pressed={item.id === selectedId} onClick={() => onSelect(item.id)} key={item.id}>
          <span><strong>{item.name}</strong><small>{item.cue || (item.kind === "custom" ? `${item.source_ts_code || "自定义"} · ${item.window_length || item.curve.length} 日` : `${item.window_length || item.curve.length} 日固定窗口`)}</small></span>
          <ChevronRight aria-hidden="true" />
        </button>
      )) : <p>{empty || "暂无模板。"}</p>}
    </section>
  );
}

function NormalizedCurve({ values, label }: { values: number[]; label: string }) {
  const width = 760;
  const height = 210;
  const padding = 18;
  if (values.length < 2) return <div className={styles.emptyCurve}>模板曲线暂不可用。</div>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = Math.max(0.0001, max - min);
  const x = (index: number) => padding + index * ((width - padding * 2) / (values.length - 1));
  const y = (value: number) => height - padding - (value - min) / spread * (height - padding * 2);
  const path = values.map((value, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(value).toFixed(1)}`).join(" ");
  return (
    <svg className={styles.curve} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
      <line x1={padding} x2={width - padding} y1={height / 2} y2={height / 2} />
      <path d={path} />
    </svg>
  );
}

function StateCard({ icon, title, text, action }: { icon: React.ReactNode; title: string; text: string; action?: React.ReactNode }) {
  return <section className={styles.stateCard}>{icon}<strong>{title}</strong><span>{text}</span>{action}</section>;
}
