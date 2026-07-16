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
  const initialBreakdown = await readPerformanceBreakdown(page);

  const firstWeeklyStarted = performance.now();
  await page.getByRole("button", { name: "周K", exact: true }).click();
  await expect(page.locator(".market-chart")).not.toHaveAttribute("data-bars", "110");
  const weeklyCount = await page.locator(".market-chart").getAttribute("data-bars");
  const firstWeeklyMs = performance.now() - firstWeeklyStarted;
  const weeklyBreakdown = await readPerformanceBreakdown(page);

  await page.getByRole("button", { name: "日K", exact: true }).click();
  await expect(page.locator(".market-chart")).toHaveAttribute("data-bars", "110");
  const repeatWeeklyStarted = performance.now();
  await page.getByRole("button", { name: "周K", exact: true }).click();
  await expect(page.locator(".market-chart")).toHaveAttribute("data-bars", weeklyCount || "27");
  await expect(page.getByTestId("market-performance")).toContainText("缓存");
  const repeatWeeklyMs = performance.now() - repeatWeeklyStarted;
  const repeatBreakdown = await readPerformanceBreakdown(page);
  const detailRequestsBeforeSwitch = detailRequests;

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
  const switchBreakdown = await readPerformanceBreakdown(page);
  const detailRequestsAfterSwitch = detailRequests;

  await page.goto("/");
  await expect(page.locator(".candidate-table tbody tr").first()).toBeVisible({ timeout: 20_000 });
  const runButton = page.locator(".run-button");
  await expect(runButton).toBeEnabled();
  await page.locator(".market-value-control input[type=number]").fill("51");
  const recomputeStarted = performance.now();
  await runButton.click();
  await expect(runButton).toBeDisabled();
  const feedbackMs = performance.now() - recomputeStarted;
  await expect(page.locator(".screen-progress")).toBeVisible();
  await expect(runButton).toBeEnabled({ timeout: 5_000 });
  const recomputeMs = performance.now() - recomputeStarted;

  const repeatedScreenStarted = performance.now();
  await runButton.click();
  await expect(runButton).toBeDisabled();
  const repeatedFeedbackMs = performance.now() - repeatedScreenStarted;
  await expect(runButton).toBeEnabled({ timeout: 3_000 });
  const repeatedScreenMs = performance.now() - repeatedScreenStarted;

  const boardToMarketStarted = performance.now();
  await page.locator(".open-market-button").click();
  await expect(page.getByRole("heading", { name: "特一药业" })).toBeVisible();
  await expect(page.locator(".market-chart")).toHaveAttribute("data-bars", "110");
  const boardToMarketMs = performance.now() - boardToMarketStarted;

  const resultPayload = {
    captured_at: new Date().toISOString(),
    viewport: "1600x1000",
    groups: {
      first: { frontend_ms: round(initialMs), detail_requests: 1, breakdown: initialBreakdown, bars: barsResponses[0] || null },
      repeat: { frontend_ms: round(repeatWeeklyMs), client_cache_hit: true, breakdown: repeatBreakdown },
      same_stock: { first_weekly_ms: round(firstWeeklyMs), detail_requests: detailRequestsBeforeSwitch, weekly_count: Number(weeklyCount), breakdown: weeklyBreakdown },
      switched_stock: { search_ms: round(searchMs), switch_ms: round(switchStockMs), total_detail_requests: detailRequestsAfterSwitch, breakdown: switchBreakdown },
      screening: {
        button_feedback_ms: round(feedbackMs),
        first_filter_ms: round(recomputeMs),
        progress_seen: true,
        repeated_button_feedback_ms: round(repeatedFeedbackMs),
        repeated_filter_ms: round(repeatedScreenMs),
      },
      board_to_market: { frontend_ms: round(boardToMarketMs), code: "002728" },
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
  expect(detailRequestsAfterSwitch).toBe(2);
  expect(feedbackMs).toBeLessThanOrEqual(100);
  expect(repeatedFeedbackMs).toBeLessThanOrEqual(100);
  expect(recomputeMs).toBeLessThanOrEqual(3000);
  expect(repeatedScreenMs).toBeLessThanOrEqual(1000);
  expect(boardToMarketMs).toBeLessThanOrEqual(2000);
});

function round(value: number) { return Math.round(value * 10) / 10; }

async function readPerformanceBreakdown(page: import("@playwright/test").Page) {
  const text = (await page.getByTestId("market-performance").innerText()).trim();
  const values = [...text.matchAll(/(\d+)ms/g)].map(match => Number(match[1]));
  return {
    text,
    frontend_ms: values[0] ?? null,
    http_ms: values[1] ?? null,
    backend_query_ms: values[2] ?? null,
    chart_redraw_ms: values[3] ?? null,
    cache_hit: text.includes("缓存"),
  };
}
