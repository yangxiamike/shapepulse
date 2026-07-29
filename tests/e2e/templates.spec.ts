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
  bars: Array.from({ length: Number(windowBars) }, (_, index) => ({
    trade_date: `2025${String(Math.floor(index / 20) + 1).padStart(2, "0")}${String(index % 20 + 1).padStart(2, "0")}`,
    close: 10 + index * .05 + Math.sin(index / 4) * .2,
  })),
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
}));

test("template library groups frozen and custom templates and links stocks into market context", async ({ page }) => {
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
  await expect(page.getByText("4321 只")).toBeVisible();

  await page.getByLabel("模板名称").fill("我的测试模板");
  await page.getByLabel("股票代码").fill("000001.SZ");
  await page.getByLabel("开始日期").fill("2025-01-02");
  await page.getByLabel("结束日期").fill("2025-03-06");
  await page.getByRole("button", { name: "保存并分析" }).click();
  await expect(page.getByText("我的测试模板", { exact: true }).first()).toBeVisible();
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
  const comparison = page.locator(".template-curve-comparison");
  await expect(comparison).toHaveAttribute("data-transform", "qfq-log-close-independent-z");
  const curveStats = await comparison.evaluate(element => ({
    templateMean: Number(element.getAttribute("data-template-mean")),
    templateStd: Number(element.getAttribute("data-template-std")),
    candidateMean: Number(element.getAttribute("data-candidate-mean")),
    candidateStd: Number(element.getAttribute("data-candidate-std")),
  }));
  expect(Math.abs(curveStats.templateMean)).toBeLessThanOrEqual(.000001);
  expect(curveStats.templateStd).toBeCloseTo(1, 6);
  expect(Math.abs(curveStats.candidateMean)).toBeLessThanOrEqual(.000001);
  expect(curveStats.candidateStd).toBeCloseTo(1, 6);
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(drawer).not.toBeVisible();
  await expect(page.getByRole("link", { name: "保存当前区间为模板" })).toHaveAttribute("href", /\/templates\?source_ts_code=/);
  await page.keyboard.press("ArrowDown");
  await expect(page).toHaveURL(/code=000002.*template=fresh_breakout/);
});
