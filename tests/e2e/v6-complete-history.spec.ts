import { expect, test } from "@playwright/test";


test("six months is only the default viewport and complete history stays reachable", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto("/market?code=000001");
  await expect(page.getByRole("heading", { name: "平安银行" })).toBeVisible({
    timeout: 20_000,
  });

  const chart = page.locator(".market-chart").first();
  await expect(chart).toHaveAttribute("data-bars", "110");
  await expect.poll(
    async () => Number(await chart.getAttribute("data-source-bars")),
    { timeout: 30_000 },
  ).toBeGreaterThan(1_000);
  await expect(chart).toHaveAttribute("data-bars", "110");

  const sourceStart = String(await chart.getAttribute("data-first-time"));
  const initialVisibleStart = String(await chart.getAttribute("data-visible-first-time"));
  expect(sourceStart).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  expect(initialVisibleStart).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  expect(sourceStart < initialVisibleStart).toBeTruthy();

  const initialLogicalFrom = Number(await chart.getAttribute("data-visible-from"));
  const box = await chart.boundingBox();
  if (!box) throw new Error("market chart is not visible");
  await page.mouse.move(box.x + box.width * 0.25, box.y + box.height * 0.45);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.8, box.y + box.height * 0.45, {
    steps: 12,
  });
  await page.mouse.up();
  await expect.poll(
    async () => Number(await chart.getAttribute("data-visible-from")),
  ).toBeLessThan(initialLogicalFrom);
  const draggedVisibleStart = String(await chart.getAttribute("data-visible-first-time"));
  expect(draggedVisibleStart < initialVisibleStart).toBeTruthy();

  await page.getByRole("button", { name: "全部", exact: true }).click();
  await expect.poll(async () => {
    const visible = Number(await page.locator(".market-chart").first().getAttribute("data-bars"));
    const source = Number(await page.locator(".market-chart").first().getAttribute("data-source-bars"));
    return source > 1_000 && visible === source;
  }).toBeTruthy();
  const allChart = page.locator(".market-chart").first();
  expect(Number(await allChart.getAttribute("data-bars"))).toBe(
    Number(await allChart.getAttribute("data-source-bars")),
  );

  const search = page.getByRole("textbox", { name: "搜索股票" });
  await search.fill("000858");
  const result = page.locator(".search-results button").filter({ hasText: "000858" }).first();
  await expect(result).toBeVisible();
  await result.click();
  await expect(page.getByRole("heading", { name: "五粮液" })).toBeVisible({
    timeout: 20_000,
  });
  const switched = page.locator(".market-chart").first();
  await expect(switched).toHaveAttribute("data-bars", "110");
  await expect.poll(
    async () => Number(await switched.getAttribute("data-source-bars")),
    { timeout: 30_000 },
  ).toBeGreaterThan(1_000);
  await expect(switched).toHaveAttribute("data-bars", "110");
  expect(
    String(await switched.getAttribute("data-first-time"))
    < String(await switched.getAttribute("data-visible-first-time")),
  ).toBeTruthy();
  await expect.poll(() => new URL(page.url()).searchParams.get("code")).toBe("000858");
});
