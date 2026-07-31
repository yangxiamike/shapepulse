import type { Metadata } from "next";
import { TemplateBreadthV3Client } from "../components/TemplateBreadthV3Client";

export const metadata: Metadata = {
  title: "Top100 行业宽度 | 手动跟踪市场",
  description:
    "四个冻结模板的一年期 Top100 行业空间，以及趋势模板热力图内的行业 B Top1 与持续走弱提示",
};

export default function TemplateBreadthV3Page() {
  return <TemplateBreadthV3Client />;
}
