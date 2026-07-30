import { chromium } from "@playwright/test";
import fs from "node:fs";

const appUrl = process.env.MEMORY_APP_URL || "http://127.0.0.1:13000";
const apiUrl = process.env.MEMORY_API_URL || "http://127.0.0.1:18765/api";
const eventsPath = process.env.MEMORY_EVENTS_PATH;
const stockLimit = Number(process.env.MEMORY_STOCKS || 40);

function event(name, detail = {}) {
  const row = { timestamp_ms: Date.now(), name, ...detail };
  fs.appendFileSync(eventsPath, `${JSON.stringify(row)}\n`, "utf8");
}

async function pageHeap(page) {
  const session = await page.context().newCDPSession(page);
  await session.send("Performance.enable");
  const metrics = await session.send("Performance.getMetrics");
  await session.detach();
  const values = Object.fromEntries(metrics.metrics.map(item => [item.name, item.value]));
  return {
    js_heap_used_mb: Number(((values.JSHeapUsedSize || 0) / 1048576).toFixed(1)),
    js_heap_total_mb: Number(((values.JSHeapTotalSize || 0) / 1048576).toFixed(1)),
    dom_nodes: values.Nodes || 0,
  };
}

async function checkpoint(page, name, detail = {}) {
  event(name, { ...detail, ...(await pageHeap(page)) });
}

async function waitForCompleteHistory(page, code) {
  const expected = code.split(".")[0];
  const deadline = Date.now() + 60_000;
  let last = {};
  while (Date.now() < deadline) {
    last = await page.evaluate(() => ({
      url: location.href,
      status: document.querySelector(".status-center")?.textContent || "",
      source_bars: Number(document.querySelector(".market-chart")?.getAttribute("data-source-bars") || 0),
      visible_bars: Number(document.querySelector(".market-chart")?.getAttribute("data-bars") || 0),
      error: document.querySelector(".chart-error")?.textContent || "",
    }));
    if (
      new URL(last.url).searchParams.get("code")?.startsWith(expected)
      && last.status.includes("完整历史")
    ) {
      return;
    }
    await page.waitForTimeout(500);
  }
  event("history_wait_diagnostic", { code, ...last });
  throw new Error(`complete history timed out for ${code}: ${JSON.stringify(last)}`);
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await context.newPage();
page.on("console", message => {
  if (message.type() === "error") event("browser_console_error", { text: message.text() });
});
page.on("pageerror", error => event("browser_page_error", { message: error.message }));
page.on("requestfailed", request => {
  if (request.url().includes("/api/")) {
    event("browser_request_failed", {
      url: request.url(),
      error: request.failure()?.errorText || "",
    });
  }
});

try {
  event("browser_started");
  const screenResponse = await context.request.post(`${apiUrl}/screen`, {
    data: {
      boards: ["主板", "创业板", "科创板"],
      industries: [],
      exclude_st: true,
      top_k: Math.max(200, stockLimit),
      mode: "combined",
      save_history: false,
    },
    timeout: 600_000,
  });
  if (!screenResponse.ok()) throw new Error(`screen failed: ${screenResponse.status()}`);
  const screen = await screenResponse.json();
  event("large_topk_screen", {
    results: screen.results?.length || 0,
    eligible: screen.counts?.eligible || 0,
    elapsed_ms: screen.elapsed_ms || 0,
  });
  const codes = [...new Set((screen.results || []).map(item => item.ts_code).filter(Boolean))];
  if (codes.length < stockLimit) {
    throw new Error(`screen returned ${codes.length} unique stocks; need ${stockLimit}`);
  }

  await page.goto(`${appUrl}/market?code=${encodeURIComponent(codes[0])}`, {
    waitUntil: "domcontentloaded",
    timeout: 60_000,
  });
  const chart = page.locator(".market-chart").first();
  await chart.waitFor({ state: "visible", timeout: 30_000 });

  for (let index = 0; index < stockLimit; index += 1) {
    const code = codes[index];
    if (index > 0) {
      const search = page.getByRole("textbox", { name: "搜索股票" });
      await search.fill(code.split(".")[0]);
      const option = page.locator(".search-results button").filter({ hasText: code.split(".")[0] }).first();
      await option.waitFor({ state: "visible", timeout: 20_000 });
      await option.click();
    }
    await waitForCompleteHistory(page, code);

    if (index === 0) {
      const box = await chart.boundingBox();
      if (!box) throw new Error("chart has no bounding box");
      const before = Number(await chart.getAttribute("data-visible-from"));
      await page.mouse.move(box.x + box.width * 0.25, box.y + box.height * 0.45);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width * 0.8, box.y + box.height * 0.45, { steps: 12 });
      await page.mouse.up();
      await page.waitForFunction(
        prior => Number(document.querySelector(".market-chart")?.getAttribute("data-visible-from")) < prior,
        before,
      );
      await page.getByRole("button", { name: "全部", exact: true }).click();
      await page.waitForFunction(() => {
        const node = document.querySelector(".market-chart");
        return Number(node?.getAttribute("data-bars")) === Number(node?.getAttribute("data-source-bars"));
      });
      await checkpoint(page, "all_and_drag", {
        source_bars: Number(await chart.getAttribute("data-source-bars")),
      });
      await page.getByRole("button", { name: "6个月", exact: true }).click();
    }

    if ([19, stockLimit - 1].includes(index)) {
      await page.getByRole("button", { name: /1 图布局/ }).click();
      await page.locator(".layout-menu").getByRole("button", { name: "4 图", exact: true }).click();
      await page.waitForFunction(() => document.querySelectorAll(".market-chart").length === 4);
      await checkpoint(page, `view_${index + 1}_four_charts`, {
        source_bars: Number(await page.locator(".market-chart").first().getAttribute("data-source-bars")),
      });
      await page.getByRole("button", { name: "恢复单图" }).click();
      await page.waitForFunction(() => document.querySelectorAll(".market-chart").length === 1);
    }
    if ([0, 9, 19, 29, stockLimit - 1].includes(index)) {
      await checkpoint(page, `view_${index + 1}`, {
        code,
        source_bars: Number(await page.locator(".market-chart").first().getAttribute("data-source-bars")),
      });
    }
  }

  const industryResponse = await context.request.get(
    `${apiUrl}/industry-strength?pattern=breakout`,
    { timeout: 600_000 },
  );
  if (!industryResponse.ok()) {
    throw new Error(`industry strength failed: ${industryResponse.status()}`);
  }
  const industry = await industryResponse.json();
  await checkpoint(page, "industry_strength", {
    elapsed_ms: industry.timings?.total_ms || 0,
    industries: industry.items?.length || industry.industries?.length || 0,
  });
  event("complete");
} catch (error) {
  event("error", { message: error instanceof Error ? error.stack : String(error) });
  throw error;
} finally {
  await browser.close();
}
