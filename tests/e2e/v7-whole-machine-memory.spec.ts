import { expect, test } from "@playwright/test";


async function browserMemory(page: import("@playwright/test").Page) {
  const session = await page.context().newCDPSession(page);
  const result = await session.send("Performance.getMetrics");
  await session.detach();
  const metrics = Object.fromEntries(
    result.metrics.map(item => [item.name, item.value]),
  );
  return {
    timestamp: new Date().toISOString(),
    js_heap_used_bytes: metrics.JSHeapUsedSize || 0,
    js_heap_total_bytes: metrics.JSHeapTotalSize || 0,
    nodes: metrics.Nodes || 0,
    documents: metrics.Documents || 0,
  };
}


test("complete history stays correct across one/four charts, all, drag, and stock switch", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto("/market?code=000001");
  const first = page.locator(".market-chart").first();
  await expect.poll(
    async () => Number(await first.getAttribute("data-source-bars")),
    { timeout: 30_000 },
  ).toBeGreaterThan(1_000);
  await expect(first).toHaveAttribute("data-bars", "110");
  const before = await browserMemory(page);
  const initialVisibleStart = String(await first.getAttribute("data-visible-first-time"));

  const box = await first.boundingBox();
  if (!box) throw new Error("market chart is not visible");
  await page.mouse.move(box.x + box.width * 0.25, box.y + box.height * 0.45);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.8, box.y + box.height * 0.45, {
    steps: 12,
  });
  await page.mouse.up();
  await expect.poll(
    async () => String(await first.getAttribute("data-visible-first-time")),
  ).not.toBe(initialVisibleStart);

  await page.getByRole("button", { name: /1 图布局/ }).click();
  await page.locator(".layout-menu").getByRole("button", { name: "4 图", exact: true }).click();
  const charts = page.locator(".market-chart");
  await expect(charts).toHaveCount(4);
  const sourceBars = Number(await charts.first().getAttribute("data-source-bars"));
  for (let index = 0; index < 4; index += 1) {
    await expect(charts.nth(index)).toHaveAttribute("data-source-bars", String(sourceBars));
    await expect(charts.nth(index)).toHaveAttribute("data-bars", "110");
  }
  const fourCharts = await browserMemory(page);

  await page.getByRole("button", { name: "全部", exact: true }).click();
  await expect.poll(async () => {
    const values = await charts.evaluateAll(nodes => nodes.map(node => ({
      visible: Number(node.getAttribute("data-bars")),
      source: Number(node.getAttribute("data-source-bars")),
    })));
    return values.length === 4 && values.every(item => item.visible === item.source);
  }).toBeTruthy();

  const search = page.getByRole("textbox", { name: "搜索股票" });
  await search.fill("000858");
  await page.locator(".search-results button").filter({ hasText: "000858" }).first().click();
  await expect.poll(() => new URL(page.url()).searchParams.get("code")).toBe("000858");
  await expect.poll(
    async () => Number(await charts.first().getAttribute("data-source-bars")),
    { timeout: 30_000 },
  ).toBeGreaterThan(1_000);
  for (let index = 0; index < 4; index += 1) {
    await expect(charts.nth(index)).toHaveAttribute("data-bars", "110");
  }
  const switched = await browserMemory(page);
  await testInfo.attach("browser-memory.json", {
    body: Buffer.from(JSON.stringify({ before, fourCharts, switched }, null, 2)),
    contentType: "application/json",
  });

  // Four panes share preprocessing, so renderer heap growth must remain far below
  // the simple four-times failure mode even though chart instances are distinct.
  expect(fourCharts.js_heap_used_bytes).toBeLessThan(
    Math.max(before.js_heap_used_bytes * 3, before.js_heap_used_bytes + 96 * 1024 * 1024),
  );
});
