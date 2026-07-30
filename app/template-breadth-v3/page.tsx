import type { Metadata } from "next";
import { TemplateBreadthV3Client } from "../components/TemplateBreadthV3Client";

export const metadata: Metadata = {
  title: "Top100 行业宽度 | 手动跟踪市场",
  description:
    "四个冻结模板的当日 Top100 行业宽度、10/20 个实际交易日净变化与按需行业明细",
};

export default function TemplateBreadthV3Page() {
  return <TemplateBreadthV3Client />;
}
