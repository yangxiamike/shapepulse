"use client";

import { useEffect, useState } from "react";
import {
  Activity,
  BarChart3,
  CircleHelp,
  LayoutDashboard,
  LineChart,
  LogOut,
} from "lucide-react";
import Link from "next/link";

export type UiFontSize = "small" | "standard" | "large";

export const UI_FONT_STORAGE_KEY = "manual-market-font-size";
const fontSizes: Array<{ value: UiFontSize; short: string; label: string }> = [
  { value: "small", short: "小", label: "小字体" },
  { value: "standard", short: "标", label: "标准字体" },
  { value: "large", short: "大", label: "大字体" },
];

function applyFontSize(next: UiFontSize, persist = true) {
  document.documentElement.dataset.fontSize = next;
  if (persist) window.localStorage.setItem(UI_FONT_STORAGE_KEY, next);
  window.dispatchEvent(new CustomEvent("ui-font-size-change", { detail: next }));
}

export function AppSidebar({ active }: { active: "screen" | "market" | "industry-strength" }) {
  const [fontSize, setFontSize] = useState<UiFontSize>("standard");

  useEffect(() => {
    const stored = window.localStorage.getItem(UI_FONT_STORAGE_KEY);
    const initial = stored === "small" || stored === "large" ? stored : "standard";
    applyFontSize(initial, false);
    queueMicrotask(() => setFontSize(initial));
  }, []);

  function changeFontSize(next: UiFontSize) {
    setFontSize(next);
    applyFontSize(next);
  }

  return (
    <aside className="app-sidebar">
      <div className="brand-lockup">
        <span className="brand-mark"><BarChart3 size={27} strokeWidth={2.8} /></span>
        <span className="brand-name">LC</span>
      </div>
      <nav className="primary-nav" aria-label="主导航">
        <Link aria-label="选股看板" className={`nav-item ${active === "screen" ? "active" : ""}`} href="/"><LayoutDashboard /><span>选股看板</span></Link>
        <Link aria-label="本地行情" className={`nav-item ${active === "market" ? "active" : ""}`} href="/market"><LineChart /><span>本地行情</span></Link>
        <Link aria-label="行业强弱" className={`nav-item ${active === "industry-strength" ? "active" : ""}`} href="/industry-strength"><Activity /><span>行业强弱</span></Link>
      </nav>
      <div className="sidebar-bottom">
        <div className="font-size-control" role="group" aria-label="字体大小">
          <span>字号</span>
          <div>
            {fontSizes.map(option => <button
              key={option.value}
              type="button"
              aria-label={option.label}
              aria-pressed={fontSize === option.value}
              className={fontSize === option.value ? "active" : ""}
              onClick={() => changeFontSize(option.value)}
            >{option.short}</button>)}
          </div>
        </div>
        <button className="nav-item icon-only" aria-label="帮助"><CircleHelp /></button>
        <button className="nav-item icon-only" aria-label="退出"><LogOut /></button>
      </div>
    </aside>
  );
}
