import { mkdir, writeFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

type BarsTiming = {
  url: string;
  cache_hit: boolean;
  timings: Record<string, number>;
  bar_count: number;
};

test("v1.1 interaction budgets and cache contract", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 1000 });
  const barsResponses: BarsTiming[] = [];
  let detailRequests = 0;
  page.on("request", request => {
    if (request.url().includes("/api/stock/")) detailRequests += 1;
  });
  page.on("response", response => {
    if (!response.url().includes("/api/bars/") || !response.ok()) return;
    void response.json().then(body => barsResponses.push({
      url: response.url(),
      cache_hit: Boolean(body.cache_hit),
      timings: body.timings || {},
      bar_count: Array.isArray(body.bars) ? body.bars.length : 0,
    })).catch(() => undefined);
  });

  const initialStarted = performance.now();
  await page.goto("/market?code=600519");
  await expect(page.getByRole("heading", { name: "贵州茅台" })).toBeVisible();
  await expect(page.locator(".market-chart")).toHaveAttribute("data-bars", "110");
  const initialMs = performance.now() - initialStarted;

  const firstWeeklyStarted = performance.now();
  await page.getByRole("button", { name: "周K", exact: true }).click();
  await expect(page.locator(".market-chart")).not.toHaveAttribute("data-bars", "110");
  const weeklyCount = await page.locator(".market-chart").getAttribute("data-bars");
  const firstWeeklyMs = performance.now() - firstWeeklyStarted;

  await page.getByRole("button", { name: "日K", exact: true }).click();
  await expect(page.locator(".market-chart")).toHaveAttribute("data-bars", "110");
  const repeatWeeklyStarted = performance.now();
  await page.getByRole("button", { name: "周K", exact: true }).click();
  await expect(page.locator(".market-chart")).toHaveAttribute("data-bars", weeklyCount || "27");
  await expect(page.getByTestId("market-performance")).toContainText("缓存");
  const repeatWeeklyMs = performance.now() - repeatWeeklyStarted;

  const search = page.getByRole("textbox", { name: "搜索股票" });
  const searchStarted = performance.now();
  await search.fill("000858");
  const result = page.locator(".search-results button").filter({ hasText: "000858" }).first();
  await expect(result).toBeVisible();
  const searchMs = performance.now() - searchStarted;
  const switchStarted = performance.now();
  await result.click();
  await expect(page.getByRole("heading", { name: "五粮液" })).toBeVisible();
  await expect(page.locator(".market-chart")).toHaveAttribute("data-bars", "110");
  const switchStockMs = performance.now() - switchStarted;

  const resultPayload = {
    captured_at: new Date().toISOString(),
    viewport: "1600x1000",
    groups: {
      first: { frontend_ms: round(initialMs), detail_requests: 1, bars: barsResponses[0] || null },
      repeat: { frontend_ms: round(repeatWeeklyMs), client_cache_hit: true },
      same_stock: { first_weekly_ms: round(firstWeeklyMs), detail_requests: detailRequests - 1, weekly_count: Number(weeklyCount) },
      switched_stock: { search_ms: round(searchMs), switch_ms: round(switchStockMs), total_detail_requests: detailRequests },
    },
    raw_bars_responses: barsResponses,
  };
  const directory = "docs/qa/evidence/v1.1";
  await mkdir(directory, { recursive: true });
  await writeFile(`${directory}/performance.json`, `${JSON.stringify(resultPayload, null, 2)}\n`, "utf8");

  expect(searchMs).toBeLessThanOrEqual(300);
  expect(initialMs).toBeLessThanOrEqual(2000);
  expect(firstWeeklyMs).toBeLessThanOrEqual(700);
  expect(repeatWeeklyMs).toBeLessThanOrEqual(300);
  expect(switchStockMs).toBeLessThanOrEqual(1000);
  expect(detailRequests).toBe(2);
});

function round(value: number) { return Math.round(value * 10) / 10; }
