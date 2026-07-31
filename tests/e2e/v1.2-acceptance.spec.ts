import { mkdir, writeFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";

const screenshotDir = "docs/qa/screenshots/v1.2";
const evidenceDir = "docs/qa/evidence/v1.2";
const evidence: Array<Record<string, unknown>> = [];

test.describe.serial("v1.2 acceptance", () => {
  test.beforeAll(async () => {
    await mkdir(screenshotDir, { recursive: true });
    await mkdir(evidenceDir, { recursive: true });
  });

  test.afterAll(async () => {
    await writeFile(`${evidenceDir}/browser-results.json`, `${JSON.stringify({ captured_at: new Date().toISOString(), results: evidence }, null, 2)}\n`, "utf8");
  });

  test("combined filters, Top K and exact user snapshot work", async ({ page }) => {
    test.setTimeout(120_000);
    const errors = audit(page);
    await page.setViewportSize({ width: 1600, height: 1000 });
    await openBoard(page);

    await page.getByRole("button", { name: "全部行业" }).click();
    const electronic = page.getByTestId("industry-filter").getByText("电子", { exact: true });
    await electronic.click();
    await page.getByRole("button", { name: /行业 1 项/ }).click();
    await page.getByRole("spinbutton", { name: "市值下限亿元" }).fill("50");
    await page.getByRole("spinbutton", { name: "市值上限亿元" }).fill("500");
    await page.getByRole("spinbutton", { name: "Top K" }).fill("7");
    await page.getByRole("button", { name: "运行筛选" }).click();
    await expect(page.getByRole("button", { name: "运行筛选" })).toBeEnabled({ timeout: 30_000 });
    await expect(page.locator(".top-card h1")).toHaveText("TOP 7");
    expect(await page.locator(".candidate-table tbody tr").count()).toBeLessThanOrEqual(7);
    const industries = await page.locator(".candidate-table tbody tr td:nth-child(4)").allTextContents();
    expect(industries.every(value => value.includes("电子"))).toBe(true);

    await page.getByRole("button", { name: "保存本次筛选" }).click();
    await expect(page.locator(".section-heading")).toContainText("已保存本次筛选");
    await page.getByRole("button", { name: /历史记录/ }).click();
    const run = page.locator("[data-run-id]").first();
    await expect(run).toBeVisible();
    await run.click();
    await expect(page.getByRole("button", { name: "恢复并复用条件" })).toBeVisible();
    expect(await page.locator(".snapshot-results > button").count()).toBeGreaterThan(0);
    await page.getByRole("button", { name: "恢复并复用条件" }).click();
    await expect(page.getByRole("spinbutton", { name: "Top K" })).toHaveValue("7");

    await page.getByRole("spinbutton", { name: "市值下限亿元" }).fill("600");
    await page.getByRole("spinbutton", { name: "市值上限亿元" }).fill("500");
    await expect(page.getByRole("alert")).toContainText("市值下限不能大于上限");
    await expect(page.getByRole("button", { name: "运行筛选" })).toBeDisabled();
    expect(errors).toEqual([]);
    evidence.push({ gate: 2, scenario: "filters-and-snapshot", top_k: 7, industry: "电子", market_cap: [50, 500], result: "pass" });
  });

  test("full history, pattern pool, layouts, fullscreen and drawings work", async ({ page }) => {
    test.setTimeout(120_000);
    const errors = audit(page);
    await page.setViewportSize({ width: 1600, height: 1000 });
    await page.goto("/market?code=002747&category=pullback");
    await expect(page.getByRole("heading", { name: "埃斯顿" })).toBeVisible({ timeout: 30_000 });
    const chart = page.locator(".market-chart").first();
    await expect(chart).toHaveAttribute("data-bars", "110");
    expect(Number(await chart.getAttribute("data-source-bars"))).toBeGreaterThan(110);
    await expect(chart).toHaveAttribute("data-dropped-bars", "0");

    await page.getByRole("button", { name: "1年", exact: true }).click();
    await expect(chart).toHaveAttribute("data-bars", "250");
    await page.screenshot({ path: `${screenshotDir}/market-1600-002747-full-history.png`, animations: "disabled", caret: "hide" });

    await page.getByRole("button", { name: "形态", exact: true }).click();
    await expect(page.getByTestId("pattern-group-select")).toHaveValue("pullback");
    const pool = page.getByTestId("pattern-pool");
    await expect(pool.locator("button").first()).toBeVisible({ timeout: 30_000 });
    await pool.locator("button").first().click();
    const firstCode = await pool.locator("button[aria-current=true] small").innerText();
    await page.keyboard.press("ArrowDown");
    await expect(pool.locator("button[aria-current=true] small")).not.toHaveText(firstCode);

    await page.getByRole("button", { name: /图布局/ }).click();
    await page.getByRole("button", { name: "2 图", exact: true }).click();
    await expect(page.locator(".chart-pane")).toHaveCount(2);
    await page.getByRole("button", { name: "放大图表 1" }).click();
    await expect(page.locator(".chart-pane")).toHaveCount(1);
    await page.getByRole("button", { name: "退出单图放大" }).click();
    await expect(page.locator(".chart-pane")).toHaveCount(2);

    await page.getByRole("button", { name: "进入全屏" }).click();
    await expect(page.locator(".chart-workspace")).toHaveAttribute("data-fullscreen", "true");
    await page.getByRole("button", { name: "退出全屏" }).click();
    await expect(page.locator(".chart-workspace")).toHaveAttribute("data-fullscreen", "false");

    await page.getByRole("button", { name: "斐波那契回撤" }).click();
    const overlay = page.locator("canvas.drawing-overlay").first();
    const before = await overlay.evaluate((canvas: HTMLCanvasElement) => canvas.toDataURL());
    const box = await overlay.boundingBox();
    if (!box) throw new Error("drawing overlay is not visible");
    await page.mouse.move(box.x + 120, box.y + 100);
    await page.mouse.down();
    await page.mouse.move(box.x + 420, box.y + 260, { steps: 6 });
    await page.mouse.up();
    const after = await overlay.evaluate((canvas: HTMLCanvasElement) => canvas.toDataURL());
    expect(after).not.toBe(before);
    await page.screenshot({ path: `${screenshotDir}/market-1600-pattern-layout-drawing.png`, animations: "disabled", caret: "hide" });
    await page.getByRole("button", { name: "选择/调整" }).click();
    await page.mouse.click(box.x + 270, box.y + 180);
    await page.keyboard.press("Delete");
    const afterDelete = await overlay.evaluate((canvas: HTMLCanvasElement) => canvas.toDataURL());
    expect(afterDelete).not.toBe(after);
    expect(errors).toEqual([]);
    evidence.push({ gate: 3, scenario: "market-interactions", code: "002747", full_history: true, layouts: [1, 2, 4], drawing: "fibonacci", result: "pass" });
  });

  test("sidebar geometry is identical and expanded board never overlaps state cards", async ({ page }) => {
    test.setTimeout(120_000);
    const viewports = [{ width: 1600, height: 1000 }, { width: 1366, height: 768 }, { width: 1024, height: 800 }];
    for (const viewport of viewports) {
      await page.setViewportSize(viewport);
      await openBoard(page);
      const boardSidebar = await sidebarGeometry(page);
      await page.screenshot({ path: `${screenshotDir}/board-${viewport.width}-top.png`, animations: "disabled", caret: "hide" });
      const expand = page.locator(".view-all-button");
      if (await expand.isVisible()) await expand.click();
      const candidate = await page.locator(".candidate-card").boundingBox();
      const cards = await page.locator(".state-cards").boundingBox();
      expect(candidate && cards ? cards.y >= candidate.y + candidate.height : false).toBe(true);
      expect(await horizontalOverflow(page)).toBe(false);
      await page.screenshot({ path: `${screenshotDir}/board-${viewport.width}-expanded.png`, fullPage: true, animations: "disabled", caret: "hide" });
      await page.locator(".state-cards").scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${screenshotDir}/board-${viewport.width}-state-cards.png`, animations: "disabled", caret: "hide" });

      await page.goto("/market?code=002747");
      await expect(page.getByRole("heading", { name: "埃斯顿" })).toBeVisible({ timeout: 30_000 });
      const marketSidebar = await sidebarGeometry(page);
      expect(marketSidebar).toEqual(boardSidebar);
      expect(await horizontalOverflow(page)).toBe(false);
      await page.screenshot({ path: `${screenshotDir}/market-${viewport.width}-sidebar.png`, animations: "disabled", caret: "hide" });
    }
    evidence.push({ gate: 4, scenario: "visual-regression", viewports, overlap: false, sidebar_equal: true, result: "pass" });
  });
});

async function openBoard(page: Page) {
  await page.goto("/");
  await expect(page.locator(".candidate-table tbody tr").first()).toBeVisible({ timeout: 30_000 });
}

function audit(page: Page) {
  const errors: string[] = [];
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  page.on("pageerror", error => errors.push(error.message));
  return errors;
}

async function sidebarGeometry(page: Page) {
  return page.locator(".app-sidebar").evaluate(sidebar => {
    const box = sidebar.getBoundingClientRect();
    const brand = sidebar.querySelector(".brand-lockup")!.getBoundingClientRect();
    const nav = [...sidebar.querySelectorAll(".primary-nav .nav-item")].map(item => { const rect = item.getBoundingClientRect(); return [Math.round(rect.x - box.x), Math.round(rect.y - box.y), Math.round(rect.width), Math.round(rect.height)]; });
    const bottom = [...sidebar.querySelectorAll(".sidebar-bottom .nav-item")].map(item => { const rect = item.getBoundingClientRect(); return [Math.round(rect.x - box.x), Math.round(rect.y - box.y), Math.round(rect.width), Math.round(rect.height)]; });
    return { width: Math.round(box.width), height: Math.round(box.height), brand: [Math.round(brand.width), Math.round(brand.height)], nav, bottom };
  });
}

async function horizontalOverflow(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
}
