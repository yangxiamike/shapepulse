import { expect, test } from "@playwright/test";

test("Top100 squarified map remains usable on desktop and mobile", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/template-breadth-v3");
  await expect(page.getByRole("heading", { name: "Top100 行业宽度" })).toBeVisible();
  const blocks = page.getByRole("group", { name: /Top100 行业矩形树图/ }).getByRole("button");
  await expect(blocks.first()).toBeVisible();
  const boxes = await blocks.evaluateAll(elements => elements.map(element => {
    const box = element.getBoundingClientRect();
    return { width: box.width, height: box.height };
  }));
  expect(boxes.every(box => box.width >= 28 && box.height >= 28)).toBeTruthy();
  expect(Math.max(...boxes.map(box => Math.max(box.width / box.height, box.height / box.width)))).toBeLessThan(5);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.getByRole("heading", { name: "Top100 行业宽度" })).toBeVisible();
  const geometry = await page.evaluate(() => {
    const sidebar = document.querySelector(".app-sidebar")?.getBoundingClientRect();
    return { scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth, sidebarTop: sidebar?.top || 0 };
  });
  expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth);
  expect(geometry.sidebarTop).toBeGreaterThanOrEqual(770);
});
