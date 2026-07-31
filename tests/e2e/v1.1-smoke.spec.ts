import { expect, test } from "@playwright/test";

test("board connects to the local service and exposes independent categories", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "综合榜" })).toBeVisible();
  await expect(page.locator(".candidate-table tbody tr").first()).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: /突破启动/ }).click();
  await expect(page.getByRole("heading", { name: "突破启动" })).toBeVisible();
  await page.getByRole("button", { name: /查看全部/ }).click();
  await expect(page.locator(".candidate-table tbody tr")).toHaveCount(50);
  expect(errors).toEqual([]);
});

test("market opens with about five months of daily bars", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto("/market?code=000001");
  await expect(page.getByRole("heading", { name: "平安银行" })).toBeVisible({ timeout: 15_000 });
  const count = Number(await page.locator(".market-chart").getAttribute("data-bars"));
  expect(count).toBeGreaterThanOrEqual(95);
  expect(count).toBeLessThanOrEqual(115);
  await page.getByRole("button", { name: "周K", exact: true }).click();
  await expect(page.locator(".market-chart")).not.toHaveAttribute("data-bars", String(count));
  expect(errors).toEqual([]);
});
