import type { Metadata } from "next";
import { TemplateLibraryClient } from "../components/TemplateLibraryClient";

export const metadata: Metadata = {
  title: "模板库 | 手动跟踪市场",
  description: "浏览冻结四模板，保存自定义 K 线窗口，并查看相似股票。",
};

export default function TemplatesPage() {
  return <TemplateLibraryClient />;
}
