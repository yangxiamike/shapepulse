import type { Metadata } from "next";
import { BoardClient } from "../components/BoardClient";

export const metadata: Metadata = {
  title: "旧版选股看板 | 手动跟踪市场",
  description: "保留的旧版三形态筛选页面。",
};

export default function LegacyScreenPage() {
  return <BoardClient />;
}
