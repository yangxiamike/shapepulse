import { expect, test } from "@playwright/test";

type BoxRow = {
  code: string;
  count: number;
  x: number;
  y: number;
  width: number;
  height: number;
};

async function blockGeometry(page: import("@playwright/test").Page) {
  return page
    .getByRole("group", { name: /Top100 行业矩形树图/ })
    .getByRole("button")
    .evaluateAll(elements =>
      elements.map(element => {
        const box = element.getBoundingClientRect();
        const node = element as HTMLElement;
        return {
          code: node.dataset.industryCode || "",
          count: Number(node.dataset.count || 0),
          x: box.x,
          y: box.y,
          width: box.width,
          height: box.height,
        };
      }),
    );
}

test("Top100 Treemap keeps area semantics while 10/20-day color context changes", async ({
  page,
}) => {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on("console", message => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", error => pageErrors.push(error.message));

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/template-breadth-v3");
  await expect(
    page.getByRole("heading", { name: "Top100 行业宽度" }),
  ).toBeVisible();

  const map = page.getByRole("group", {
    name: /Top100 行业矩形树图/,
  });
  await expect(map).toHaveAttribute("data-total", "100");
  await expect(map.locator('[data-industry-code="other"]')).toHaveAttribute(
    "data-direction",
    "neutral",
  );
  await expect(map.locator('[data-direction="expand"]').first()).toBeVisible();
  await expect(map.locator('[data-direction="contract"]').first()).toBeVisible();

  const centered = await map
    .getByRole("button")
    .first()
    .evaluate(element => {
      const style = getComputedStyle(element);
      return {
        alignItems: style.alignItems,
        justifyContent: style.justifyContent,
        textAlign: style.textAlign,
      };
    });
  expect(centered).toEqual({
    alignItems: "center",
    justifyContent: "center",
    textAlign: "center",
  });

  const before = await blockGeometry(page);
  expect(before.reduce((sum, item) => sum + item.count, 0)).toBe(100);
  expect(
    before
      .filter(item => item.count >= 3)
      .every(
        item =>
          Math.max(
            item.width / Math.max(1, item.height),
            item.height / Math.max(1, item.width),
          ) <= 3.75,
      ),
  ).toBeTruthy();

  await page.getByRole("button", { name: "20日", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "20日", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  const after = await blockGeometry(page);
  expect(after.map(item => item.code)).toEqual(before.map(item => item.code));
  after.forEach((item, index) => {
    const previous = before[index] as BoxRow;
    expect(Math.abs(item.x - previous.x)).toBeLessThanOrEqual(1);
    expect(Math.abs(item.y - previous.y)).toBeLessThanOrEqual(1);
    expect(Math.abs(item.width - previous.width)).toBeLessThanOrEqual(1);
    expect(Math.abs(item.height - previous.height)).toBeLessThanOrEqual(1);
  });

  const detailResponse = page.waitForResponse(response =>
    response.url().includes("/template-breadth-v3-details/"),
  );
  await map.locator('[data-industry-code="other"]').click();
  expect((await detailResponse).status()).toBe(200);
  await expect(
    page.getByRole("heading", { name: /其他行业（\d+个行业，\d+只）/ }),
  ).toBeVisible();
  await expect(page.getByText("“其他行业”具体构成")).toBeVisible();
  await expect(page.getByText(/当前入选股票/)).toBeVisible();
  await expect(page.getByText(/行业 Top100 数量时间序列/)).toBeVisible();

  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});

for (const viewport of [
  { name: "wide", width: 1900, height: 956 },
  { name: "desktop", width: 1440, height: 900 },
  { name: "tablet", width: 1024, height: 768 },
  { name: "mobile", width: 390, height: 844 },
]) {
  test(`Top100 industry width stays readable at ${viewport.name}`, async ({
    page,
  }) => {
    await page.setViewportSize({
      width: viewport.width,
      height: viewport.height,
    });
    await page.goto("/template-breadth-v3");
    await expect(
      page.getByRole("heading", { name: "Top100 行业宽度" }),
    ).toBeVisible();
    const map = page.getByRole("group", {
      name: /Top100 行业矩形树图/,
    });
    await expect(map).toBeVisible();
    const mapBox = await map.boundingBox();
    const geometry = await page.evaluate(() => {
      return {
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      };
    });
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth);
    expect(mapBox?.width || 0).toBeGreaterThan(300);
    expect(mapBox?.height || 0).toBeGreaterThanOrEqual(
      viewport.width <= 600 ? 470 : 490,
    );
    await expect(
      page.getByRole("button", { name: "10日", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "20日", exact: true }),
    ).toBeVisible();
  });
}
