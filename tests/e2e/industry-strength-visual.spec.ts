import { mkdir, writeFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";

const screenshotDir = "docs/qa/screenshots/industry-strength";
const evidenceDir = "docs/qa/evidence/industry-strength";
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
      await expect(page.locator(".heat-row-label")).toHaveCount(16, { timeout: 45_000 });
      await expect(page.locator(".industry-data-foot")).toContainText("真实行业数：31");
      await expect(page.locator(".industry-data-foot")).toContainText("采样节点：24");
      await expect(page.getByRole("button", { name: /已折叠 15 个行业/ })).toBeVisible();

      expect(await horizontalOverflow(page)).toBe(false);
      const sidebar = await page.locator(".app-sidebar").boundingBox();
      const main = await page.locator(".industry-main").boundingBox();
      expect(sidebar && main ? main.x >= sidebar.x + sidebar.width - 1 : false).toBe(true);
      const scrollState = await page.locator(".industry-heat-scroll").evaluate(element => ({
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
      }));
      expect(scrollState.scrollWidth).toBeGreaterThanOrEqual(scrollState.clientWidth);

      const firstCell = page.locator(".heat-cell").first();
      await firstCell.click();
      await expect(page.getByTestId("industry-point-detail")).toBeVisible();
      await page.locator(".industry-ranking-table tbody tr").first().getByRole("button", { name: /查看/ }).click();
      await expect(page.getByTestId("industry-stock-detail")).toBeVisible();
      await page.locator(".industry-table-wrap").evaluate(element => { element.scrollLeft = 0; });
      expect(errors).toEqual([]);

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
        default_visible: 16,
        folded: 15,
        page_overflow: false,
        heatmap_internal_scroll: scrollState.scrollWidth > scrollState.clientWidth,
        console_errors: errors,
        result: "pass",
      });
    });
  }

  test("expand, detail and trend linkage use the same real response", async ({ page }) => {
    test.setTimeout(90_000);
    await page.setViewportSize({ width: 1600, height: 1000 });
    await page.goto("/industry-strength");
    await expect(page.locator(".heat-row-label")).toHaveCount(16, { timeout: 45_000 });
    await page.getByRole("button", { name: /已折叠 15 个行业/ }).click();
    await expect(page.locator(".heat-row-label")).toHaveCount(31);
    const target = page.locator(".heat-row-label").nth(20);
    const industry = (await target.locator("b").innerText()).trim();
    await target.click();
    await expect(page.getByTestId("industry-point-detail")).toContainText(industry);
    await expect(page.locator(".trend-legend")).toContainText(industry);
    results.push({ scenario: "expand-detail-trend-linkage", industry, result: "pass" });
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
