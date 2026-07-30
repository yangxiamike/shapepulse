"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  Brush,
  CalendarDays,
  ChevronDown,
  CircleDot,
  Clock3,
  Crosshair,
  Fullscreen,
  Grid2X2,
  Layers3,
  LineChart,
  Menu,
  Minus,
  MousePointer2,
  MoveHorizontal,
  MoveVertical,
  PanelRightOpen,
  PanelTopClose,
  PanelTopOpen,
  Palette,
  PenLine,
  Plus,
  Ruler,
  Search,
  Settings2,
  Square,
  Spline,
  Trash2,
  Type,
  X,
  ZoomIn,
} from "lucide-react";
import { AppSidebar } from "./AppSidebar";
import { CandlestickPreview } from "./CandlestickPreview";
import {
  defaultFibonacciLevels,
  MarketChart,
  prepareChartData,
  type ChartDrawing,
  type DrawingMode,
  type FibonacciLevel,
  type MarketChartHandle,
} from "./MarketChart";
import { api, fmtAmount, fmtMarketValue, fmtNumber, formatDate } from "../lib/api";
import type { Bar, StateSnapshot, Stock, TemplateDefinition, TemplateStock } from "../lib/types";

const periods = [
  ["日K", "D"], ["周K", "W"], ["月K", "M"], ["季K", "Q"], ["年K", "Y"],
] as const;
const ranges = [["1天", "1D"], ["5天", "5D"], ["1个月", "1M"], ["3个月", "3M"], ["6个月", "6M"], ["YTD", "YTD"], ["1年", "1Y"], ["3年", "3Y"], ["5年", "5Y"], ["全部", "ALL"]] as const;
const tabs = ["自选", "详情", "模板"] as const;
type RightTab = typeof tabs[number];
type FibonacciKind = "fibonacci" | "fibonacci-extension";
type MarketOrigin = { from: string | null; industry: string | null; window: string | null };

const DEFAULT_TEMPLATE_KEY = "fresh_breakout";
const emptyState: StateSnapshot = { viewed: [], saved: [], pending: [], watchlist: [], history: { runs: [], recommendations: [] } };
const rangeLimits: Record<string, Record<string, number>> = {
  "1D": { D: 1, W: 1, M: 1, Q: 1, Y: 1 }, "5D": { D: 5, W: 2, M: 1, Q: 1, Y: 1 },
  "1M": { D: 22, W: 5, M: 1, Q: 1, Y: 1 }, "3M": { D: 66, W: 14, M: 3, Q: 1, Y: 1 },
  "6M": { D: 110, W: 27, M: 6, Q: 2, Y: 1 }, YTD: { D: 160, W: 32, M: 8, Q: 3, Y: 1 },
  "1Y": { D: 250, W: 53, M: 12, Q: 4, Y: 1 }, "3Y": { D: 750, W: 160, M: 36, Q: 12, Y: 3 },
  "5Y": { D: 1250, W: 266, M: 60, Q: 20, Y: 5 }, ALL: { D: 10000, W: 2500, M: 600, Q: 200, Y: 50 },
};

