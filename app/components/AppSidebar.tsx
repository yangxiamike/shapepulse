"use client";

import {
  BarChart3,
  CircleHelp,
  LayoutDashboard,
  LineChart,
  LogOut,
  Settings,
  Star,
} from "lucide-react";
import Link from "next/link";

export function AppSidebar({ active }: { active: "screen" | "market" }) {
  const market = active === "market";
  return (
    <aside className={`app-sidebar ${market ? "market-sidebar" : ""}`}>
      <div className="brand-lockup">
        <span className="brand-mark"><BarChart3 size={27} strokeWidth={2.8} /></span>
        <span className="brand-name">{market ? "本地行情" : "LC"}</span>
      </div>
      <nav className="primary-nav" aria-label="主导航">
        <Link className={`nav-item ${active === "screen" ? "active" : ""}`} href="/"><LayoutDashboard /><span>选股看板</span></Link>
        <Link className={`nav-item ${active === "market" ? "active" : ""}`} href="/market"><LineChart /><span>本地行情</span></Link>
        {market && <button className="nav-item icon-only" aria-label="自选"><Star /></button>}
      </nav>
      <div className="sidebar-bottom">
        <button className="nav-item icon-only" aria-label="设置"><Settings /></button>
        <button className="nav-item icon-only" aria-label="帮助"><CircleHelp /></button>
        {market && <button className="nav-item icon-only" aria-label="退出"><LogOut /></button>}
      </div>
    </aside>
  );
}
