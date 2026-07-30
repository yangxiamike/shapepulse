import type { Metadata } from "next";
import { TemplateBreadthV3Client } from "../components/TemplateBreadthV3Client";

export const metadata: Metadata = {
  title: "Top100 行业宽度 | 手动跟踪市场",
  description:
    "四个冻结模板的一年期 Top100 行业空间、10/20 个实际交易日净变化与按需最新行业明细",
};

export default function TemplateBreadthV3Page() {
  return <TemplateBreadthV3Client />;
}