export function MarketClient() {
  const [stock, setStock] = useState<Stock | null>(null);
  const [bars, setBars] = useState<Bar[]>([]);
  const [period, setPeriod] = useState("D");
  const [range, setRange] = useState("6M");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Stock[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [activeResult, setActiveResult] = useState(0);
  const [rightTab, setRightTab] = useState<RightTab>("自选");
  const [rightOpen, setRightOpen] = useState(false);
  const [state, setState] = useState<StateSnapshot>(emptyState);
  const [watchlist, setWatchlist] = useState<Stock[]>([]);
  const [templates, setTemplates] = useState<TemplateDefinition[]>([]);
  const [template, setTemplate] = useState<TemplateDefinition | null>(null);
  const [templateLoading, setTemplateLoading] = useState(false);
  const [templateError, setTemplateError] = useState("");
  const [drawingMode, setDrawingMode] = useState<DrawingMode | null>(null);
  const [drawings, setDrawings] = useState<ChartDrawing[]>([]);
  const [selectedDrawing, setSelectedDrawing] = useState<number | null>(null);
  const [drawingColor, setDrawingColor] = useState("#2864ff");
  const [drawingLineWidth, setDrawingLineWidth] = useState(2);
  const [drawingText, setDrawingText] = useState("文本标记");
  const [fibonacciDefaults, setFibonacciDefaults] = useState<Record<FibonacciKind, FibonacciLevel[]>>({
    fibonacci: defaultFibonacciLevels("fibonacci"),
    "fibonacci-extension": defaultFibonacciLevels("fibonacci-extension"),
  });
  const [fibonacciSettings, setFibonacciSettings] = useState<{ index: number; left: number; top: number } | null>(null);
  const [customFibonacciValue, setCustomFibonacciValue] = useState("");
  const [fibonacciError, setFibonacciError] = useState("");
  const [layout, setLayout] = useState<1 | 2 | 4>(1);
  const [layoutOpen, setLayoutOpen] = useState(false);
  const [maximizedPane, setMaximizedPane] = useState<number | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [templateId, setTemplateId] = useState(DEFAULT_TEMPLATE_KEY);
  const [templatePool, setTemplatePool] = useState<TemplateStock[]>([]);
  const [poolLoading, setPoolLoading] = useState(false);
  const [crosshairEnabled, setCrosshairEnabled] = useState(true);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [rightOverlayMode, setRightOverlayMode] = useState(false);
  const [rightWidth, setRightWidth] = useState(360);
  const [headerCompact, setHeaderCompact] = useState(false);
  const [templatePendingCode, setTemplatePendingCode] = useState<string | null>(null);
  const [marketOrigin, setMarketOrigin] = useState<MarketOrigin>({ from: null, industry: null, window: null });
  const [status, setStatus] = useState("连接本地数据…");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [clock, setClock] = useState("—");
  const [perf, setPerf] = useState({ frontendMs: 0, httpMs: 0, queryMs: 0, renderMs: 0, cache: false });
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const operationStarted = useRef(0);
  const loadSequence = useRef(0);
  const barsLoadSequence = useRef(0);
  const fullHistorySequence = useRef(0);
  const fullHistoryRequest = useRef({
    key: "",
    sequence: 0,
    loading: false,
    complete: false,
  });
  const templateLoadSequence = useRef(0);
  const shellRef = useRef<HTMLDivElement>(null);
  const workspaceRef = useRef<HTMLElement>(null);
  const chartRefs = useRef<Array<MarketChartHandle | null>>([]);
  const templateCursorRef = useRef(-1);
  const templateIdRef = useRef(DEFAULT_TEMPLATE_KEY);
  const rightResizeActive = useRef(false);
  const rightResizeFrame = useRef<number | null>(null);
  const fibonacciInputRef = useRef<HTMLInputElement>(null);
  const rightCloseRef = useRef<HTMLButtonElement>(null);
  const rightOpenRef = useRef<HTMLButtonElement>(null);
  const drawerWasOpen = useRef(false);
  const marketOriginRef = useRef<MarketOrigin>({ from: null, industry: null, window: null });

  const marketPath = useCallback((code: string, activeTemplateId: string) => {
    const params = new URLSearchParams({ code, template: activeTemplateId });
    const origin = marketOriginRef.current;
    if (origin.from) params.set("from", origin.from);
    if (origin.industry) params.set("industry", origin.industry);
    if (origin.window) params.set("window", origin.window);
    return `/market?${params.toString()}`;
  }, []);

  const refreshWatchlist = useCallback(async (snapshot: StateSnapshot) => {
    const items = await Promise.all(snapshot.watchlist.map(item => api.stock(item.code).then(result => result.item).catch(() => ({ code: item.code, ts_code: item.ts_code, name: item.name || item.code, close: 0, pct_chg: 0 } as Stock))));
    setWatchlist(items);
  }, []);

  const loadTemplatePool = useCallback(async (id: string) => {
    const sequence = ++templateLoadSequence.current;
    setPoolLoading(true);
    setTemplateLoading(true);
    setTemplateError("");
    const definitionTask = api.template(id)
      .then(definition => {
        if (sequence === templateLoadSequence.current && templateIdRef.current === id) {
          setTemplate(definition);
        }
      })
      .catch(e => {
        if (sequence === templateLoadSequence.current && templateIdRef.current === id) {
          setTemplateError(e instanceof Error ? e.message : "模板 K 线加载失败");
          setTemplate(null);
        }
      })
      .finally(() => {
        if (sequence === templateLoadSequence.current && templateIdRef.current === id) {
          setTemplateLoading(false);
        }
      });
    const rankingTask = api.templateStocks(id, 100)
      .then(result => {
        if (sequence === templateLoadSequence.current && templateIdRef.current === id) {
          setTemplatePool(result.items);
        }
      })
      .catch(e => {
        if (sequence === templateLoadSequence.current && templateIdRef.current === id) {
          setTemplateError(e instanceof Error ? e.message : "模板 Top100 加载失败");
          setTemplatePool([]);
        }
      })
      .finally(() => {
        if (sequence === templateLoadSequence.current && templateIdRef.current === id) {
          setPoolLoading(false);
        }
      });
    await Promise.allSettled([definitionTask, rankingTask]);
  }, []);

  const loadTemplates = useCallback(async (requestedId?: string | null) => {
    setTemplateLoading(true);
    setTemplateError("");
    try {
      const items = await api.templates();
      setTemplates(items);
      const selected = items.find(item => item.id === requestedId || item.key === requestedId)
        || items.find(item => item.key === DEFAULT_TEMPLATE_KEY)
        || items[0];
      if (!selected) throw new Error("模板库当前为空");
      const requestedIsValid = Boolean(requestedId && items.some(item => item.id === requestedId || item.key === requestedId));
      if (requestedIsValid) {
        setRightTab("模板");
      }
      templateIdRef.current = selected.id;
      setTemplateId(selected.id);
      await loadTemplatePool(selected.id);
    } catch (e) {
      setTemplateError(e instanceof Error ? e.message : "模板库加载失败");
    } finally {
      setTemplateLoading(false);
    }
  }, [loadTemplatePool]);

  const loadCompleteHistory = useCallback(async (
    code: string,
    activePeriod: string,
    sequence: number,
  ) => {
    const key = `${code}:${activePeriod}`;
    const current = fullHistoryRequest.current;
    if (
      current.key === key
      && current.sequence === sequence
      && (current.loading || current.complete)
    ) return;
    fullHistoryRequest.current = { key, sequence, loading: true, complete: false };
    try {
      const history = await api.barsComplete(code, activePeriod);
      const latest = fullHistoryRequest.current;
      if (
        latest.key !== key
        || latest.sequence !== sequence
        || fullHistorySequence.current !== sequence
      ) return;
      fullHistoryRequest.current = { key, sequence, loading: false, complete: true };
      setBars(history.items);
      setStatus(currentStatus =>
        `${currentStatus.split(" · 完整历史")[0]} · 完整历史 ${history.items.length} 根`
      );
    } catch (e) {
      const latest = fullHistoryRequest.current;
      if (latest.key === key && latest.sequence === sequence) {
        fullHistoryRequest.current = { key, sequence, loading: false, complete: false };
        setStatus(e instanceof Error ? `完整历史补载失败：${e.message}` : "完整历史补载失败");
      }
    }
  }, []);

  const requestOlderHistory = useCallback(() => {
    if (!stock) return;
    void loadCompleteHistory(stock.code, period, fullHistorySequence.current);
  }, [loadCompleteHistory, period, stock]);

  const loadStock = useCallback(async (code: string, nextPeriod = "D", nextRange = "6M", preserveContext = false) => {
    const sequence = ++loadSequence.current;
    ++barsLoadSequence.current;
    const historySequence = ++fullHistorySequence.current;
    fullHistoryRequest.current = {
      key: `${code}:${nextPeriod}`,
      sequence: historySequence,
      loading: false,
      complete: false,
    };
    const started = performance.now();
    operationStarted.current = started;
    setLoading(true); setError(""); setStatus("正在读取本地行情…");
    try {
      const [detailResult, history] = await Promise.all([
        api.stock(code),
        nextRange === "ALL"
          ? api.barsComplete(code, nextPeriod)
          : api.bars(code, nextPeriod, nextRange),
      ]);
      if (sequence !== loadSequence.current) return;
      const detail = detailResult.item;
      setStock(detail); setBars(history.items); setPeriod(nextPeriod); setRange(nextRange);
      setTemplatePendingCode(null);
      setPerf(current => ({ ...current, frontendMs: performance.now() - started, httpMs: Math.max(detailResult.httpMs, history.http_ms || 0), queryMs: history.timings.total_ms || 0, cache: detailResult.cacheHit && Boolean(history.client_cache_hit) }));
      const visibleBars = nextRange === "ALL"
        ? history.items.length
        : Math.min(history.items.length, rangeLimits[nextRange]?.[nextPeriod] || history.items.length);
      setStatus(`${history.client_cache_hit ? "前端缓存" : history.cache_hit ? "后端缓存" : "本地快照"} · ${formatDate(history.as_of.daily)} · ${visibleBars} 根可见 / ${history.items.length} 根已读`);
      setSearchOpen(false); setQuery(""); if (!preserveContext) setRightOpen(false);
      window.history.replaceState(null, "", marketPath(detail.code, templateIdRef.current));
      void api.updateState(detail.code, "viewed").catch(() => undefined);
      if (nextRange === "ALL") {
        fullHistoryRequest.current = {
          key: `${code}:${nextPeriod}`,
          sequence: historySequence,
          loading: false,
          complete: true,
        };
      } else {
        void loadCompleteHistory(code, nextPeriod, historySequence);
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : "本地行情加载失败";
      setError(message); setStatus(message);
      if (sequence === loadSequence.current) setTemplatePendingCode(null);
    } finally { if (sequence === loadSequence.current) setLoading(false); }
  }, [loadCompleteHistory, marketPath]);

  const chooseTemplateStock = useCallback((code: string) => {
    const index = templatePool.findIndex(item => item.code === code);
    if (index >= 0) templateCursorRef.current = index;
    setTemplatePendingCode(code);
    void loadStock(code, "D", "6M", true);
  }, [loadStock, templatePool]);

  const stepTemplateStock = useCallback((direction: -1 | 1) => {
    if (!templatePool.length) return false;
    let index = templateCursorRef.current;
    if (index < 0 || index >= templatePool.length) {
      index = templatePool.findIndex(item => item.code === (templatePendingCode || stock?.code));
    }
    if (index < 0) index = direction > 0 ? -1 : templatePool.length;
    const nextIndex = Math.max(0, Math.min(templatePool.length - 1, index + direction));
    if (nextIndex === index) {
      setStatus(direction > 0 ? "已经是 Top100 最后一只" : "已经是 Top100 第一只");
      return false;
    }
    templateCursorRef.current = nextIndex;
    const code = templatePool[nextIndex].code;
    setTemplatePendingCode(code);
    void loadStock(code, "D", "6M", true);
    return true;
  }, [loadStock, stock?.code, templatePendingCode, templatePool]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code") || "000001";
    const requestedTemplate = params.get("template");
    const origin = {
      from: params.get("from"),
      industry: params.get("industry"),
      window: params.get("window"),
    };
    marketOriginRef.current = origin;
    const updateClock = () => setClock(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
    const boot = window.setTimeout(() => {
      setMarketOrigin(origin);
      void loadStock(code, "D", "6M", Boolean(requestedTemplate));
      if (requestedTemplate) void loadTemplates(requestedTemplate);
      void api.state().then(snapshot => { setState(snapshot); void refreshWatchlist(snapshot); }).catch(() => undefined);
      updateClock();
    }, 0);
    const timer = window.setInterval(updateClock, 1000);
    return () => { window.clearTimeout(boot); window.clearInterval(timer); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (rightTab === "模板" && !templates.length && !templateLoading) void loadTemplates(templateId);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadTemplates, rightTab, templateId, templateLoading, templates.length]);

  useEffect(() => {
    const index = templatePool.findIndex(item => item.code === (templatePendingCode || stock?.code));
    if (index >= 0) templateCursorRef.current = index;
  }, [stock?.code, templatePendingCode, templatePool]);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 1100px)");
    const update = () => setRightOverlayMode(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (!rightOpen) {
      if (drawerWasOpen.current) {
        drawerWasOpen.current = false;
        const frame = window.requestAnimationFrame(() => rightOpenRef.current?.focus());
        return () => window.cancelAnimationFrame(frame);
      }
      return;
    }
    drawerWasOpen.current = true;
    const frame = window.requestAnimationFrame(() => rightCloseRef.current?.focus());
    const closeDrawer = (event: KeyboardEvent) => {
      if (event.key === "Escape") setRightOpen(false);
    };
    window.addEventListener("keydown", closeDrawer);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", closeDrawer);
    };
  }, [rightOpen]);

  useEffect(() => {
    const onFullscreen = () => {
      setFullscreen(document.fullscreenElement === workspaceRef.current);
      window.setTimeout(() => chartRefs.current.forEach(chart => chart?.resize()), 40);
    };
    document.addEventListener("fullscreenchange", onFullscreen);
    return () => document.removeEventListener("fullscreenchange", onFullscreen);
  }, []);

  useEffect(() => () => {
    if (rightResizeFrame.current != null) cancelAnimationFrame(rightResizeFrame.current);
  }, []);

  useEffect(() => {
    if (!fibonacciSettings) return;
    const frame = requestAnimationFrame(() => fibonacciInputRef.current?.focus());
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFibonacciSettings(null);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [fibonacciSettings]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (rightTab !== "模板" || (event.key !== "ArrowUp" && event.key !== "ArrowDown")) return;
      const target = event.target as HTMLElement | null;
      if (target?.matches("input, select, textarea, [contenteditable=true]")) return;
      if (stepTemplateStock(event.key === "ArrowDown" ? 1 : -1)) event.preventDefault();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [rightTab, stepTemplateStock]);

  const changeBars = useCallback(async (nextPeriod: string, nextRange = range) => {
    if (!stock || (nextPeriod === period && nextRange === range)) return;
    const sequence = ++barsLoadSequence.current;
    const historySequence = ++fullHistorySequence.current;
    fullHistoryRequest.current = {
      key: `${stock.code}:${nextPeriod}`,
      sequence: historySequence,
      loading: false,
      complete: false,
    };
    const previousPeriod = period;
    const previousRange = range;
    const started = performance.now();
    operationStarted.current = started;
    setPeriod(nextPeriod); setRange(nextRange);
    setLoading(true); setError(""); setStatus("切换 K 线周期…");
    try {
      const history = nextRange === "ALL"
        ? await api.barsComplete(stock.code, nextPeriod)
        : await api.bars(stock.code, nextPeriod, nextRange);
      if (sequence !== barsLoadSequence.current) return;
      setBars(history.items);
      setPerf(current => ({ ...current, frontendMs: performance.now() - started, httpMs: history.http_ms || 0, queryMs: history.timings.total_ms || 0, cache: Boolean(history.client_cache_hit || history.cache_hit) }));
      const visibleBars = nextRange === "ALL"
        ? history.items.length
        : Math.min(history.items.length, rangeLimits[nextRange]?.[nextPeriod] || history.items.length);
      setStatus(`${history.client_cache_hit ? "前端缓存" : history.cache_hit ? "后端缓存" : "本地聚合"} · ${periodLabel(nextPeriod)} · ${visibleBars} 根可见 / ${history.items.length} 根已读`);
      if (nextRange === "ALL") {
        fullHistoryRequest.current = {
          key: `${stock.code}:${nextPeriod}`,
          sequence: historySequence,
          loading: false,
          complete: true,
        };
      } else {
        void loadCompleteHistory(stock.code, nextPeriod, historySequence);
      }
    } catch (e) {
      if (sequence !== barsLoadSequence.current) return;
      const message = e instanceof Error ? e.message : "周期切换失败";
      setPeriod(previousPeriod); setRange(previousRange); setError(message); setStatus(message);
    } finally {
      if (sequence === barsLoadSequence.current) setLoading(false);
    }
  }, [loadCompleteHistory, period, range, stock]);

  function onSearch(value: string) {
    setQuery(value); setSearchOpen(Boolean(value.trim())); setActiveResult(0);
    if (searchTimer.current) clearTimeout(searchTimer.current);
    if (!value.trim()) { setResults([]); return; }
    searchTimer.current = setTimeout(() => void api.search(value).then(result => setResults(result.items.slice(0, 8))).catch(() => setResults([])), 100);
  }

  function searchKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") { e.preventDefault(); setActiveResult(index => Math.min(index + 1, results.length - 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setActiveResult(index => Math.max(index - 1, 0)); }
    if (e.key === "Enter" && results[activeResult]) { e.preventDefault(); void loadStock(results[activeResult].code, "D", "6M"); }
    if (e.key === "Escape") setSearchOpen(false);
  }

  async function toggleWatchlist() {
    if (!stock) return;
    const exists = state.watchlist.some(item => item.code === stock.code);
    try {
      const next = await api.updateState(stock.code, "watchlist", !exists);
      setState(next); await refreshWatchlist(next);
      setStatus(`${stock.name} 已${exists ? "移出" : "加入"}自选`);
    } catch (e) { setError(e instanceof Error ? e.message : "自选保存失败"); }
  }

  function zoomIn() {
    const order = ["ALL", "5Y", "3Y", "1Y", "YTD", "6M", "3M", "1M", "5D", "1D"];
    const index = order.indexOf(range);
    const next = order[Math.min(order.length - 1, index + 1)];
    void changeBars(period, next);
  }

  function changeLayout(next: 1 | 2 | 4) {
    setLayout(next); setMaximizedPane(null); setLayoutOpen(false);
    window.setTimeout(() => chartRefs.current.forEach(chart => chart?.resize()), 40);
  }

  async function toggleFullscreen() {
    if (!workspaceRef.current) return;
    if (document.fullscreenElement) await document.exitFullscreen();
    else await workspaceRef.current.requestFullscreen();
  }

  function selectDrawing(index: number | null) {
    setSelectedDrawing(index);
    if (fibonacciSettings && fibonacciSettings.index !== index) setFibonacciSettings(null);
    if (index == null) return;
    const drawing = drawings[index];
    if (!drawing) return;
    setDrawingColor(drawing.color || "#2864ff");
    setDrawingLineWidth(drawing.lineWidth || 2);
    if (drawing.kind === "text" && drawing.text) setDrawingText(drawing.text);
  }

  function changeTemplate(nextId: string) {
    templateIdRef.current = nextId;
    templateCursorRef.current = -1;
    setTemplatePendingCode(null);
    setTemplateId(nextId);
    if (stock) window.history.replaceState(null, "", marketPath(stock.code, nextId));
    void loadTemplatePool(nextId);
  }

  function applyDrawingStyle(change: Pick<ChartDrawing, "color" | "lineWidth" | "text">) {
    if (selectedDrawing == null) return;
    setDrawings(items => items.map((item, index) => index === selectedDrawing ? { ...item, ...change } : item));
  }

  function changeDrawingColor(color: string) {
    setDrawingColor(color);
    applyDrawingStyle({ color });
  }

  function changeDrawingLineWidth(lineWidth: number) {
    setDrawingLineWidth(lineWidth);
    applyDrawingStyle({ lineWidth });
  }

  function changeDrawingText(text: string) {
    setDrawingText(text);
    if (selectedDrawing != null && drawings[selectedDrawing]?.kind === "text") applyDrawingStyle({ text });
  }

  function completeDrawing(drawing: ChartDrawing) {
    setSelectedDrawing(drawings.length);
    setDrawings(items => [...items, drawing]);
    setDrawingMode("select");
  }

  function deleteDrawing(index: number) {
    setDrawings(items => items.filter((_item, itemIndex) => itemIndex !== index));
    setSelectedDrawing(null);
    setFibonacciSettings(null);
  }

  function openFibonacciSettings(index: number, point: { clientX: number; clientY: number }) {
    const drawing = drawings[index];
    if (drawing?.kind !== "fibonacci" && drawing?.kind !== "fibonacci-extension") return;
    setSelectedDrawing(index);
    setCustomFibonacciValue("");
    setFibonacciError("");
    setFibonacciSettings({
      index,
      left: Math.max(12, Math.min(point.clientX + 12, window.innerWidth - 352)),
      top: Math.max(12, Math.min(point.clientY + 12, window.innerHeight - 520)),
    });
  }

  function currentFibonacciLevels() {
    if (!fibonacciSettings) return [];
    const drawing = drawings[fibonacciSettings.index];
    if (drawing?.kind !== "fibonacci" && drawing?.kind !== "fibonacci-extension") return [];
    return drawing.fibonacciLevels?.length
      ? drawing.fibonacciLevels
      : fibonacciDefaults[drawing.kind];
  }

  function updateFibonacciLevels(next: FibonacciLevel[]) {
    if (!fibonacciSettings) return;
    const drawing = drawings[fibonacciSettings.index];
    if (drawing?.kind !== "fibonacci" && drawing?.kind !== "fibonacci-extension") return;
    const normalized = next.map(level => ({ ...level }));
    setDrawings(items => items.map((item, index) => index === fibonacciSettings.index ? { ...item, fibonacciLevels: normalized } : item));
    setFibonacciDefaults(current => ({ ...current, [drawing.kind]: normalized }));
  }

  function addCustomFibonacciLevel() {
    const raw = customFibonacciValue.trim().replace(/%$/, "");
    const value = Number(raw);
    const levels = currentFibonacciLevels();
    if (!raw || !Number.isFinite(value) || value < 0 || value > 10) {
      setFibonacciError("请输入 0 到 10 之间的比例，例如 1.414");
      return;
    }
    if (levels.some(level => Math.abs(level.value - value) < 0.000001)) {
      setFibonacciError("这个比例已经存在");
      return;
    }
    updateFibonacciLevels([...levels, {
      id: `custom-${Date.now()}-${value}`,
      value,
      enabled: true,
      custom: true,
    }].sort((left, right) => left.value - right.value));
    setCustomFibonacciValue("");
    setFibonacciError("");
    requestAnimationFrame(() => fibonacciInputRef.current?.focus());
  }

  function rightWidthLimit() {
    if (typeof window === "undefined") return 560;
    const sidebar = window.innerWidth <= 1320 ? 78 : 136;
    return Math.max(300, Math.min(560, window.innerWidth - sidebar - 620));
  }

  function resizeRightbarAt(clientX: number) {
    const next = Math.max(300, Math.min(rightWidthLimit(), window.innerWidth - clientX));
    if (rightResizeFrame.current != null) cancelAnimationFrame(rightResizeFrame.current);
    rightResizeFrame.current = requestAnimationFrame(() => {
      rightResizeFrame.current = null;
      setRightWidth(next);
    });
  }

  function startRightResize(event: React.PointerEvent<HTMLDivElement>) {
    rightResizeActive.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    resizeRightbarAt(event.clientX);
  }

  function moveRightResize(event: React.PointerEvent<HTMLDivElement>) {
    if (rightResizeActive.current) resizeRightbarAt(event.clientX);
  }

  function finishRightResize(event: React.PointerEvent<HTMLDivElement>) {
    rightResizeActive.current = false;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }

  function rightResizeKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight" && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    if (event.key === "Home") setRightWidth(300);
    else if (event.key === "End") setRightWidth(rightWidthLimit());
    else setRightWidth(current => Math.max(300, Math.min(rightWidthLimit(), current + (event.key === "ArrowLeft" ? 24 : -24))));
  }

  function toggleRightbar() {
    if (window.matchMedia("(max-width: 1100px)").matches) setRightOpen(value => !value);
    else setRightCollapsed(value => !value);
    window.setTimeout(() => chartRefs.current.forEach(chart => chart?.resize()), 30);
  }

  const onRendered = useCallback((durationMs: number) => {
    setPerf(current => ({ ...current, renderMs: durationMs, frontendMs: operationStarted.current ? performance.now() - operationStarted.current : current.frontendMs }));
  }, []);

  const latest = bars.at(-1);
  const maLegend = useMemo(() => latest ? [latest.ma5, latest.ma10, latest.ma20] : [], [latest]);
  const watched = Boolean(stock && state.watchlist.some(item => item.code === stock.code));
  const visibleCount = range === "ALL"
    ? Math.max(1, bars.length)
    : rangeLimits[range]?.[period] || 110;
  const visibleBars = bars.slice(-visibleCount);
  const preparedChartData = useMemo(() => prepareChartData(bars), [bars]);
  const paneIndexes = maximizedPane == null ? Array.from({ length: layout }, (_value, index) => index) : [maximizedPane];
  const activeTemplateStock = templatePool.find(item => item.code === (templatePendingCode || stock?.code)) || null;
  const templateReturnHref = marketOrigin.from === "breadth"
    ? `/template-breadth-v3?template=${encodeURIComponent(templateId)}${marketOrigin.industry ? `&industry=${encodeURIComponent(marketOrigin.industry)}` : ""}${marketOrigin.window ? `&window=${encodeURIComponent(marketOrigin.window)}` : ""}`
    : `/templates?template=${encodeURIComponent(templateId)}`;
  const templateReturnLabel = marketOrigin.from === "breadth" ? "回到行业宽度" : "回到模板库查看完整列表";

  return <div
    ref={shellRef}
    className={`app-shell market-shell ${rightCollapsed ? "right-collapsed" : ""} ${headerCompact ? "header-compact" : "header-expanded"}`}
    style={{ "--rightbar-width": `${rightWidth}px` } as React.CSSProperties}
    data-rightbar-state={rightCollapsed ? "collapsed" : "expanded"}
  >
    <AppSidebar active="market" />
    <main className="market-main">
      <header className="market-topbar">
        <div className="market-search-wrap">
          <Search className="search-left" />
          <input value={query} onFocus={() => query && setSearchOpen(true)} onChange={e => onSearch(e.target.value)} onKeyDown={searchKeyDown} placeholder="搜索股票名称 / 代码 / 拼音首字母" aria-label="搜索股票" />
          {query ? <button onClick={() => onSearch("")} aria-label="清空搜索"><X /></button> : <Search className="search-right" />}
          {searchOpen && <div className="search-results" role="listbox">{results.length ? results.map((item, index) => <button role="option" aria-selected={index === activeResult} key={item.code} className={index === activeResult ? "active" : ""} onMouseEnter={() => setActiveResult(index)} onClick={() => void loadStock(item.code, "D", "6M")}><span>{item.code}</span><b>{item.name}</b><em>{item.initials}</em></button>) : <p>没有匹配的本地股票</p>}</div>}
        </div>
        <div className="layout-tools"><button className="header-density-toggle" onClick={() => { setHeaderCompact(value => !value); window.setTimeout(() => chartRefs.current.forEach(chart => chart?.resize()), 40); }} aria-pressed={headerCompact} aria-label={headerCompact ? "展开行情页顶部" : "收起行情页顶部"} title={headerCompact ? "展开股票摘要与顶部工具" : "一键收起顶部，增加 K 线高度"}>{headerCompact ? <PanelTopOpen /> : <PanelTopClose />}<span>{headerCompact ? "展开顶部" : "收起顶部"}</span></button><div className="layout-picker"><button onClick={() => setLayoutOpen(value => !value)} aria-expanded={layoutOpen}><Grid2X2 /><span>{layout} 图布局</span><ChevronDown /></button>{layoutOpen && <div className="layout-menu">{([1, 2, 4] as const).map(value => <button key={value} className={layout === value ? "active" : ""} onClick={() => changeLayout(value)}>{value} 图</button>)}</div>}</div>{(layout !== 1 || maximizedPane != null) && <button onClick={() => changeLayout(1)} title="恢复单图" aria-label="恢复单图"><Grid2X2 /><span>{maximizedPane == null ? `布局 ${layout}` : "单图放大"}</span></button>}<button onClick={() => chartRefs.current.forEach(chart => chart?.fitContent())} title="适配当前已读范围" aria-label="适配图表"><Settings2 /></button><button ref={rightOpenRef} className="mobile-panel-button" onClick={() => setRightOpen(true)} aria-label="打开右侧面板" aria-expanded={rightOpen}><PanelRightOpen /></button><button onClick={toggleRightbar} aria-label="折叠或展开右侧栏" aria-expanded={!rightCollapsed} title={rightCollapsed ? "展开右侧栏" : "折叠右侧栏"}><Menu /></button></div>
      </header>

      <section className="quote-summary">
        {stock ? <>
          <div className="quote-main"><div className="quote-title"><h1>{stock.name}</h1><span>{stock.code}</span><em>{stock.market || "A股"}</em><em>{stock.industry || "本地数据"}</em>{stock.is_st && <em className="st-badge">ST</em>}</div><div className={`quote-price ${stock.pct_chg >= 0 ? "up" : "down"}`}><b>{fmtNumber(stock.close)}</b><span>CNY</span><p>{signed(stock.change)}　{signed(stock.pct_chg)}%</p></div></div>
          <div className="quote-facts"><QuoteFact label="今开" value={fmtNumber(stock.open)} /><QuoteFact label="最高" value={fmtNumber(stock.high)} /><QuoteFact label="最低" value={fmtNumber(stock.low)} /><QuoteFact label="昨收" value={fmtNumber(stock.pre_close)} /><QuoteFact label="成交额" value={fmtAmount(stock.amount)} /><QuoteFact label="成交量" value={stock.volume == null ? "—" : `${fmtNumber(stock.volume / 10000)}万手`} /><QuoteFact label="换手率" value={stock.turnover_rate == null ? "—" : `${fmtNumber(stock.turnover_rate)}%`} /><QuoteFact label="市值" value={fmtMarketValue(stock.total_mv)} /></div>
          <div className="quote-dates"><span>行情 {formatDate(stock.as_of?.quote)}</span><span>估值 {formatDate(stock.as_of?.valuation)}</span><span>ST {formatDate(stock.as_of?.st)}</span><span>复权 {formatDate(stock.as_of?.adj_factor)}</span></div>
        </> : <div className="quote-loading">{status}</div>}
      </section>

      {stock?.warnings?.length ? <div className="market-warning">{stock.warnings.join(" · ")}</div> : null}

      <section ref={workspaceRef} className="chart-workspace" data-layout={layout} data-fullscreen={fullscreen}>
        <div className="chart-toolbar">
          <div className="period-tabs">{periods.map(([label, value]) => <button key={label} className={period === value ? "active" : ""} onClick={() => void changeBars(value)}>{label}</button>)}</div>
          <div className="chart-actions"><span className="local-period-note">本地真实前复权 K 线</span><button onClick={() => void toggleFullscreen()} aria-label={fullscreen ? "退出全屏" : "进入全屏"} title={fullscreen ? "退出全屏" : "进入全屏"}><Fullscreen />{fullscreen ? "退出" : "全屏"}</button></div>
          <div className="ma-legend">
            <span className="ma5">MA5　{fmtNumber(maLegend[0])}</span><span className="ma10">MA10　{fmtNumber(maLegend[1])}</span><span className="ma20">MA20　{fmtNumber(maLegend[2])}</span>
            <div className="drawing-style-controls" aria-label="画线样式">
              <label className="drawing-color-control" title="画线颜色"><Palette /><input type="color" value={drawingColor} onChange={event => changeDrawingColor(event.target.value)} aria-label="画线颜色" /></label>
              <label><span>线宽</span><select value={drawingLineWidth} onChange={event => changeDrawingLineWidth(Number(event.target.value))} aria-label="画线线宽">{[1, 2, 3, 4, 5].map(value => <option value={value} key={value}>{value}px</option>)}</select></label>
              {(drawingMode === "text" || (selectedDrawing != null && drawings[selectedDrawing]?.kind === "text")) && <label className="drawing-text-control"><span>文本</span><input value={drawingText} maxLength={40} onChange={event => changeDrawingText(event.target.value)} aria-label="标注文本" /></label>}
            </div>
            <span className="perf-chip" data-testid="market-performance">总 {perf.frontendMs.toFixed(0)}ms · HTTP {perf.httpMs.toFixed(0)}ms · 查询 {perf.queryMs.toFixed(0)}ms · 绘制 {perf.renderMs.toFixed(0)}ms{perf.cache ? " · 缓存" : ""}</span>
          </div>
        </div>
        <div className="drawing-toolbar" aria-label="绘图工具">
          <div className="drawing-tool-group" role="group" aria-label="选择工具">
            <DrawingButton label="选择/调整" active={drawingMode === "select"} onClick={() => setDrawingMode("select")}><MousePointer2 /></DrawingButton>
            <DrawingButton label={`十字光标${crosshairEnabled ? "已开启" : "已关闭"}`} active={crosshairEnabled} onClick={() => setCrosshairEnabled(value => !value)}><Crosshair /></DrawingButton>
          </div>
          <div className="drawing-tool-group" role="group" aria-label="线工具">
            <DrawingButton label="趋势线" hint="趋势线：穿过两个锚点，并向两端延伸" active={drawingMode === "trend"} onClick={() => setDrawingMode("trend")}><PenLine /></DrawingButton>
            <DrawingButton label="线段" hint="线段：只连接两个锚点" active={drawingMode === "segment"} onClick={() => setDrawingMode("segment")}><Minus /></DrawingButton>
            <DrawingButton label="射线" hint="射线：从第一点穿过第二点，向前延伸" active={drawingMode === "ray"} onClick={() => setDrawingMode("ray")}><ArrowUpRight /></DrawingButton>
            <DrawingButton label="水平线" active={drawingMode === "horizontal"} onClick={() => setDrawingMode("horizontal")}><MoveHorizontal /></DrawingButton>
            <DrawingButton label="垂直线" active={drawingMode === "vertical"} onClick={() => setDrawingMode("vertical")}><MoveVertical /></DrawingButton>
          </div>
          <div className="drawing-tool-group" role="group" aria-label="斐波那契工具">
            <DrawingButton label="斐波那契回撤" active={drawingMode === "fibonacci"} onClick={() => setDrawingMode("fibonacci")}><Layers3 /></DrawingButton>
            <DrawingButton label="斐波那契扩展" active={drawingMode === "fibonacci-extension"} onClick={() => setDrawingMode("fibonacci-extension")}><LineChart /></DrawingButton>
          </div>
          <div className="drawing-tool-group" role="group" aria-label="曲线和自由绘制">
            <DrawingButton label="矩形" hint="矩形：两次点击确定对角点" active={drawingMode === "rectangle"} onClick={() => setDrawingMode("rectangle")}><Square /></DrawingButton>
            <DrawingButton label="曲线" active={drawingMode === "curve"} onClick={() => setDrawingMode("curve")}><Spline /></DrawingButton>
            <DrawingButton label="自由绘制" active={drawingMode === "freehand"} onClick={() => setDrawingMode("freehand")}><Brush /></DrawingButton>
          </div>
          <div className="drawing-tool-group" role="group" aria-label="文本和测量">
            <DrawingButton label="文本" active={drawingMode === "text"} onClick={() => setDrawingMode("text")}><Type /></DrawingButton>
            <DrawingButton label="测量" active={drawingMode === "measure"} onClick={() => setDrawingMode("measure")}><Ruler /></DrawingButton>
          </div>
          <div className="drawing-tool-group drawing-tool-actions" role="group" aria-label="绘图操作">
            <DrawingButton label="放大图表" active={false} onClick={zoomIn}><ZoomIn /></DrawingButton>
            {selectedDrawing != null && <DrawingButton label="删除所选" active onClick={() => deleteDrawing(selectedDrawing)}><Trash2 /></DrawingButton>}
            {drawings.length > 0 && <DrawingButton label="清除画线（全部）" active onClick={() => { setDrawings([]); setSelectedDrawing(null); setDrawingMode(null); }}><Trash2 /></DrawingButton>}
          </div>
        </div>
        <div className={`chart-stage chart-grid layout-${paneIndexes.length}`}>{error && !bars.length ? <div className="chart-error"><p>{error}</p><button onClick={() => stock && void loadStock(stock.code, period, range)}>重试</button></div> : paneIndexes.map(index => <div className="chart-pane" key={index} data-pane={index}><button className="pane-maximize" onClick={() => { setMaximizedPane(current => current === index ? null : index); window.setTimeout(() => chartRefs.current.forEach(chart => chart?.resize()), 40); }} aria-label={maximizedPane === index ? "退出单图放大" : `放大图表 ${index + 1}`}>{maximizedPane === index ? "恢复布局" : `图 ${index + 1} · 放大`}</button><MarketChart key={`${stock?.code || "none"}-${period}-${range}-${index}`} ref={handle => { chartRefs.current[index] = handle; }} bars={bars} preparedData={preparedChartData} visibleCount={visibleCount} rightPaddingBars={10} onNeedMoreHistory={requestOlderHistory} enablePriceScaleMenu onResetDefault={() => void changeBars("D", "6M")} drawingMode={drawingMode} crosshairEnabled={crosshairEnabled} drawingColor={drawingColor} drawingLineWidth={drawingLineWidth} drawingText={drawingText} fibonacciLevels={drawingMode === "fibonacci-extension" ? fibonacciDefaults["fibonacci-extension"] : fibonacciDefaults.fibonacci} drawings={drawings} selectedDrawingIndex={selectedDrawing} onDrawingSelect={selectDrawing} onDrawingsChange={setDrawings} onDrawingDoubleClick={openFibonacciSettings} onRendered={onRendered} onDrawComplete={completeDrawing} /></div>)}{loading && <div className="chart-loading">正在加载本地行情…</div>}</div>
        <div className="range-toolbar">{ranges.map(([label, value]) => <button className={range === value ? "active" : ""} key={value} onClick={() => void changeBars(period, value)}>{label}</button>)}<b>{visibleBars[0]?.time || "—"} 至 {visibleBars.at(-1)?.time || "—"}　<CalendarDays /></b></div>
      </section>
    </main>

    {rightOpen && <button className="rightbar-backdrop" onClick={() => setRightOpen(false)} aria-label="关闭右侧面板" />}
    {!rightCollapsed && <div
      className="market-right-resizer"
      data-testid="market-right-resizer"
      role="separator"
      aria-label="调整主图与右侧栏宽度"
      aria-orientation="vertical"
      aria-valuemin={300}
      aria-valuemax={560}
      aria-valuenow={Math.round(rightWidth)}
      tabIndex={0}
      onKeyDown={rightResizeKeyDown}
      onPointerDown={startRightResize}
      onPointerMove={moveRightResize}
      onPointerUp={finishRightResize}
      onPointerCancel={finishRightResize}
    />}
    <aside
      className={`market-rightbar ${rightOpen ? "open" : ""}`}
      aria-hidden={rightCollapsed || (rightOverlayMode && !rightOpen)}
      inert={rightCollapsed || (rightOverlayMode && !rightOpen)}
    >
      <div className="rightbar-mobile-head"><b>股票面板</b><button ref={rightCloseRef} onClick={() => setRightOpen(false)} aria-label="关闭"><X /></button></div>
      <div className="right-tabs">{tabs.map(tab => <button className={rightTab === tab ? "active" : ""} onClick={() => setRightTab(tab)} key={tab}>{tab}</button>)}</div>
      {rightTab === "自选" ? <>
        <div className="watch-header"><span>名称/代码</span><span>最新价</span><span>涨跌幅</span></div>
        <div className="watch-list">{watchlist.length ? watchlist.map(item => <button key={item.code} className={item.code === stock?.code ? "active" : ""} onClick={() => void loadStock(item.code, "D", "6M")}><span><b>{item.name}</b><em>{item.code}</em></span><strong>{fmtNumber(item.close)}</strong><i className={item.pct_chg >= 0 ? "up" : "down"}>{signed(item.pct_chg)}%</i></button>) : <PanelEmpty title="暂无自选" text="添加后会保存在本项目的本地数据库中。" />}</div>
        <button className={`add-watch ${watched ? "remove" : ""}`} onClick={() => void toggleWatchlist()} disabled={!stock}>{watched ? <X /> : <Plus />}{watched ? "移出自选" : "添加自选"}</button>
      </> : rightTab === "详情" ? <DetailPanel stock={stock} /> : <TemplateWorkspace activeCode={templatePendingCode || stock?.code || null} templateId={templateId} templates={templates} pool={templatePool} poolLoading={poolLoading} onTemplate={changeTemplate} onChoose={chooseTemplateStock}><TemplateComparisonPanel key={`${templateId}:${templatePendingCode || stock?.code || "none"}:${activeTemplateStock?.ts_code || "pending"}`} stock={stock} template={template} candidate={activeTemplateStock} loading={templateLoading} error={templateError} onRetry={() => void loadTemplates(templateId)} returnHref={templateReturnHref} returnLabel={templateReturnLabel} /></TemplateWorkspace>}
    </aside>

    <footer className="market-statusbar"><span><i className={stock ? "connected" : ""} />{stock ? "已连接" : "未连接"}</span><span><Clock3 />{clock}</span><span className="status-center">本地数据　{status}</span><span><CircleDot />zer0share 日线快照</span><span>CN</span></footer>
    {fibonacciSettings && <div className="fibonacci-settings-layer" onMouseDown={event => {
      if (event.target === event.currentTarget) setFibonacciSettings(null);
    }}>
      <section
        className="fibonacci-settings"
        role="dialog"
        aria-modal="false"
        aria-labelledby="fibonacci-settings-title"
        style={{ left: fibonacciSettings.left, top: fibonacciSettings.top }}
      >
        <div className="fibonacci-settings-head"><div><b id="fibonacci-settings-title">斐波那契比例设置</b><small>修改立即应用，并作为同类新图形默认值</small></div><button type="button" onClick={() => setFibonacciSettings(null)} aria-label="关闭斐波那契设置"><X /></button></div>
        <div className="fibonacci-level-list">
          {currentFibonacciLevels().map(level => <label key={level.id}>
            <input type="checkbox" checked={level.enabled} onChange={event => updateFibonacciLevels(currentFibonacciLevels().map(item => item.id === level.id ? { ...item, enabled: event.target.checked } : item))} />
            <span>{formatFibonacciLevel(level.value)}</span>
            <em>{level.custom ? "自定义" : "默认"}</em>
            {level.custom && <button type="button" aria-label={`删除自定义比例 ${formatFibonacciLevel(level.value)}`} onClick={() => updateFibonacciLevels(currentFibonacciLevels().filter(item => item.id !== level.id))}><Trash2 /></button>}
          </label>)}
        </div>
        <form className="fibonacci-custom-form" onSubmit={event => { event.preventDefault(); addCustomFibonacciLevel(); }}>
          <label><span>新增自定义比例</span><input ref={fibonacciInputRef} value={customFibonacciValue} onChange={event => { setCustomFibonacciValue(event.target.value); setFibonacciError(""); }} inputMode="decimal" placeholder="例如 1.414" aria-label="自定义斐波那契比例" /></label>
          <button type="submit"><Plus />新增</button>
        </form>
        {fibonacciError && <p className="fibonacci-error" role="alert">{fibonacciError}</p>}
        <p className="fibonacci-hint">按 Esc 或点击菜单外部关闭。</p>
      </section>
    </div>}
  </div>;
}

