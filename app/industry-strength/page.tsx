import type { Metadata } from "next";
import { IndustryStrengthClient } from "../components/IndustryStrengthClient";

export const metadata: Metadata = {
  title: "行业强弱 | 手动跟踪市场",
  description: "基于本地真实形态 Top 100 截面的申万一级行业强弱、轮动与集中度分析。",
};

export default function IndustryStrengthPage() {
  return <IndustryStrengthClient />;
}
