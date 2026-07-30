import { expect, test } from "@playwright/test";

const templateKeys = [
  "fresh_breakout",
  "healthy_uptrend",
  "pullback_strengthening",
  "parabolic_uptrend",
];

test("sidebar opens the template library and market pages", async ({
  page,
}) => {
  await page.goto("/template-breadth-v3");
  await page.getByRole("link", { name: "模板库" }).click();
  await expect(page).toHaveURL(/\/templates$/);
  await expect(page.getByRole("heading", { name: "模板库", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "冻结四模板" })).toBeVisible();
  await expect(page.getByText("Failed to fetch", { exact: true })).toHaveCount(0);

  await page.getByRole("link", { name: "行情详情" }).click();
  await expect(page).toHaveURL(/\/market\?/);
  await expect(page.getByRole("heading", { name: "平安银行" })).toBeVisible();
  await expect(page.getByText("已连接", { exact: true })).toBeVisible();
  await expect(page.getByText("Failed to fetch", { exact: true })).toHaveCount(0);
});

test("all four frozen templates expose independent one-year timelines", async ({
  page,
}) => {
  const timelineResponses: string[] = [];
  page.on("response", response => {
    if (response.url().includes("/template-breadth-v3-timelines/")) {
      timelineResponses.push(response.url());
    }
  });

  await page.goto("/template-breadth-v3");
  const slider = page.getByRole("slider", {
    name: "选择行业空间历史交易日",
  });
  await expect(slider).toHaveAttribute("max", "51");
  await expect(slider).toHaveAttribute("aria-valuetext", /2026-07-29/);

  for (const key of templateKeys) {
    const manifest = await page.evaluate(async templateKey => {
      const response = await fetch("/template-breadth-v3.json");
      const payload = await response.json();
      return payload.templates.find(
        (item: { key: string }) => item.key === templateKey,
      );
    }, key);
    expect(manifest.timeline.sampled_points).toBe(52);
    expect(manifest.timeline.history_trading_days).toBe(252);
    expect(manifest.timeline.trading_day_step).toBe(5);
    expect(manifest.timeline.latest_always_included).toBe(true);
    expect(manifest.timeline_url).toContain(key);
  }

  const tabs = page.getByRole("navigation", { name: "冻结四模板切换" });
  for (let index = 1; index < templateKeys.length; index += 1) {
    await tabs.getByRole("button").nth(index).click();
    await expect(slider).toHaveAttribute("max", "51");
    await expect(slider).toHaveAttribute("aria-valuetext", /2026-07-29/);
    await expect(
      page.getByRole("group", { name: /Top100 行业矩形树图/ }),
    ).toHaveAttribute("data-total", "100");
  }

  expect(
    new Set(
      timelineResponses.map(url =>
        url.slice(url.lastIndexOf("/") + 1).replace(".json", ""),
      ),
    ),
  ).toEqual(new Set(templateKeys));
});

test("timeline click, drag and keyboard movement keep the whole view in sync", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/template-breadth-v3");

  const slider = page.getByRole("slider", {
    name: "选择行业空间历史交易日",
  });
  await expect(slider).toHaveAttribute("aria-valuetext", /2026-07-29/);
  await slider.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(slider).toHaveAttribute("aria-valuetext", /2026-07-28/);
  await expect(page.getByText("回溯交易日 2026-07-28")).toBeVisible();
  await expect(page.getByText(/2026-07-28 vs 2026-07-14/)).toBeVisible();

  const map = page.getByRole("group", {
    name: /Top100 行业矩形树图/,
  });
  const latestOrder = await map
    .getByRole("button")
    .evaluateAll(elements =>
      elements.map(
        element => (element as HTMLElement).dataset.industryCode || "",
      ),
    );
  await expect(map).toHaveAttribute("data-total", "100");
  const historicalTotal = await map
    .getByRole("button")
    .evaluateAll(elements =>
      elements.reduce(
        (sum, element) =>
          sum + Number((element as HTMLElement).dataset.count || 0),
        0,
      ),
  );
  expect(historicalTotal).toBe(100);

  const sliderBox = await slider.boundingBox();
  expect(sliderBox).not.toBeNull();
  await slider.click({
    position: {
      x: (sliderBox?.width || 1) / 2,
      y: (sliderBox?.height || 1) / 2,
    },
  });
  const clickedIndex = Number(await slider.inputValue());
  expect(clickedIndex).toBeGreaterThan(15);
  expect(clickedIndex).toBeLessThan(36);

  await slider.fill("0");
  await expect(slider).toHaveAttribute("aria-valuetext", /2025-07-16/);
  await expect(page.getByText(/2025-07-16 vs 2025-07-02/)).toBeVisible();
  const firstOrder = await map
    .getByRole("button")
    .evaluateAll(elements =>
      elements.map(
        element => (element as HTMLElement).dataset.industryCode || "",
      ),
    );
  const sharedLatest = latestOrder.filter(code => firstOrder.includes(code));
  const sharedFirst = firstOrder.filter(code => latestOrder.includes(code));
  expect(sharedFirst).toEqual(sharedLatest);

  const transition = await map
    .getByRole("button")
    .first()
    .evaluate(element => getComputedStyle(element).transitionProperty);
  expect(transition).toContain("left");
  expect(transition).toContain("top");
  expect(transition).toContain("width");
  expect(transition).toContain("height");
});

test("historical industry selection never reuses the latest stock list", async ({
  page,
}) => {
  await page.goto("/template-breadth-v3");
  const map = page.getByRole("group", {
    name: /Top100 行业矩形树图/,
  });
  const other = map.locator('[data-industry-code="other"]');

  const latestDetail = page.waitForResponse(response =>
    response.url().includes(
      "/template-breadth-v3-details/fresh_breakout.json",
    ),
  );
  await other.click();
  await latestDetail;
  await expect(page.getByText("最新交易日入选股票")).toBeVisible();

  const slider = page.getByRole("slider", {
    name: "选择行业空间历史交易日",
  });
  await slider.fill("0");
  await expect(
    page.getByText("历史日期仅显示行业统计。"),
  ).toBeVisible();
  await expect(
    page.getByText(/这里不会用最新股票清单代替 2025-07-16/),
  ).toBeVisible();
  await expect(page.getByText("最新交易日入选股票")).toHaveCount(0);
  await expect(page.getByLabel(/其他行业 2025-07-16 行业统计/)).toBeVisible();
});

test("slow timeline responses cannot overwrite a newer template selection", async ({
  page,
}) => {
  await page.route("**/template-breadth-v3-timelines/*.json", async route => {
    if (route.request().url().endsWith("/fresh_breakout.json")) {
      await new Promise(resolve => setTimeout(resolve, 300));
    }
    await route.continue();
  });

  await page.goto("/template-breadth-v3");
  const tabs = page.getByRole("navigation", { name: "冻结四模板切换" });
  await tabs.getByRole("button").nth(1).click();
  const slider = page.getByRole("slider", {
    name: "选择行业空间历史交易日",
  });
  await expect(slider).toHaveAttribute("aria-valuetext", /2026-07-29/);
  await page.waitForTimeout(400);
  await expect(tabs.getByRole("button").nth(1)).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(
    page.locator('[data-industry-code="801080.SI"]'),
  ).toHaveAttribute("data-count", "47");
});