function DetailPanel({ stock }: { stock: Stock | null }) {
  if (!stock) return <PanelEmpty title="尚未选择股票" text="先搜索或从自选中打开一只股票。" />;
  return <div className="detail-panel"><div className="panel-title"><Layers3 /><div><h3>{stock.name}</h3><p>{stock.ts_code}</p></div></div><dl><dt>市场</dt><dd>{stock.market || "—"}</dd><dt>行业</dt><dd>{stock.industry || "—"}</dd><dt>总市值</dt><dd>{fmtMarketValue(stock.total_mv)}</dd><dt>市盈率 TTM</dt><dd>{fmtNumber(stock.pe_ttm)}</dd><dt>市净率</dt><dd>{fmtNumber(stock.pb)}</dd><dt>ST 状态</dt><dd>{stock.is_st ? "是" : "否"}</dd></dl><div className="panel-dates"><b>数据表日期</b><span>行情 {formatDate(stock.as_of?.quote)}</span><span>估值 {formatDate(stock.as_of?.valuation)}</span><span>ST {formatDate(stock.as_of?.st)}</span><span>复权 {formatDate(stock.as_of?.adj_factor)}</span></div>{stock.warnings?.map(item => <p className="panel-warning" key={item}>{item}</p>)}</div>;
}

function TemplateWorkspace({ activeCode, templateId, templates, pool, poolLoading, onTemplate, onChoose, children }: { activeCode: string | null; templateId: string; templates: TemplateDefinition[]; pool: TemplateStock[]; poolLoading: boolean; onTemplate: (id: string) => void; onChoose: (code: string) => void; children: React.ReactNode }) {
  const activeButtonRef = useRef<HTMLButtonElement>(null);
  const workspaceRef = useRef<HTMLDivElement>(null);
  const resizing = useRef(false);
  const [poolHeight, setPoolHeight] = useState<number | null>(null);

  useEffect(() => {
    activeButtonRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeCode]);

  const splitBounds = useCallback(() => {
    const height = workspaceRef.current?.clientHeight || 0;
    const minArea = Math.max(120, Math.min(210, (height - 10) * 0.35));
    return { min: minArea, max: Math.max(minArea, height - 10 - minArea) };
  }, []);

  const resizeAt = useCallback((clientY: number) => {
    const bounds = workspaceRef.current?.getBoundingClientRect();
    if (!bounds) return;
    const limits = splitBounds();
    setPoolHeight(Math.max(limits.min, Math.min(limits.max, clientY - bounds.top)));
  }, [splitBounds]);

  function startSplitResize(event: React.PointerEvent<HTMLDivElement>) {
    resizing.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    resizeAt(event.clientY);
  }

  function moveSplitResize(event: React.PointerEvent<HTMLDivElement>) {
    if (resizing.current) resizeAt(event.clientY);
  }

  function stopSplitResize(event: React.PointerEvent<HTMLDivElement>) {
    resizing.current = false;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }

  function splitKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown" && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    const limits = splitBounds();
    setPoolHeight(current => event.key === "Home"
      ? limits.min
      : event.key === "End"
        ? limits.max
        : Math.max(limits.min, Math.min(limits.max, (current ?? (limits.min + limits.max) / 2) + (event.key === "ArrowDown" ? 24 : -24))));
  }

  return <div
    ref={workspaceRef}
    className="pattern-workspace template-workspace"
    style={{ "--pattern-pool-height": poolHeight == null ? "54%" : `${poolHeight}px` } as React.CSSProperties}
    data-pattern-pool-height={poolHeight == null ? "default" : Math.round(poolHeight)}
  >
    <section className="pattern-pool-section template-list-section" aria-labelledby="template-list-title">
      <div className="panel-section-heading"><b id="template-list-title">模板股票列表</b><span>{pool.length} 只 · ↑↓切换 · 滚轮滚动</span></div>
      <label className="pattern-group template-group-select"><span>当前模板</span><select data-testid="template-group-select" value={templateId} onChange={event => onTemplate(event.target.value)}>{templates.map(item => <option key={item.id} value={item.id}>{item.kind === "custom" ? `自定义 · ${item.name}` : item.name}</option>)}</select></label>
      <div className="pattern-pool template-stock-list" data-testid="template-stock-list" data-wheel-behavior="scroll-only">{poolLoading ? <p>正在加载模板股票…</p> : pool.length ? pool.map((item, index) => <button ref={item.code === activeCode ? activeButtonRef : undefined} key={item.ts_code} aria-current={item.code === activeCode ? "true" : undefined} className={item.code === activeCode ? "active" : ""} onClick={() => onChoose(item.code)}><b>{item.rank || index + 1}</b><span><strong>{item.name}</strong><small>{item.code}</small></span><em>{item.score.toFixed(3)}</em></button>) : <p>该模板当前没有可用股票</p>}</div>
    </section>
    <div
      className="pattern-splitter template-splitter"
      data-testid="template-splitter"
      role="separator"
      aria-label="调整模板股票列表与曲线比较高度"
      aria-orientation="horizontal"
      aria-valuemin={120}
      aria-valuemax={1000}
      aria-valuenow={Math.round(poolHeight ?? 320)}
      tabIndex={0}
      onPointerDown={startSplitResize}
      onPointerMove={moveSplitResize}
      onPointerUp={stopSplitResize}
      onPointerCancel={stopSplitResize}
      onKeyDown={splitKeyDown}
    ><span /></div>
    <section className="pattern-facts-section template-comparison-section" aria-labelledby="template-comparison-title">
      <div className="panel-section-heading"><b id="template-comparison-title">模板与当前窗口</b><span>{activeCode || "未选择"}</span></div>
      <div className="pattern-facts template-comparison">{children}</div>
    </section>
  </div>;
}

