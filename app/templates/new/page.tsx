import type { Metadata } from "next";
import { NewTemplateClient } from "../../components/NewTemplateClient";

export const metadata: Metadata = {
  title: "新建模板 | 手动跟踪市场",
  description: "搜索本地股票，在真实前复权 K 线上框选 20–240 个交易日并保存自定义模板。",
};

export default function NewTemplatePage() {
  return <NewTemplateClient />;
}
