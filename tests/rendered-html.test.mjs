import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

async function render(path = "/") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}-${path}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(new Request(`http://localhost${path}`, { headers: { accept: "text/html" } }), {
    ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) },
  }, { waitUntil() {}, passThroughOnException() {} });
}

test("server-renders the template library as the main entry", async () => {
  const response = await render("/");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /<title>模板库 \| 手动跟踪市场<\/title>/i);
  assert.match(html, /模板库/);
  assert.match(html, /自定义模板/);
  assert.match(html, /保存并分析/);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton/i);
});

test("server-renders the legacy selection board only on its compatibility route", async () => {
  const response = await render("/legacy-screen");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /<title>旧版选股看板 \| 手动跟踪市场<\/title>/i);
  assert.match(html, /运行筛选/);
  assert.match(html, /综合榜/);
});

test("server-renders the independent market terminal", async () => {
  const response = await render("/market?code=000001");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /<title>本地行情终端 \| 手动跟踪市场<\/title>/i);
  assert.match(html, /搜索股票名称/);
  assert.match(html, /自选/);
  assert.match(html, /模板/);
  assert.match(html, /保存当前区间为模板/);
  assert.doesNotMatch(html, /交易/);
  assert.doesNotMatch(html, /今日推荐|筛选进度|上一只|下一只/);
});

test("server-renders the industry strength page and fixed scope", async () => {
  const response = await render("/industry-strength");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /<title>行业强弱 \| 手动跟踪市场<\/title>/i);
  assert.match(html, /行业强弱/);
  assert.match(html, /Top 100/);
  assert.match(html, /正在计算 24 个真实历史截面/);
  assert.match(html, /aria-label="固定统计口径"/);
  assert.match(html, /aria-expanded="false"/);
});

test("starter preview has been removed", async () => {
  const [page, layout, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);
  assert.match(page, /<TemplateLibraryClient \/>/);
  assert.match(layout, /lang="zh-CN"/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  await assert.rejects(access(new URL("../app/_sites-preview/SkeletonPreview.tsx", import.meta.url)));
});
