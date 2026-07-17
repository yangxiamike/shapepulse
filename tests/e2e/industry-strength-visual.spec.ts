import { mkdir, writeFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";

const screenshotDir = "docs/qa/screenshots/industry-strength-v2.2.1";
const evidenceDir = "docs/qa/evidence/industry-strength-v2.2.1";
const results: Array<Record<string, unknown>> = [];

test.describe.serial("industry strength real-data visual acceptance", () => {
  test.beforeAll(async () => {
    await mkdir(screenshotDir, { recursive: true });
    await mkdir(evidenceDir, { recursive: true });
  });

  test.afterAll(async () => {
    await writeFile(
      `${evidenceDir}/browser-results.json`,
      `${JSON.stringify({ captured_at: new Date().toISOString(), results }, null, 2)}\n`,
      "utf8",
    );
  });

  for (const viewport of [{ width: 1600, height: 1000 }, { width: 1024, height: 800 }]) {
    test(`real 31-industry layout passes at ${viewport.width}px`, async ({ page }) => {
      test.setTimeout(90_000);
      const errors = audit(page);
      await page.setViewportSize(viewport);
      await page.goto("/industry-strength");
      await expect(page.getByRole("heading", { name: "行业强弱", exact: true })).toBeVisible({ timeout: 45_000 });
      await expect(page.locator(".heat-row-label")).toHaveCount(12, { timeout: 45_000 });
      await expect(page.locator(".industry-data-foot")).toContainText("真实行业数：31");
      await expect(page.locator(".industry-data-foot")).toContainText("采样节点：24");
      await expect(page.locator(".heat-time-axis time").first()).toContainText("最新");
      await expect(page.locator(".industry-ranking-table tbody tr")).toHaveCount(15);
      await expect(page.getByRole("listbox", { name: "行业选择器" })).toBeVisible();

      expect(await horizontalOverflow(page)).toBe(false);
      const fontSizes = await fontAudit(page);
      expect(Math.min(...Object.values(fontSizes))).toBeGreaterThanOrEqual(13);
      const sidebar = await page.locator(".app-sidebar").boundingBox();
      const main = await page.locator(".industry-main").boundingBox();
      expect(sidebar && main ? main.x >= sidebar.x + sidebar.width - 1 : false).toBe(true);
      const scrollState = await page.locator(".industry-heat-scroll").evaluate(element => ({
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
      }));
      expect(scrollState.scrollWidth).toBeGreaterThanOrEqual(scrollState.clientWidth);

      const firstCell = page.locator(".heat-cell").first();
      await firstCell.hover();
      await expect(page.getByTestId("industry-point-detail")).toBeVisible();
      await firstCell.focus();
      await expect(page.getByTestId("industry-point-detail")).toContainText("完整 24 节点");
      await page.locator(".trend-hit-line").first().dispatchEvent("pointerover");
      await expect(page.locator(".trend-series.muted")).toHaveCount(4);
      await expect(page.locator(".trend-series.active")).toHaveCount(1);
      await page.locator(".trend-hit-line").first().dispatchEvent("pointerout");
      await expect(page.locator(".trend-series.muted")).toHaveCount(0);
      await page.locator(".trend-hit-line").first().focus();
      await expect(page.locator(".trend-series.muted")).toHaveCount(4);
      await page.locator(".trend-hit-line").first().blur();
      await expect(page.locator(".trend-series.muted")).toHaveCount(0);

      const infoButton = page.getByRole("button", { name: "热力图阅读说明" });
      await infoButton.focus();
      const tip = page.locator(".industry-info-tip.open [role=tooltip]");
      await expect(tip).toBeVisible();
      const tipBox = await tip.boundingBox();
      expect(tipBox?.x ?? -1).toBeGreaterThanOrEqual(0);
      expect((tipBox?.x ?? 0) + (tipBox?.width ?? 0)).toBeLessThanOrEqual(viewport.width);
      await page.keyboard.press("Escape");

      await page.locator(".industry-ranking-table tbody tr").first().getByRole("button", { name: /查看/ }).click();
      await expect(page.getByTestId("industry-stock-detail")).toBeVisible();
      await page.locator(".industry-table-wrap").evaluate(element => { element.scrollLeft = 0; });
      expect(errors).toEqual([]);

      const activeRows = await page.locator(".heat-row-label").evaluateAll(elements =>
        elements.map(element => element.textContent?.replace(/\s+/g, " ").trim()),
      );

      await page.screenshot({
        path: `${screenshotDir}/industry-strength-${viewport.width}.png`,
        fullPage: true,
        animations: "disabled",
        caret: "hide",
      });
      results.push({
        viewport,
        real_industries: 31,
        sample_nodes: 24,
        default_visible: 12,
        active_rows: activeRows,
        latest_on_left: true,
        ranking_rows: 15,
        keyboard_preview: true,
        trend_hover_focus: true,
        trend_leave_restores_all: true,
        trend_keyboard_focus_blur: true,
        minimum_audited_font_px: Math.min(...Object.values(fontSizes)),
        audited_font_px: fontSizes,
        accessible_info_tooltip: true,
        page_overflow: false,
        heatmap_internal_scroll: scrollState.scrollWidth > scrollState.clientWidth,
        console_errors: errors,
        result: "pass",
      });
    });
  }

  test("selector, detail and trend linkage use the same real response", async ({ page }) => {
    test.setTimeout(90_000);
    await page.setViewportSize({ width: 1600, height: 1000 });
    await page.goto("/industry-strength");
    await expect(page.locator(".heat-row-label")).toHaveCount(12, { timeout: 45_000 });
    const target = page.getByRole("option").nth(20);
    const industry = (await target.locator("b").innerText()).trim();
    await target.click();
    await expect(page.getByTestId("industry-point-detail")).toContainText(industry);
    await expect(page.locator(".trend-legend")).toContainText(industry);
    await page.getByRole("listbox", { name: "行业选择器" }).focus();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("listbox", { name: "行业选择器" }).locator('[aria-selected="true"]')).toHaveCount(1);
    results.push({ scenario: "selector-detail-trend-linkage", industry, result: "pass" });
  });
});

function audit(page: Page) {
  const errors: string[] = [];
  page.on("console", message => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", error => errors.push(error.message));
  return errors;
}

async function horizontalOverflow(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
}

async function fontAudit(page: Page) {
  return page.evaluate(() => {
    const selectors = {
      heatIndustry: ".heat-row-label b",
      heatStatus: ".heat-row-label small",
      heatSlope: ".heat-row-label em",
      heatCell: ".heat-cell",
      heatAxis: ".heat-time-axis time",
      trendLegend: ".trend-legend button",
      trendSelector: ".industry-selector-list > button b",
      rankingBody: ".industry-ranking-table td",
      rankingStatus: ".industry-status",
      rankingButton: ".stock-detail-button",
    };
    return Object.fromEntries(Object.entries(selectors).map(([name, selector]) => {
      const element = document.querySelector(selector);
      return [name, element ? Number.parseFloat(getComputedStyle(element).fontSize) : 0];
    }));
  });
}
