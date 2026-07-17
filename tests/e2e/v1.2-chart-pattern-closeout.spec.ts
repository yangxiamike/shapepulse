import { mkdir, writeFile } from "node:fs/promises";
import { expect, test, type Locator, type Page } from "@playwright/test";

const screenshotDir = "docs/qa/screenshots/v1.2-final";
const evidenceDir = "docs/qa/evidence/v1.2-final";
const results: Array<Record<string, unknown>> = [];

async function box(locator: Locator) {
  const value = await locator.boundingBox();
  if (!value) throw new Error("expected visible geometry");
  return value;
}

async function numberAttribute(locator: Locator, name: string) {
  return Number(await locator.getAttribute(name));
}

async function chartState(chart: Locator) {
  return {
    from: await numberAttribute(chart, "data-visible-from"),
    to: await numberAttribute(chart, "data-visible-to"),
    rightPadding: await numberAttribute(chart, "data-visible-right-padding"),
    rightGap: await numberAttribute(chart, "data-latest-bar-right-gap"),
    priceFrom: await numberAttribute(chart, "data-price-from"),
    priceTo: await numberAttribute(chart, "data-price-to"),
    priceSpan: await numberAttribute(chart, "data-price-span"),
    priceMode: await chart.getAttribute("data-price-scale-mode"),
  };
}

async function openPriceMenu(page: Page, chart: Locator, yRatio = 0.5) {
  const bounds = await box(chart);
  await page.mouse.click(bounds.x + bounds.width - 10, bounds.y + bounds.height * yRatio, { button: "right" });
  const menu = page.getByRole("menu", { name: "价格刻度设置" });
  await expect(menu).toBeVisible();
  return menu;
}

async function drag(page: Page, from: { x: number; y: number }, to: { x: number; y: number }) {
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(to.x, to.y, { steps: 12 });
  await page.mouse.up();
}

