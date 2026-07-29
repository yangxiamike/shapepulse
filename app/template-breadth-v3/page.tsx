import type { Metadata } from "next";
import { TemplateBreadthV3Client } from "../components/TemplateBreadthV3Client";

export const metadata: Metadata = {
  title: "Top100 行业宽度 | 手动跟踪市场",
  description: "按冻结四模板各自每日 Pearson Top100 查看行业宽度、入选率和五日进出变化。",
};

export default function TemplateBreadthV3Page() {
  return <TemplateBreadthV3Client />;
}
