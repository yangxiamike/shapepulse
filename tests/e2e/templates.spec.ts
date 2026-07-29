import { expect, test } from "@playwright/test";

const frozen = [
  ["fresh_breakout", "刚突破", 50],
  ["healthy_uptrend", "健康上涨", 80],
  ["pullback_strengthening", "回调转强", 55],
  ["parabolic_uptrend", "抛物线上升", 160],
].map(([id, label, windowBars]) => ({
  id,
  key: id,
  label,
  name: label,
  source: "frozen",
  read_only: true,
  source_ts_code: "000001.SZ",
  start_date: "20250102",
  end_date: "20250630",
  window_bars: windowBars,
  bars: Array.from({ length: Number(windowBars) }, (_, index) => {
    const close = 10 + index * .05 + Math.sin(index / 4) * .2;
    return {
      trade_date: `2025${String(Math.floor(index / 20) + 1).padStart(2, "0")}${String(index % 20 + 1).padStart(2, "0")}`,
      open: close - .08,
      high: close + .18,
      low: close - .2,
      close,
    };
  }),
}));

const stockItems = Array.from({ length: 30 }, (_, index) => ({
  template_id: "fresh_breakout",
  rank: index + 1,
  ts_code: `${String(index + 1).padStart(6, "0")}.SZ`,
  code: String(index + 1).padStart(6, "0"),
  name: `模板股票${index + 1}`,
  industry: "测试行业",
  score: .95 - index * .005,
  start_date: "20260101",
  end_date: "20260320",
  window_bars: 50,
  bars: Array.from({ length: 50 }, (_, barIndex) => {
    const close = 10 + barIndex * .04 + Math.sin(barIndex / 4) * .2;
    return {
      trade_date: `2026${String(Math.floor(barIndex / 20) + 1).padStart(2, "0")}${String(barIndex % 20 + 1).padStart(2, "0")}`,
      open: close - .08,
      high: close + .18,
      low: close - .2,
      close,
    };
  }),
}));

test("template library groups frozen and custom templates and links stocks into market context", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  let custom: Record<string, unknown>[] = [];
  await page.route("**/api/templates**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const suffix = url.pathname.replace("/api/templates", "").replace(/^\//, "");
    const method = request.method();

    if (!suffix && method === "GET") {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [...frozen.map(({ bars: _bars, ...item }) => item), ...custom] }) });
      return;
    }
    if (!suffix && method === "POST") {
      const input = request.postDataJSON();
      const created = {
        id: "custom_test",
        name: input.name,
        label: input.name,
        source: "custom",
        read_only: false,
        source_ts_code: input.source_ts_code,
        start_date: input.start_date,
        end_date: input.end_date,
        window_bars: 40,
        bars: frozen[0].bars.slice(0, 40),
      };
      custom = [created];
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(created) });
      return;
    }
    const [id, resource] = suffix.split("/");
    const definition = [...frozen, ...custom].find(item => item.id === id);
    if (resource === "stocks") {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ template: definition, items: stockItems, total_eligible: 4321 }) });
      return;
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(definition) });
  });

  await page.goto("/templates");
  await expect(page.getByRole("heading", { name: "模板库", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "冻结四模板" })).toBeVisible();
  await expect(page.locator("a[href*='/market?code=000001&template=fresh_breakout']")).toBeVisible();
  const miniKlineBox = await page.getByRole("img", { name: /候选窗口真实前复权 K 线/ }).first().boundingBox();
  expect(miniKlineBox?.width || 0).toBeGreaterThanOrEqual(150);
  await expect(page.getByText("4321 只")).toBeVisible();
  await expect(page.getByRole("link", { name: "新建模板" })).toHaveAttribute("href", "/templates/new");
  await expect(page.getByLabel("模板名称")).toHaveCount(0);
});

