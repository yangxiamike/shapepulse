import type { Metadata } from "next";
import { MarketClient } from "../components/MarketClient";

export const metadata: Metadata = {
  title: "本地行情终端 | 手动跟踪市场",
  description: "使用本地历史行情的独立 A 股 K 线查看终端。",
};

export default function MarketPage() {
  return <MarketClient />;
}
