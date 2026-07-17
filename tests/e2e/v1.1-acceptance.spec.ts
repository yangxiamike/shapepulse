import { mkdir, writeFile } from "node:fs/promises";
import { expect, test, type Locator, type Page } from "@playwright/test";

const screenshotDir = "docs/qa/screenshots/v1.1";
const evidenceDir = "docs/qa/evidence/v1.1";
const browserEvidence: Array<Record<string, unknown>> = [];

test.describe.serial("v1.1 Chrome acceptance", () => {
  test.beforeAll(async () => {
    await mkdir(screenshotDir, { recursive: true });
    await mkdir(evidenceDir, { recursive: true });
  });

  test.afterAll(async () => {
    await writeFile(
      `${evidenceDir}/browser-results.json`,
      `${JSON.stringify({ captured_at: new Date().toISOString(), results: browserEvidence }, null, 2)}\n`,
      "utf8",
    );
  });

  test("three responsive viewports stay readable and keep local-only requests", async ({ page }) => {
    test.setTimeout(120_000);
    const audit = attachAudit(page);
    for (const viewport of [
      { width: 1600, height: 1000 },
      { width: 1280, height: 900 },
      { width: 1024, height: 800 },
    ]) {
      const size = `${viewport.width}x${viewport.height}`;
      await page.setViewportSize(viewport);
      await openBoard(page);
      expect(await hasPageOverflow(page)).toBe(false);
      if (viewport.width === 1600) {
        const chart = await page.locator(".detail-chart").boundingBox();
        expect(chart?.width || 0).toBeGreaterThanOrEqual(420);
        expect(chart?.height || 0).toBeGreaterThanOrEqual(280);
      }
      await expect(page.locator(".detail-chart .market-chart")).toHaveAttribute("data-bars", "110");
      await settleForScreenshot(page, page.locator(".detail-chart .market-chart"));
      await captureScreenshot(page, { path: `${screenshotDir}/board-${viewport.width}-overview.png`, fullPage: viewport.width < 1440, animations: "disabled", caret: "hide" });

      await page.goto("/market?code=002728");
      await expect(page.getByRole("heading", { name: "特一药业" })).toBeVisible();
      await expect(page.locator(".market-chart")).toHaveAttribute("data-bars", "110");
      expect(await hasPageOverflow(page)).toBe(false);
      await settleForScreenshot(page, page.locator(".market-chart"));
      await captureScreenshot(page, { path: `${screenshotDir}/market-${viewport.width}-002728-daily.png`, animations: "disabled", caret: "hide" });
      if (viewport.width === 1024) {
        await page.getByRole("button", { name: "打开右侧面板" }).click();
        await page.getByRole("button", { name: "形态", exact: true }).click();
        await expect(page.getByTestId("pattern-group-select")).toBeVisible();
        await expect(page.getByRole("heading", { name: /特一药业 · 形态事实|尚未计算|已计算但无匹配/ })).toBeVisible();
        await settleForScreenshot(page, page.locator(".market-rightbar"));
        await captureScreenshot(page, { path: `${screenshotDir}/market-1024-right-drawer.png`, animations: "disabled", caret: "hide" });
      }
      browserEvidence.push({ scenario: "responsive", viewport: size, overflow: false, result: "pass" });
    }
    expect(audit.consoleErrors).toEqual([]);
    expect(audit.externalRequests).toEqual([]);
  });

  test("five visual samples from each independent category remain internally consistent", async ({ page }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width: 1600, height: 1000 });
    const audit = attachAudit(page);
    await openBoard(page);
    const categories = [
      { label: "突破启动", slug: "breakout" },
      { label: "上升趋势回调", slug: "pullback" },
      { label: "区间下沿反弹", slug: "range-bounce" },
    ];
    for (const category of categories) {
      const card = page.getByRole("button", { name: new RegExp(category.label) }).first();
      await card.focus();
      await page.keyboard.press("Enter");
      await expect(page.getByRole("heading", { name: category.label })).toBeVisible();
      const expand = page.getByRole("button", { name: /查看全部/ });
      if (await expand.isVisible()) await expand.click();
      const rows = page.locator(".candidate-table tbody tr");
      await expect(rows).toHaveCount(50);
      for (let index = 0; index < 5; index += 1) {
        const row = rows.nth(index);
        const code = (await row.locator("td").nth(1).innerText()).trim();
        const rank = (await row.locator("td").nth(0).innerText()).trim();
        const tag = (await row.locator(".pattern-tag").innerText()).trim();
        const reason = (await row.locator("td").nth(5).innerText()).trim();
        const pct = (await row.locator("td").nth(8).innerText()).trim();
        expect(Number(rank)).toBe(index + 1);
        expect(tag).toBe(category.label);
        expect(reason.length).toBeGreaterThan(3);
        await row.click();
        await expect(page.locator(".detail-chart .market-chart")).toHaveAttribute("data-bars", "110");
        const detailPctText = await page.locator(".snapshot-price span").innerText();
        const rowPctValue = Number(pct.replace("%", ""));
        const detailPctValue = Number(detailPctText.match(/([+-]?\d+\.\d+)%/)?.[1]);
        expect(Math.abs(rowPctValue - detailPctValue)).toBeLessThanOrEqual(0.02);
        await expect(page.locator(".pattern-reading .pattern-tag")).toHaveText(category.label);
        await expect(page.locator(".pattern-reading li").first()).toBeVisible();
        await settleForScreenshot(page, page.locator(".detail-chart .market-chart"));
        const sample = String(index + 1).padStart(2, "0");
        await captureScreenshot(page, { path: `${screenshotDir}/sample-${category.slug}-${sample}-${code}.png`, animations: "disabled", caret: "hide" });
        browserEvidence.push({ scenario: "shape-sample", category: category.label, sample: index + 1, code, rank, reason, pct, result: "pass" });
      }
    }
    expect(audit.consoleErrors).toEqual([]);
    expect(audit.externalRequests).toEqual([]);
  });

  test("state, periods, drawings, disabled tools and mobile pattern panel work", async ({ page }) => {
    test.setTimeout(120_000);
    const audit = attachAudit(page);
    await page.setViewportSize({ width: 1600, height: 1000 });
    await openBoard(page);
    const saveButton = page.locator(".snapshot-title button");
    if (await saveButton.getAttribute("aria-pressed") === "true") await saveButton.click();
    await saveButton.click();
    await expect(saveButton).toHaveAttribute("aria-pressed", "true");
    await page.reload();
    await expect(page.locator(".candidate-table tbody tr").first()).toBeVisible();
    await expect(page.locator(".snapshot-title button")).toHaveAttribute("aria-pressed", "true");
    await page.locator(".snapshot-title button").click();
    await expect(page.locator(".snapshot-title button")).toHaveAttribute("aria-pressed", "false");

    await page.goto("/market?code=000001");
    await expect(page.getByRole("heading", { name: "平安银行" })).toBeVisible();
    const addWatch = page.locator(".add-watch");
    if ((await addWatch.innerText()).includes("移出")) await addWatch.click();
    await addWatch.click();
    await expect(addWatch).toContainText("移出自选");
    await page.reload();
    await expect(page.locator(".add-watch")).toContainText("移出自选");
    await page.locator(".add-watch").click();
    await expect(page.locator(".add-watch")).toContainText("添加自选");

    const counts: number[] = [];
    for (const label of ["日K", "周K", "月K", "季K", "年K"]) {
      await page.getByRole("button", { name: label, exact: true }).click();
      await page.waitForTimeout(80);
      counts.push(Number(await page.locator(".market-chart").getAttribute("data-bars")));
    }
    expect(new Set(counts).size).toBe(5);
    expect(counts[0]).toBe(110);

    await page.getByRole("button", { name: "日K", exact: true }).click();
    const overlay = page.locator("canvas.drawing-overlay");
    const before = await overlay.evaluate((canvas: HTMLCanvasElement) => canvas.toDataURL());
    await page.getByRole("button", { name: "趋势线" }).click();
    const box = await overlay.boundingBox();
    if (!box) throw new Error("drawing canvas is not visible");
    await page.mouse.move(box.x + 180, box.y + 160);
    await page.mouse.down();
    await page.mouse.move(box.x + 430, box.y + 90, { steps: 6 });
    await page.mouse.up();
    const afterLine = await overlay.evaluate((canvas: HTMLCanvasElement) => canvas.toDataURL());
    expect(afterLine).not.toBe(before);
    await page.getByRole("button", { name: "清除画线" }).click();
    const afterClear = await overlay.evaluate((canvas: HTMLCanvasElement) => canvas.toDataURL());
    expect(afterClear).toBe(before);
    for (const tool of ["水平线", "文本", "测量"]) {
      await page.getByRole("button", { name: tool }).click();
      await page.mouse.move(box.x + 220, box.y + 180);
      await page.mouse.down();
      await page.mouse.move(box.x + 380, box.y + 120, { steps: 4 });
      await page.mouse.up();
    }
    await settleForScreenshot(page, page.locator(".market-chart"));
    await captureScreenshot(page, { path: `${screenshotDir}/market-1600-drawing-tools.png`, animations: "disabled", caret: "hide" });
    await page.getByRole("button", { name: "清除画线" }).click();
    await page.getByRole("button", { name: "放大图表", exact: true }).click();
    await expect(page.locator(".range-toolbar button.active")).not.toHaveText("6个月");

    for (const label of ["分时", "5分", "指标尚未实现", "对比尚未实现", "预警尚未实现", "回放尚未实现"]) {
      const button = page.getByRole("button", { name: label, exact: false }).first();
      await expect(button).toBeDisabled();
    }
    await page.getByRole("button", { name: "形态", exact: true }).click();
    await expect(page.getByTestId("pattern-group-select")).toBeVisible();
    await expect(page.getByRole("heading", { name: /尚未计算|已计算但无匹配|形态事实/ })).toBeVisible();

    await page.setViewportSize({ width: 1024, height: 800 });
    await page.goto("/market?code=002728");
    await expect(page.getByRole("heading", { name: "特一药业" })).toBeVisible();
    await page.getByRole("button", { name: "打开右侧面板" }).click();
    await page.getByRole("button", { name: "形态", exact: true }).click();
    await expect(page.getByTestId("pattern-group-select")).toBeVisible();
    await expect(page.getByRole("heading", { name: /特一药业 · 形态事实|尚未计算|已计算但无匹配/ })).toBeVisible();
    await expect(page.getByRole("link", { name: "到选股看板查看该股记录" })).toBeVisible();
    browserEvidence.push({ scenario: "interactions", periods: counts, drawings: ["line", "horizontal", "text", "measure", "clear"], state_persistence: true, mobile_pattern_panel: true, result: "pass" });
    expect(audit.consoleErrors).toEqual([]);
    expect(audit.externalRequests).toEqual([]);
  });
});

async function openBoard(page: Page) {
  await page.goto("/");
  await expect(page.locator(".candidate-table tbody tr").first()).toBeVisible({ timeout: 20_000 });
}

async function settleForScreenshot(page: Page, target: Locator) {
  await target.scrollIntoViewIfNeeded();
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(600);
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function captureScreenshot(page: Page, options: Parameters<Page["screenshot"]>[0]) {
  try {
    await page.screenshot(options);
  } catch (error) {
    if (!(error instanceof Error) || !/unknown error, open/i.test(error.message)) throw error;
    await page.waitForTimeout(150);
    await page.screenshot(options);
  }
}

async function hasPageOverflow(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
}

function attachAudit(page: Page) {
  const consoleErrors: string[] = [];
  const externalRequests: string[] = [];
  page.on("console", message => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("request", request => {
    const url = request.url();
    if (url.startsWith("data:") || url.startsWith("blob:")) return;
    const host = new URL(url).hostname;
    if (!['localhost', '127.0.0.1', '::1'].includes(host)) externalRequests.push(url);
  });
  return { consoleErrors, externalRequests };
}