test("market uses template URL state and dynamic template stock list", async ({ page }) => {
  await page.route("**/api/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/templates") {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: frozen.map(({ bars: _bars, ...item }) => item) }) });
      return;
    }
    if (url.pathname.match(/^\/api\/templates\/[^/]+\/stocks$/)) {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ template: frozen[0], items: stockItems, total_eligible: stockItems.length }) });
      return;
    }
    if (url.pathname.match(/^\/api\/templates\/[^/]+$/)) {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(frozen[0]) });
      return;
    }
    if (url.pathname.startsWith("/api/stock/")) {
      const code = url.pathname.split("/").at(-1)!;
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ ts_code: `${code}.SZ`, name: `模板股票${Number(code)}`, close: 12, pct_chg: 1, as_of: { quote: "20260729" } }) });
      return;
    }
    if (url.pathname.startsWith("/api/bars/")) {
      const bars = Array.from({ length: 90 }, (_, index) => ({
        time: `2026-01-${String(index % 28 + 1).padStart(2, "0")}`,
        trade_date: `202601${String(index % 28 + 1).padStart(2, "0")}`,
        open: 10 + index * .02,
        high: 10.4 + index * .02,
        low: 9.8 + index * .02,
        close: 10.2 + index * .02,
        volume: 1000,
      }));
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ bars, period: "1d", as_of: { daily: "20260729" }, warnings: [], timings: {}, cache_hit: false, range: {} }) });
      return;
    }
    if (url.pathname === "/api/state") {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ viewed: [], saved: [], pending: [], watchlist: [], history: {} }) });
      return;
    }
    await route.fulfill({ contentType: "application/json", body: "{}" });
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/market?code=000001&template=fresh_breakout");
  await expect(page.getByRole("button", { name: "模板", exact: true })).toHaveClass(/active/);
  await expect(page.getByTestId("template-group-select")).toHaveValue("fresh_breakout");
  await expect(page.getByTestId("template-stock-list").getByRole("button")).toHaveCount(30);
  await expect(page.getByText("模板与当前窗口")).toBeVisible();
  const drawer = page.locator(".market-rightbar");
  await expect.poll(async () => {
    const box = await drawer.boundingBox();
    return box ? box.x : -1;
  }).toBeGreaterThanOrEqual(0);
  await expect.poll(async () => {
    const box = await drawer.boundingBox();
    return box ? box.x + box.width : Number.POSITIVE_INFINITY;
  }).toBeLessThanOrEqual(390);
  await page.getByTestId("template-stock-list").getByRole("button").first().click();
  await expect(page.getByRole("img", { name: /模板真实前复权 K 线/ })).toBeVisible();
  await expect(page.getByRole("img", { name: /候选窗口真实前复权 K 线/ })).toBeVisible();
  await expect(page.getByText(/不使用未来表现作验证/)).toBeVisible();
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(drawer).not.toBeVisible();
  await expect(page.getByRole("link", { name: /保存.*模板/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "收起行情页顶部" })).toBeVisible();
  await page.getByRole("button", { name: "收起行情页顶部" }).click();
  await expect(page.locator(".market-shell")).toHaveClass(/header-compact/);
  await expect(page.getByRole("button", { name: "展开行情页顶部" })).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await expect(page).toHaveURL(/code=000002.*template=fresh_breakout/);
});

