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

test("server-renders the selection board", async () => {
  const response = await render("/");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /<title>综合选股看板 \| 手动跟踪市场<\/title>/i);
  assert.match(html, /选股看板/);
  assert.match(html, /运行筛选/);
  assert.match(html, /综合榜/);
  assert.match(html, /突破启动/);
  assert.match(html, /上升趋势回调/);
  assert.match(html, /区间下沿反弹/);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton/i);
});

test("server-renders the independent market terminal", async () => {
  const response = await render("/market?code=000001");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /<title>本地行情终端 \| 手动跟踪市场<\/title>/i);
  assert.match(html, /搜索股票名称/);
  assert.match(html, /自选/);
  assert.match(html, /形态/);
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
  assert.match(html, /回看 120 个交易日/);
  assert.match(html, /每 5 个交易日采样/);
  assert.match(html, /共 24 个节点/);
  assert.match(html, /固定统计口径/);
});

test("starter preview has been removed", async () => {
  const [page, layout, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);
  assert.match(page, /<BoardClient \/>/);
  assert.match(layout, /lang="zh-CN"/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  await assert.rejects(access(new URL("../app/_sites-preview/SkeletonPreview.tsx", import.meta.url)));
});