test.describe.serial("V1.2 final closeout chart and pattern fixes", () => {
  test.beforeAll(async () => {
    await mkdir(screenshotDir, { recursive: true });
    await mkdir(evidenceDir, { recursive: true });
  });

  test.afterAll(async () => {
    await writeFile(
      `${evidenceDir}/chart-pattern-results.json`,
      `${JSON.stringify({ captured_at: new Date().toISOString(), results }, null, 2)}\n`,
      "utf8",
    );
  });

  test("main chart resets per stock and price-axis modes change real geometry", async ({ page }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto("/market?code=000001&category=breakout");
    await expect(page.getByRole("heading", { name: "平安银行" })).toBeVisible({ timeout: 30_000 });
    const chart = page.locator(".market-chart").first();
    await expect(chart).toHaveAttribute("data-bars", "110");
    await expect(chart).toHaveAttribute("data-right-padding-bars", "10");
    await expect.poll(() => numberAttribute(chart, "data-visible-right-padding")).toBeGreaterThan(9.5);
    await expect.poll(() => numberAttribute(chart, "data-price-span")).toBeGreaterThan(0);
    const initial = await chartState(chart);
    expect(initial.rightGap).toBeGreaterThan(60);

    await page.getByRole("button", { name: "1年", exact: true }).click();
    await expect(chart).toHaveAttribute("data-bars", "250");
    let menu = await openPriceMenu(page, chart);
    await menu.getByRole("menuitemradio", { name: /自动适配/ }).click();
    await expect(page.getByRole("button", { name: "6个月", exact: true })).toHaveClass(/active/);
    await expect(chart).toHaveAttribute("data-bars", "110");

    menu = await openPriceMenu(page, chart);
    await menu.getByRole("menuitemradio", { name: /自由价格比例/ }).click();
    await expect(chart).toHaveAttribute("data-price-scale-mode", "free");
    const chartBox = await box(chart);
    const beforeFreeScale = await chartState(chart);
    await drag(
      page,
      { x: chartBox.x + chartBox.width - 9, y: chartBox.y + chartBox.height * 0.42 },
      { x: chartBox.x + chartBox.width - 9, y: chartBox.y + chartBox.height * 0.62 },
    );
    await expect.poll(() => numberAttribute(chart, "data-price-span")).not.toBeCloseTo(beforeFreeScale.priceSpan, 2);
    const freelyScaled = await chartState(chart);

    menu = await openPriceMenu(page, chart);
    await menu.getByRole("menuitemradio", { name: /锁定价格比例/ }).click();
    const lockedBefore = await chartState(chart);
    await drag(
      page,
      { x: chartBox.x + chartBox.width - 9, y: chartBox.y + chartBox.height * 0.42 },
      { x: chartBox.x + chartBox.width - 9, y: chartBox.y + chartBox.height * 0.62 },
    );
    const lockedAfterAxisDrag = await chartState(chart);
    expect(Math.abs(lockedAfterAxisDrag.priceSpan - lockedBefore.priceSpan)).toBeLessThan(0.01);
    await drag(
      page,
      { x: chartBox.x + chartBox.width * 0.48, y: chartBox.y + chartBox.height * 0.5 },
      { x: chartBox.x + chartBox.width * 0.68, y: chartBox.y + chartBox.height * 0.5 },
    );
    await expect.poll(() => numberAttribute(chart, "data-visible-from")).not.toBeCloseTo(lockedBefore.from, 1);

    menu = await openPriceMenu(page, chart);
    await menu.getByRole("menuitemradio", { name: /自动适配/ }).click();
    await expect(chart).toHaveAttribute("data-price-scale-mode", "auto");
    await expect.poll(() => numberAttribute(chart, "data-visible-right-padding")).toBeGreaterThan(9.5);
    const reset = await chartState(chart);
    expect(Math.abs(reset.priceSpan - initial.priceSpan)).toBeLessThan(initial.priceSpan * 0.08);

    menu = await openPriceMenu(page, chart, 0.96);
    const menuBox = await box(menu);
    expect(menuBox.x).toBeGreaterThanOrEqual(0);
    expect(menuBox.y).toBeGreaterThanOrEqual(0);
    expect(menuBox.x + menuBox.width).toBeLessThanOrEqual(1920);
    expect(menuBox.y + menuBox.height).toBeLessThanOrEqual(1080);
    await page.keyboard.press("Escape");
    await expect(menu).toBeHidden();
    menu = await openPriceMenu(page, chart);
    await page.mouse.click(300, 120);
    await expect(menu).toBeHidden();

    menu = await openPriceMenu(page, chart);
    await page.screenshot({ path: `${screenshotDir}/market-price-scale-context-menu.png`, animations: "disabled", caret: "hide" });
    await menu.getByRole("menuitemradio", { name: /自由价格比例/ }).click();
    await drag(
      page,
      { x: chartBox.x + chartBox.width - 9, y: chartBox.y + chartBox.height * 0.45 },
      { x: chartBox.x + chartBox.width - 9, y: chartBox.y + chartBox.height * 0.7 },
    );
    await drag(
      page,
      { x: chartBox.x + chartBox.width * 0.45, y: chartBox.y + chartBox.height * 0.5 },
      { x: chartBox.x + chartBox.width * 0.7, y: chartBox.y + chartBox.height * 0.5 },
    );

    const search = page.getByRole("textbox", { name: "搜索股票" });
    await search.fill("002747");
    await expect(page.locator(".search-results button").first()).toBeVisible();
    await page.locator(".search-results button").first().click();
    await expect(page.getByRole("heading", { name: "埃斯顿" })).toBeVisible({ timeout: 30_000 });
    const switchedChart = page.locator(".market-chart").first();
    await expect(switchedChart).toHaveAttribute("data-bars", "110");
    await expect(switchedChart).toHaveAttribute("data-right-padding-bars", "10");
    await expect(switchedChart).toHaveAttribute("data-price-scale-mode", "auto");
    await expect.poll(() => numberAttribute(switchedChart, "data-visible-right-padding")).toBeGreaterThan(9.5);
    await expect.poll(() => numberAttribute(switchedChart, "data-price-span")).toBeGreaterThan(0);
    const switched = await chartState(switchedChart);
    expect(switched.priceSpan).not.toBeCloseTo(freelyScaled.priceSpan, 1);
    await expect(page.getByRole("button", { name: "日K", exact: true })).toHaveClass(/active/);
    await expect(page.getByRole("button", { name: "6个月", exact: true })).toHaveClass(/active/);

    await page.screenshot({ path: `${screenshotDir}/market-chart-price-menu-and-stock-reset.png`, animations: "disabled", caret: "hide" });
    results.push({ gate: "chart-default-and-price-scale", initial, freely_scaled: freelyScaled, locked: lockedAfterAxisDrag, reset, switched, result: "pass" });
  });

  test("current-stock facts, draggable split and list navigation follow the new semantics", async ({ page }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width: 1600, height: 1000 });
    await page.goto("/market?code=000001&category=breakout");
    await expect(page.getByRole("heading", { name: "平安银行" })).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "形态", exact: true }).click();
    await expect(page.getByRole("heading", { name: "三类形态均不符合" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("按最新本地数据计算，三类形态均不符合", { exact: true })).toBeVisible();
    await expect(page.locator(".pattern-facts").getByText("行情 2026.07.16", { exact: true })).toBeVisible();
    await expect(page.getByText("尚未计算", { exact: true })).toHaveCount(0);

    const splitter = page.getByTestId("pattern-splitter");
    const poolSection = page.locator(".pattern-pool-section");
    const factsSection = page.locator(".pattern-facts-section");
    const splitterBox = await box(splitter);
    const beforePool = (await box(poolSection)).height;
    const beforeFacts = (await box(factsSection)).height;
    await drag(
      page,
      { x: splitterBox.x + splitterBox.width / 2, y: splitterBox.y + splitterBox.height / 2 },
      { x: splitterBox.x + splitterBox.width / 2, y: splitterBox.y - 90 },
    );
    const afterUpPool = (await box(poolSection)).height;
    const afterUpFacts = (await box(factsSection)).height;
    expect(afterUpPool).toBeLessThan(beforePool - 60);
    expect(afterUpFacts).toBeGreaterThan(beforeFacts + 60);
    const movedSplitter = await box(splitter);
    await drag(
      page,
      { x: movedSplitter.x + movedSplitter.width / 2, y: movedSplitter.y + movedSplitter.height / 2 },
      { x: movedSplitter.x + movedSplitter.width / 2, y: movedSplitter.y + 150 },
    );
    expect((await box(poolSection)).height).toBeGreaterThan(afterUpPool + 100);
    await page.screenshot({ path: `${screenshotDir}/market-pingan-current-pattern-facts.png`, animations: "disabled", caret: "hide" });

    const pool = page.getByTestId("pattern-pool");
    await expect(pool.locator("button").first()).toBeVisible({ timeout: 60_000 });
    await pool.locator("button").first().click();
    await expect(pool.locator("button[aria-current=true]")).toBeVisible();
    await pool.evaluate(element => { element.scrollTop = 0; });
    const activeBeforeWheel = await pool.locator("button[aria-current=true]").textContent();
    const poolBox = await box(pool);
    await page.mouse.move(poolBox.x + poolBox.width / 2, poolBox.y + poolBox.height * 0.75);
    await page.mouse.wheel(0, 450);
    await expect.poll(() => pool.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
    expect(await pool.locator("button[aria-current=true]").textContent()).toBe(activeBeforeWheel);

    await page.keyboard.press("ArrowDown");
    await expect.poll(() => pool.locator("button[aria-current=true]").textContent()).not.toBe(activeBeforeWheel);
    const active = pool.locator("button[aria-current=true]");
    expect(await active.evaluate(button => {
      const item = button.getBoundingClientRect();
      const parent = button.parentElement!.getBoundingClientRect();
      return item.top >= parent.top - 1 && item.bottom <= parent.bottom + 1;
    })).toBe(true);
    await expect(page.getByRole("button", { name: "日K", exact: true })).toHaveClass(/active/);
    await expect(page.getByRole("button", { name: "6个月", exact: true })).toHaveClass(/active/);

    await page.screenshot({ path: `${screenshotDir}/market-pattern-current-facts-and-splitter.png`, animations: "disabled", caret: "hide" });
    results.push({
      gate: "pattern-current-facts-and-navigation",
      snapshot: "20260716",
      ping_an_bank: "calculated_no_match",
      splitter: { before_pool: beforePool, after_up_pool: afterUpPool, before_facts: beforeFacts, after_up_facts: afterUpFacts },
      wheel: "scroll_only",
      keyboard: "stock_switch",
      result: "pass",
    });
  });

  test("board stays three months and narrow large-font layout does not clip", async ({ page }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width: 1600, height: 1000 });
    await page.goto("/");
    const detail = page.locator(".detail-chart .market-chart");
    await expect(detail).toBeVisible({ timeout: 60_000 });
    await expect(detail).toHaveAttribute("data-bars", "66");
    await expect(detail).toHaveAttribute("data-right-padding-bars", "8");
    await expect.poll(() => numberAttribute(detail, "data-visible-right-padding")).toBeGreaterThan(7.5);

    await page.setViewportSize({ width: 1024, height: 800 });
    await page.getByRole("button", { name: "大字体" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-font-size", "large");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    await page.goto("/market?code=000001&category=breakout");
    await expect.poll(() => numberAttribute(page.locator(".market-chart").first(), "data-price-span")).toBeGreaterThan(0);
    await page.getByRole("button", { name: "打开右侧面板" }).click();
    await expect(page.locator(".market-rightbar")).toHaveClass(/open/);
    await page.getByRole("button", { name: "形态", exact: true }).click();
    await expect(page.getByTestId("pattern-splitter")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    await page.screenshot({ path: `${screenshotDir}/market-1024-large-pattern-layout.png`, animations: "disabled", caret: "hide" });
    results.push({ gate: "board-3m-and-responsive", board_bars: 66, board_padding: 8, viewport: [1024, 800], font: "large", overflow: false, result: "pass" });
  });
});