test("new template page uses real bars and saves a valid trading-day brush window", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  let savedName = "";
  let savedStart = "";
  let savedEnd = "";
  await page.route("**/api/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/search") {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ results: [{ ts_code: "000001.SZ", symbol: "000001", name: "平安银行", industry_name: "银行", close: 10, pct_chg: 0 }] }) });
      return;
    }
    if (url.pathname.startsWith("/api/bars/")) {
      const bars = Array.from({ length: 300 }, (_, index) => {
        const day = new Date(Date.UTC(2025, 0, 2 + index));
        const tradeDate = day.toISOString().slice(0, 10).replaceAll("-", "");
        const close = 10 + index * .02 + Math.sin(index / 7) * .25;
        return { time: day.toISOString().slice(0, 10), trade_date: tradeDate, open: close - .08, high: close + .2, low: close - .18, close, volume: 1000 };
      });
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ bars, period: "1d", as_of: { daily: "20260729" }, warnings: [], timings: {}, cache_hit: false, range: {} }) });
      return;
    }
    if (url.pathname === "/api/templates" && request.method() === "POST") {
      const input = request.postDataJSON() as Record<string, unknown>;
      savedName = String(input.name || "");
      savedStart = String(input.start_date || "");
      savedEnd = String(input.end_date || "");
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ id: "custom_brush", name: savedName, source: "custom", source_ts_code: "000001.SZ", start_date: savedStart, end_date: savedEnd, window_bars: 60, bars: [] }) });
      return;
    }
    if (url.pathname === "/api/templates") {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: frozen.map(({ bars: _bars, ...item }) => item) }) });
      return;
    }
    if (url.pathname.match(/^\/api\/templates\/[^/]+\/stocks$/)) {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ template: frozen[0], items: stockItems, total_eligible: stockItems.length }) });
      return;
    }
    if (url.pathname.match(/^\/api\/templates\/[^/]+$/)) {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(frozen[0]) });
      return;
    }
    await route.fulfill({ contentType: "application/json", body: "{}" });
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/templates/new");
  await expect.poll(() => pageErrors).toEqual([]);
  await page.waitForTimeout(500);
  const searchResponse = page.waitForResponse(response => new URL(response.url()).pathname === "/api/search");
  await page.getByLabel("搜索股票").fill("平安");
  await searchResponse;
  await page.getByRole("button", { name: /平安银行/ }).click();
  await expect(page.getByText("窗口有效：60 个实际交易日")).toBeVisible();
  await expect(page.getByRole("img", { name: /完整前复权 K 线/ })).toBeVisible();
  await expect(page.getByRole("img", { name: /选中模板窗口局部真实前复权 K 线/ })).toBeVisible();
  const fullChart = page.getByRole("img", { name: /完整前复权 K 线/ });
  const fullChartBox = await fullChart.boundingBox();
  if (!fullChartBox) throw new Error("完整 K 线图未渲染");
  const startBoundaryX = fullChartBox.x + fullChartBox.width * (240.5 / 300);
  const boundaryY = fullChartBox.y + fullChartBox.height / 2;
  await page.mouse.move(startBoundaryX + 18, boundaryY);
  await page.mouse.down();
  await page.mouse.move(startBoundaryX + 34, boundaryY);
  await page.mouse.up();
  await expect(page.getByText(/窗口有效：(?!60\b)\d+ 个实际交易日/)).toBeVisible();
  const mobileGeometry = await page.evaluate(() => {
    const sidebar = document.querySelector(".app-sidebar")?.getBoundingClientRect();
    return { scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth, sidebarTop: sidebar?.top || 0 };
  });
  expect(mobileGeometry.scrollWidth).toBeLessThanOrEqual(mobileGeometry.clientWidth);
  expect(mobileGeometry.sidebarTop).toBeGreaterThanOrEqual(770);
  const countBeforeKeyboard = Number((await page.getByText(/窗口有效：\d+ 个实际交易日/).textContent())?.match(/\d+/)?.[0]);
  await page.getByRole("slider", { name: "模板窗口开始边界" }).press("Shift+ArrowLeft");
  await expect(page.getByText(`窗口有效：${countBeforeKeyboard + 5} 个实际交易日`)).toBeVisible();
  await page.getByLabel("模板名称").fill("真实窗口测试");
  await page.getByRole("button", { name: "保存模板" }).click();
  await expect.poll(() => savedName).toBe("真实窗口测试");
  expect(savedStart).toMatch(/^\d{8}$/);
  expect(savedEnd).toMatch(/^\d{8}$/);
});
