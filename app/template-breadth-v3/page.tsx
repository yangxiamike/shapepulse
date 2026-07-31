import type { Metadata } from "next";
import { TemplateBreadthV3Client } from "../components/TemplateBreadthV3Client";

export const metadata: Metadata = {
  title: "Top100 行业宽度 | 手动跟踪市场",
  description:
    "四个冻结模板的一年期 Top100 行业空间、行业 B 健康监测、核心行业与平滑走弱状态",
};

export default function TemplateBreadthV3Page() {
  return <TemplateBreadthV3Client />;
}
