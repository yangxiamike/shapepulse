import type { Metadata } from "next";
import { TemplateBreadthV3Client } from "../components/TemplateBreadthV3Client";

export const metadata: Metadata = {
  title: "形态宽度试用页 | 手动跟踪市场",
  description: "使用 0.80 试用观察线查看四模板的市场扩散与行业宽度。",
};

export default function TemplateBreadthV3Page() {
  return <TemplateBreadthV3Client />;
}