function TemplateComparisonPanel({ stock, template, candidate, loading, error, onRetry, returnHref, returnLabel }: { stock: Stock | null; template: TemplateDefinition | null; candidate: TemplateStock | null; loading: boolean; error: string; onRetry: () => void; returnHref: string; returnLabel: string }) {
  const [candidateBars, setCandidateBars] = useState<Bar[]>(() => candidate?.bars || []);
  const [candidateKlineState, setCandidateKlineState] = useState<"idle" | "loading" | "ready" | "error">(() => {
    if (!candidate) return "idle";
    if (candidate.bars.length) return "ready";
    return candidate.start_date && candidate.end_date ? "loading" : "error";
  });
  const [candidateRetry, setCandidateRetry] = useState(0);

  useEffect(() => {
    let active = true;
    if (!candidate || candidate.bars.length || !candidate.start_date || !candidate.end_date) {
      return () => { active = false; };
    }
    void api.barsWindow(candidate.code, candidate.start_date, candidate.end_date, candidate.window_length || template?.window_length || 240)
      .then(result => {
        if (!active) return;
        setCandidateBars(result.items);
        setCandidateKlineState("ready");
      })
      .catch(() => {
        if (active) setCandidateKlineState("error");
      });
    return () => { active = false; };
  }, [candidate, candidateRetry, template?.window_length]);

  if (!stock) return <PanelEmpty title="尚未选择股票" text="从模板股票列表中打开一只股票。" />;
  if (loading) return <PanelEmpty title="正在读取模板主 K 线" text="Top100 排名和候选缩略图会分别呈现。" />;
  if (error) return <div className="panel-error"><p>{error}</p><button onClick={onRetry}>重试</button></div>;
  if (!template) return <PanelEmpty title="模板不可用" text="请重新选择一个模板。" />;
  if (!candidate) return <div className="template-not-ranked"><CircleDot /><h3>未进入这个模板的 Top100</h3><p>{stock.name} 不在当前 Top100，因此不显示推测分数。</p><Link href={returnHref}>{returnLabel}</Link></div>;
  return <div className="template-comparison-panel">
    <div className="template-comparison-head"><div><small>{template.kind === "custom" ? "自定义模板" : "冻结模板"}</small><h3>{template.name}</h3></div><strong>{candidate.score.toFixed(3)}</strong></div>
    <div className="template-kline-pair">
      <figure>
        <figcaption><strong>模板真实 K 线</strong><small>{template.start_date ? `${formatDate(template.start_date)}—${formatDate(template.end_date)}` : "冻结窗口"}</small></figcaption>
        <CandlestickPreview bars={template.bars} height={132} label={`${template.name}模板真实前复权 K 线`} />
      </figure>
      <figure>
        <figcaption><strong>候选真实 K 线</strong><small>{candidateKlineState === "loading" ? "正在加载缩略图" : candidate.start_date ? `${formatDate(candidate.start_date)}—${formatDate(candidate.end_date)}` : "候选窗口"}</small></figcaption>
        {candidateBars.length
          ? <CandlestickPreview bars={candidateBars} height={132} label={`${stock.name}候选窗口真实前复权 K 线`} />
          : candidateKlineState === "error"
            ? <button className="candidate-kline-retry" onClick={() => { setCandidateKlineState("loading"); setCandidateRetry(value => value + 1); }}>重试候选 K 线</button>
            : <div className="candidate-kline-loading">排名已就绪，正在加载候选缩略图…</div>}
      </figure>
    </div>
    <dl className="template-comparison-facts">
      <div><dt>相似度</dt><dd>{candidate.score.toFixed(3)}</dd></div>
      <div><dt>窗口长度</dt><dd>{template.window_length || template.curve.length} 日</dd></div>
      <div><dt>候选区间</dt><dd>{candidate.start_date ? `${formatDate(candidate.start_date)}—${formatDate(candidate.end_date)}` : "按最新等长窗口"}</dd></div>
      <div><dt>模板区间</dt><dd>{template.start_date ? `${formatDate(template.start_date)}—${formatDate(template.end_date)}` : "冻结定义"}</dd></div>
    </dl>
    <p className="template-description">{template.description || template.cue || "两张图都来自本机前复权日线。"}</p>
    <p className="template-stage-note">阶段提示：相似度只比较各自选中窗口的 log-close 形状。请结合两张真实 K 线与起止位置判断更接近起涨、加速或末端；这里不使用未来表现作验证。</p>
    <Link className="pattern-link" href={returnHref}>{returnLabel}</Link>
  </div>;
}
function PanelEmpty({ title, text }: { title: string; text: string }) { return <div className="right-placeholder"><CircleDot /><h3>{title}</h3><p>{text}</p></div>; }
function QuoteFact({ label, value }: { label: string; value: string }) { return <span><small>{label}</small><b>{value}</b></span>; }
function DrawingButton({ label, hint, active, onClick, children }: { label: string; hint?: string; active: boolean; onClick: () => void; children: React.ReactNode }) { return <button title={hint || label} aria-label={label} aria-pressed={active} className={active ? "active" : ""} onClick={onClick}>{children}</button>; }
function periodLabel(value: string) { return ({ D: "日K", W: "周K", M: "月K", Q: "季K", Y: "年K" } as Record<string, string>)[value] || value; }
function signed(value?: number) { if (value == null || !Number.isFinite(value)) return "—"; return `${value >= 0 ? "+" : ""}${fmtNumber(value)}`; }
function formatFibonacciLevel(value: number) { return `${Number(value.toFixed(4))}（${Number((value * 100).toFixed(2))}%）`; }
