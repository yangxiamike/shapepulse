import type { Metadata } from "next";
import { BoardClient } from "./components/BoardClient";

export const metadata: Metadata = {
  title: "综合选股看板 | 手动跟踪市场",
  description: "基于本地 A 股数据库的形态筛选与人工复核看板。",
};

export default function Home() {
  return <BoardClient />;
}
