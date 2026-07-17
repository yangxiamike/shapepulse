import { mkdir, writeFile } from "node:fs/promises";
import { expect, test, type Locator, type Page } from "@playwright/test";

const screenshotDir = "docs/qa/screenshots/v1.2-final";
const evidenceDir = "docs/qa/evidence/v1.2-final";
const apiBase = process.env.MARKET_API_BASE || "http://127.0.0.1:8765/api";
const evidence: Array<Record<string, unknown>> = [];

const twoPointTools = new Set([
  "趋势线",
  "线段",
  "射线",
  "斐波那契回撤",
  "斐波那契扩展",
  "曲线",
  "测量",
]);

test.describe.serial("V1.2 final closeout", () => {
  test.beforeAll(async () => {
    await mkdir(screenshotDir, { recursive: true });
    await mkdir(evidenceDir, { recursive: true });
  });

  test.afterAll(async () => {
    await writeFile(
      `${evidenceDir}/browser-results.json`,
      `${JSON.stringify({ captured_at: new Date().toISOString(), results: evidence }, null, 2)}\n`,
      "utf8",
    );
  });

  test("Top K and snapshots stay stable while every real pattern match reaches table and detail", async ({ page }) => {
    test.setTimeout(180_000);
    const errors = audit(page);
    await page.setViewportSize({ width: 1920, height: 1080 });
    await setFontSize(page, "standard");
    const historyBefore = await apiJson(page, "/screen/snapshots?page=1&page_size=1");
    await openBoard(page);

    await expect(page.getByRole("spinbutton", { name: "Top K" })).toHaveValue("50");
    const raw = await apiJson(page, "/screen?board=主板&exclude_st=true&top_k=50&mode=per_category");
    expect(raw.results).toHaveLength(50);
    expect(raw.results.every((item: { matches?: unknown[] }) => Array.isArray(item.matches) && item.matches.length > 0)).toBe(true);
    const multi = raw.results.find((item: { matches?: unknown[] }) => (item.matches?.length || 0) > 1);
    expect(multi).toBeTruthy();

    const expand = page.locator(".view-all-button");
    if (await expand.isVisible()) await expand.click();
    const codes = await tableCodes(page);
    expect(codes).toHaveLength(50);
    expect(codes).toEqual(raw.results.map((item: { symbol?: string; ts_code: string }) => String(item.symbol || item.ts_code).split(".")[0]));

    const multiCode = String(multi.symbol || multi.ts_code).split(".")[0];
    const multiRow = page.locator(".candidate-table tbody tr").filter({ hasText: multiCode });
    await expect(multiRow).toHaveCount(1);
    const tablePatterns = await multiRow.locator(".pattern-tag").allTextContents();
    expect(tablePatterns).toHaveLength(multi.matches.length);
    await multiRow.click();
    await expect(page.getByTestId("pattern-fact-count")).toHaveText(`共匹配 ${multi.matches.length} 个真实形态`);
    await expect(page.locator(".detail-pattern-match")).toHaveCount(multi.matches.length);
    expect(await page.locator(".detail-pattern-match").evaluateAll(items => items.map(item => item.getAttribute("data-pattern"))))
      .toEqual(multi.matches.map((item: { category: string }) => item.category));

    const run = page.getByRole("button", { name: "运行筛选", exact: true });
    await Promise.all([
      page.waitForResponse(response => response.url().includes("/api/screen") && response.request().method() === "POST" && response.ok()),
      run.click(),
    ]);
    await expect(run).toBeEnabled({ timeout: 120_000 });
    const historyAfter = await apiJson(page, "/screen/snapshots?page=1&page_size=1");
    expect(historyAfter.total).toBe(historyBefore.total);
    await expect(page.getByRole("spinbutton", { name: "Top K" })).toHaveValue("50");

    await page.screenshot({ path: `${screenshotDir}/board-1920-standard.png`, fullPage: true, animations: "disabled", caret: "initial" });
    expect(errors).toEqual([]);
    evidence.push({
      gate: "G2-G3",
      top_k: 50,
      complete_codes: codes,
      multi_pattern: { code: multiCode, count: multi.matches.length, categories: multi.matches.map((item: { category: string }) => item.category) },
      ordinary_screen_does_not_save_snapshot: historyAfter.total === historyBefore.total,
      result: "pass",
    });
  });

  test("three persistent font sizes and critical text geometry pass four widths plus zoom equivalent", async ({ page }) => {
    test.setTimeout(240_000);
    const errors = audit(page);
    await page.setViewportSize({ width: 1600, height: 1000 });
    await openBoard(page);

    const computed: Record<string, string> = {};
    for (const [label, value] of [["小字体", "small"], ["标准字体", "standard"], ["大字体", "large"]] as const) {
      await page.getByRole("button", { name: label }).click();
      await expect(page.locator("html")).toHaveAttribute("data-font-size", value);
      computed[value] = await page.locator(".candidate-table").evaluate(element => getComputedStyle(element).fontSize);
    }
    expect(Number.parseFloat(computed.small)).toBeLessThan(Number.parseFloat(computed.standard));
    expect(Number.parseFloat(computed.large)).toBeGreaterThan(Number.parseFloat(computed.standard));
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-font-size", "large");
    await expect(page.getByRole("button", { name: "大字体" })).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".candidate-table tbody tr").first()).toBeVisible({ timeout: 60_000 });
    await waitForChartPaint(page.locator(".detail-chart"));
    await page.screenshot({ path: `${screenshotDir}/board-1600-large.png`, fullPage: true, animations: "disabled", caret: "initial" });

    const cases = [
      { width: 1920, height: 1080, font: "standard", screenshot: "board-1920-standard-geometry.png" },
      { width: 1600, height: 1000, font: "large", screenshot: "board-1600-large-geometry.png" },
      { width: 1366, height: 900, font: "standard", screenshot: "board-1366-standard.png" },
      { width: 1024, height: 800, font: "large", screenshot: "board-1024-large.png" },
      { width: 1280, height: 800, font: "large", screenshot: null, zoom_equivalent: "1600px at 125%" },
    ] as const;
    const geometry: Array<Record<string, unknown>> = [];
    for (const item of cases) {
      await page.setViewportSize({ width: item.width, height: item.height });
      await openBoard(page);
      await setFontSize(page, item.font);
      const overflows = await criticalTextOverflows(page);
      expect(overflows).toEqual([]);
      expect(await horizontalOverflow(page)).toBe(false);
      await expect(page.locator(".candidate-table thead th")).toHaveCount(10);
      const tableScroll = await revealLastTableColumn(page);
      expect(tableScroll.last_header_visible).toBe(true);
      for (const control of [page.locator(".detail-actions .secondary-action"), page.getByRole("link", { name: "打开行情" })]) {
        await control.scrollIntoViewIfNeeded();
        expect(await fullyInteractable(control)).toBe(true);
      }
      if (item.screenshot) {
        await page.locator(".table-wrap").evaluate(element => { (element as HTMLElement).scrollLeft = 0; });
        await page.screenshot({ path: `${screenshotDir}/${item.screenshot}`, fullPage: true, animations: "disabled", caret: "initial" });
      }
      geometry.push({ viewport: [item.width, item.height], font: item.font, zoom_equivalent: "zoom_equivalent" in item ? item.zoom_equivalent : null, table_scroll: tableScroll });
    }

    await page.setViewportSize({ width: 1366, height: 900 });
    await openMarket(page);
    await expect(page.locator("html")).toHaveAttribute("data-font-size", "large");
    await expect(page.locator(".market-chart").first()).toHaveAttribute("data-ui-font-size", "14");
    expect(await horizontalOverflow(page)).toBe(false);
    await page.screenshot({ path: `${screenshotDir}/market-1366-large.png`, animations: "disabled", caret: "initial" });
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-font-size", "large");
    await setFontSize(page, "standard");

    expect(errors).toEqual([]);
    evidence.push({ gate: "G2-G4", font_pixels: computed, persisted_across_routes: true, market_chart_font_pixels: 14, geometry, result: "pass" });
  });

  test("all drawing tools work; two-click placement and line/ray/trend geometry are distinct", async ({ page }) => {
    test.setTimeout(240_000);
    const errors = audit(page);
    await page.setViewportSize({ width: 1600, height: 1000 });
    await setFontSize(page, "standard");
    await openMarket(page);
    const chart = page.locator(".market-chart").first();
    const overlay = chart.locator("canvas.drawing-overlay");
    const box = await visibleBox(overlay);

    const signatures: string[] = [];
    const tools = [
      ["趋势线", "trend"],
      ["线段", "segment"],
      ["射线", "ray"],
      ["水平线", "horizontal"],
      ["垂直线", "vertical"],
      ["斐波那契回撤", "fibonacci"],
      ["斐波那契扩展", "fibonacci-extension"],
      ["曲线", "curve"],
      ["自由绘制", "freehand"],
      ["文本", "text"],
      ["测量", "measure"],
    ] as const;
    for (const [label, kind] of tools) {
      await clearDrawings(page, chart);
      await page.getByRole("button", { name: label, exact: true }).scrollIntoViewIfNeeded();
      await page.getByRole("button", { name: label, exact: true }).click();
      if (kind === "text") await page.getByLabel("标注文本").fill("突破位");
      if (twoPointTools.has(label)) {
        await page.mouse.click(box.x + 220, box.y + 330);
        await expect(chart).toHaveAttribute("data-drawings", "0");
        await expect(overlay).toHaveAttribute("data-drawing-phase", "awaiting-second-point");
        const beforePreview = await canvasSignature(overlay);
        await page.mouse.move(box.x + 650, box.y + 170, { steps: 6 });
        await expect.poll(() => canvasSignature(overlay)).not.toBe(beforePreview);
        await page.mouse.click(box.x + 650, box.y + 170);
      } else if (kind === "freehand") {
        await page.mouse.move(box.x + 220, box.y + 320);
        await page.mouse.down();
        for (let index = 1; index <= 9; index += 1) {
          await page.mouse.move(box.x + 220 + index * 45, box.y + 320 + Math.sin(index) * 42, { steps: 2 });
        }
        await page.mouse.up();
      } else {
        await page.mouse.click(box.x + 350, box.y + 240);
      }
      await expect(chart).toHaveAttribute("data-drawings", "1");
      await expect(chart).toHaveAttribute("data-drawing-kinds", kind);
      signatures.push(await canvasSignature(overlay));
    }
    expect(new Set(signatures).size).toBe(tools.length);

    const lineGeometry: Record<string, Awaited<ReturnType<typeof drawingBounds>>> = {};
    for (const label of ["趋势线", "线段", "射线"] as const) {
      await clearDrawings(page, chart);
      const button = page.getByRole("button", { name: label, exact: true });
      await button.click();
      expect(await button.getAttribute("title")).toMatch(label === "趋势线" ? /两端延伸/ : label === "射线" ? /向前延伸/ : /只连接/);
      await page.mouse.click(box.x + 260, box.y + 350);
      await page.mouse.move(box.x + 690, box.y + 160, { steps: 5 });
      await page.mouse.click(box.x + 690, box.y + 160);
      lineGeometry[label] = await drawingBounds(overlay);
    }
    expect(lineGeometry["趋势线"].min_x).toBeLessThanOrEqual(1);
    expect(lineGeometry["趋势线"].max_x).toBeGreaterThanOrEqual(lineGeometry["趋势线"].canvas_width - 2);
    expect(lineGeometry["射线"].min_x).toBeGreaterThan(100);
    expect(lineGeometry["射线"].max_x).toBeGreaterThanOrEqual(lineGeometry["射线"].canvas_width - 2);
    expect(lineGeometry["线段"].min_x).toBeGreaterThan(100);
    expect(lineGeometry["线段"].max_x).toBeLessThan(lineGeometry["线段"].canvas_width - 100);

    await clearDrawings(page, chart);
    await page.getByRole("button", { name: "线段", exact: true }).click();
    await page.mouse.move(box.x + 220, box.y + 330);
    await page.mouse.down();
    await page.mouse.move(box.x + 650, box.y + 170, { steps: 8 });
    await page.mouse.up();
    await expect(chart).toHaveAttribute("data-drawings", "1");

    await page.screenshot({ path: `${screenshotDir}/market-1600-segment.png`, animations: "disabled", caret: "initial" });
    expect(errors).toEqual([]);
    evidence.push({ gate: "G5-G6", tools: tools.map(([label, kind]) => ({ label, kind })), unique_signatures: signatures.length, first_click_keeps_zero_drawings: true, drag_compatible: true, line_geometry: lineGeometry, result: "pass" });
  });

  test("Fibonacci settings and both divider modes pass mouse, keyboard, validation and responsive geometry", async ({ page }) => {
    test.setTimeout(240_000);
    const errors = audit(page);
    await page.setViewportSize({ width: 1600, height: 1000 });
    await openMarket(page);
    const chart = page.locator(".market-chart").first();
    const overlay = chart.locator("canvas.drawing-overlay");
    const box = await visibleBox(overlay);

    await page.getByRole("button", { name: "斐波那契回撤", exact: true }).click();
    const fib = await drawFibonacciByClicks(page, box);
    await page.mouse.dblclick(fib.middle.x, fib.middle.y, { delay: 50 });
    const dialog = page.getByRole("dialog", { name: "斐波那契比例设置" });
    await expect(dialog).toBeVisible();
    expect(await dialog.locator(".fibonacci-level-list > label").count()).toBe(7);
    expect(await withinViewport(dialog)).toBe(true);
    const signatureBeforeToggle = await canvasSignature(overlay);
    const secondDefault = dialog.locator('.fibonacci-level-list input[type="checkbox"]').nth(1);
    await secondDefault.uncheck();
    await expect.poll(() => canvasSignature(overlay)).not.toBe(signatureBeforeToggle);

    await dialog.getByLabel("自定义斐波那契比例").fill("11");
    await dialog.getByRole("button", { name: "新增", exact: true }).click();
    await expect(dialog.getByRole("alert")).toContainText("0 到 10");
    await dialog.getByLabel("自定义斐波那契比例").fill("1.414");
    await dialog.getByRole("button", { name: "新增", exact: true }).click();
    await expect(dialog.locator(".fibonacci-level-list > label")).toHaveCount(8);
    await expect(dialog.locator(".fibonacci-level-list > label").filter({ hasText: "1.414" })).toContainText("自定义");
    await page.screenshot({ path: `${screenshotDir}/market-1600-fibonacci-settings.png`, animations: "disabled", caret: "initial" });
    await page.mouse.click(4, 4);
    await expect(dialog).toBeHidden();

    await page.mouse.dblclick(fib.middle.x, fib.middle.y, { delay: 50 });
    await expect(dialog).toBeVisible();
    const custom = dialog.locator(".fibonacci-level-list > label").filter({ hasText: "1.414" });
    await custom.getByRole("button", { name: /删除自定义比例/ }).click();
    await expect(dialog.locator(".fibonacci-level-list > label")).toHaveCount(7);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();

    await clearDrawings(page, chart);
    await page.getByRole("button", { name: "斐波那契回撤", exact: true }).click();
    const inherited = await drawFibonacciByClicks(page, box);
    await page.mouse.dblclick(inherited.middle.x, inherited.middle.y, { delay: 50 });
    await expect(dialog).toBeVisible();
    expect(await dialog.locator('.fibonacci-level-list input[type="checkbox"]').nth(1).isChecked()).toBe(false);
    await page.keyboard.press("Escape");

    await page.goto("/");
    await expect(page.locator(".candidate-table tbody tr").first()).toBeVisible({ timeout: 60_000 });
    const workspace = page.locator(".board-workspace");
    const separator = page.getByTestId("board-workspace-resizer");
    const freeBefore = await boardGeometry(page);
    let separatorBox = await visibleBox(separator);
    await page.mouse.move(separatorBox.x + 5, separatorBox.y + 220);
    await page.mouse.down();
    await page.mouse.move(separatorBox.x - 60, separatorBox.y + 320, { steps: 8 });
    await page.mouse.up();
    const freeAfter = await boardGeometry(page);
    expect(freeAfter.detail_width).toBeGreaterThan(freeBefore.detail_width + 35);
    expect(freeAfter.workspace_height).toBeGreaterThan(freeBefore.workspace_height + 70);
    await page.screenshot({ path: `${screenshotDir}/board-1600-free-resized.png`, fullPage: true, animations: "disabled", caret: "initial" });

    await page.getByRole("button", { name: "仅左右比例", exact: true }).click();
    await expect(workspace).toHaveAttribute("data-resize-mode", "ratio");
    const ratioBefore = await boardGeometry(page);
    separatorBox = await visibleBox(separator);
    await page.mouse.move(separatorBox.x + 5, separatorBox.y + 220);
    await page.mouse.down();
    await page.mouse.move(separatorBox.x + 70, separatorBox.y + 100, { steps: 8 });
    await page.mouse.up();
    const ratioAfter = await boardGeometry(page);
    expect(Math.abs(ratioAfter.workspace_height - ratioBefore.workspace_height)).toBeLessThanOrEqual(1);
    expect(Math.abs(ratioAfter.detail_width - ratioBefore.detail_width)).toBeGreaterThan(35);
    expect(await detailTextOverflows(page)).toEqual([]);
    expect(await horizontalOverflow(page)).toBe(false);
    await page.screenshot({ path: `${screenshotDir}/board-1600-ratio-resized.png`, fullPage: true, animations: "disabled", caret: "initial" });

    await page.setViewportSize({ width: 1024, height: 800 });
    await page.goto("/");
    await expect(page.locator(".candidate-table tbody tr").first()).toBeVisible({ timeout: 60_000 });
    await expect(separator).toBeVisible();
    await expect(separator).toHaveAttribute("aria-orientation", "horizontal");
    await separator.scrollIntoViewIfNeeded();
    separatorBox = await visibleBox(separator);
    const stackedBefore = await boardGeometry(page);
    await page.mouse.move(separatorBox.x + 300, separatorBox.y + 6);
    await page.mouse.down();
    await page.mouse.move(separatorBox.x + 300, separatorBox.y + 86, { steps: 8 });
    await page.mouse.up();
    const stackedAfter = await boardGeometry(page);
    expect(stackedAfter.candidate_height).toBeGreaterThan(stackedBefore.candidate_height + 60);
    await page.screenshot({ path: `${screenshotDir}/board-1024-free-vertical.png`, fullPage: true, animations: "disabled", caret: "initial" });
    await page.getByRole("button", { name: "仅左右比例", exact: true }).click();
    await expect(separator).toBeHidden();

    await openMarket(page);
    await page.screenshot({ path: `${screenshotDir}/market-1024-standard.png`, animations: "disabled", caret: "initial" });
    expect(errors).toEqual([]);
    evidence.push({
      gate: "G7-G8",
      fibonacci: { default_levels: 7, toggle_immediate: true, validation: true, custom_add_delete: true, inherited_default: true, escape_close: true, outside_close: true },
      divider: { free_before: freeBefore, free_after: freeAfter, ratio_before: ratioBefore, ratio_after: ratioAfter, stacked_before: stackedBefore, stacked_after: stackedAfter, ratio_stacked_hidden: true },
      result: "pass",
    });
  });
});

async function openBoard(page: Page) {
  await page.goto("/");
  await expect(page.locator(".candidate-table tbody tr").first()).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".detail-chart .market-chart")).toHaveAttribute("data-bars", /[1-9]\d*/);
  await waitForChartPaint(page.locator(".detail-chart"));
}

async function openMarket(page: Page) {
  await page.goto("/market?code=002728");
  await expect(page.locator(".market-chart").first()).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".quote-title h1")).toContainText("特一药业");
  await expect(page.locator(".market-chart").first()).toHaveAttribute("data-bars", /[1-9]\d*/);
  await waitForChartPaint(page.locator(".market-chart").first());
}

async function waitForChartPaint(chart: Locator) {
  await expect.poll(async () => chart.locator("canvas").evaluateAll(canvases => {
    let saturatedPixels = 0;
    for (const item of canvases) {
      const canvas = item as HTMLCanvasElement;
      const context = canvas.getContext("2d");
      if (!context || canvas.width < 2 || canvas.height < 2) continue;
      const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
      const stride = Math.max(4, Math.floor(pixels.length / 20_000 / 4) * 4);
      for (let index = 0; index < pixels.length; index += stride) {
        const red = pixels[index];
        const green = pixels[index + 1];
        const blue = pixels[index + 2];
        if (pixels[index + 3] > 0 && Math.max(red, green, blue) - Math.min(red, green, blue) > 55) saturatedPixels += 1;
      }
    }
    return saturatedPixels;
  }), { timeout: 30_000 }).toBeGreaterThan(20);
}

async function setFontSize(page: Page, value: "small" | "standard" | "large") {
  const labels = { small: "小字体", standard: "标准字体", large: "大字体" };
  if (page.url() === "about:blank") {
    await page.goto("/");
    await expect(page.getByRole("group", { name: "字体大小" })).toBeVisible();
  }
  await page.getByRole("button", { name: labels[value] }).click();
  await expect(page.locator("html")).toHaveAttribute("data-font-size", value);
}

async function apiJson(page: Page, path: string) {
  const response = await page.request.get(`${apiBase}${path}`);
  expect(response.ok()).toBe(true);
  return response.json();
}

async function clearDrawings(page: Page, chart: Locator) {
  const clear = page.getByRole("button", { name: "清除画线（全部）", exact: true });
  await clear.scrollIntoViewIfNeeded();
  await clear.click();
  await expect(chart).toHaveAttribute("data-drawings", "0");
}

async function drawFibonacciByClicks(page: Page, box: NonNullable<Awaited<ReturnType<Locator["boundingBox"]>>>) {
  const start = { x: box.x + 250, y: box.y + 340 };
  const end = { x: box.x + 700, y: box.y + 160 };
  await page.mouse.click(start.x, start.y);
  await page.mouse.move(end.x, end.y, { steps: 6 });
  await page.mouse.click(end.x, end.y);
  return { start, end, middle: { x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 } };
}

async function drawingBounds(overlay: Locator) {
  return overlay.evaluate((canvas: HTMLCanvasElement) => {
    const data = canvas.getContext("2d")!.getImageData(0, 0, canvas.width, canvas.height).data;
    let minX = canvas.width;
    let maxX = -1;
    let minY = canvas.height;
    let maxY = -1;
    let pixels = 0;
    for (let index = 3; index < data.length; index += 4) {
      if (!data[index]) continue;
      pixels += 1;
      const point = (index - 3) / 4;
      const x = point % canvas.width;
      const y = Math.floor(point / canvas.width);
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
    }
    return { min_x: minX, max_x: maxX, min_y: minY, max_y: maxY, pixels, canvas_width: canvas.width, canvas_height: canvas.height };
  });
}

async function canvasSignature(overlay: Locator) {
  return overlay.evaluate((canvas: HTMLCanvasElement) => canvas.toDataURL());
}

async function tableCodes(page: Page) {
  return (await page.locator(".candidate-table tbody .code-cell").allTextContents()).map(value => value.trim());
}

async function horizontalOverflow(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
}

async function criticalTextOverflows(page: Page) {
  return page.evaluate(() => {
    const selectors = [
      ".filter-control",
      ".filter-control *",
      ".top-card > span",
      ".top-card h1",
      ".progress-ring b",
      ".progress-ring span",
      ".top-card p",
      ".pattern-copy",
      ".pattern-copy > span",
      ".pattern-copy strong",
      ".pattern-metric small",
      ".stock-snapshot *",
      ".workspace-resize-controls *",
      ".font-size-control button",
      ".detail-actions > *",
    ];
    return [...document.querySelectorAll<HTMLElement>(selectors.join(","))]
      .filter(element => {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        const readableText = (element.textContent || element.getAttribute("aria-label") || "").trim();
        return readableText.length > 0
          && rect.width > 0
          && rect.height > 0
          && style.display !== "none"
          && style.visibility !== "hidden";
      })
      .filter(element => element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1)
      .map(element => ({
        tag: element.tagName,
        class: element.className,
        text: (element.textContent || element.getAttribute("aria-label") || "").trim().slice(0, 80),
        client: [element.clientWidth, element.clientHeight],
        scroll: [element.scrollWidth, element.scrollHeight],
      }));
  });
}

async function detailTextOverflows(page: Page) {
  return page.locator(".detail-card").evaluate(card => {
    const selectors = [
      ".reading-head *",
      ".detail-pattern-match > div:first-child > *",
      ".detail-pattern-match li",
      ".metric-facts span",
      ".metric-facts small",
      ".metric-facts b",
      ".detail-actions > *",
    ];
    return [...card.querySelectorAll<HTMLElement>(selectors.join(","))]
      .filter(element => {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        const readableText = (element.textContent || element.getAttribute("aria-label") || "").trim();
        return readableText.length > 0
          && rect.width > 0
          && rect.height > 0
          && style.display !== "none"
          && style.visibility !== "hidden";
      })
      .filter(element => element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1)
      .map(element => ({
        tag: element.tagName,
        class: element.className,
        text: (element.textContent || element.getAttribute("aria-label") || "").trim().slice(0, 80),
        client: [element.clientWidth, element.clientHeight],
        scroll: [element.scrollWidth, element.scrollHeight],
      }));
  });
}

async function revealLastTableColumn(page: Page) {
  return page.locator(".table-wrap").evaluate(element => {
    const wrap = element as HTMLElement;
    wrap.scrollLeft = wrap.scrollWidth;
    const bounds = wrap.getBoundingClientRect();
    const last = wrap.querySelector("th:last-child")!.getBoundingClientRect();
    return {
      client_width: wrap.clientWidth,
      scroll_width: wrap.scrollWidth,
      scroll_left: wrap.scrollLeft,
      last_header_visible: last.left >= bounds.left - 1 && last.right <= bounds.right + 1,
    };
  });
}

async function fullyInteractable(control: Locator) {
  return control.evaluate(element => {
    const rect = element.getBoundingClientRect();
    let visible = { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom };
    let ancestor = element.parentElement;
    while (ancestor) {
      const style = getComputedStyle(ancestor);
      if (style.overflow !== "visible" || style.overflowX !== "visible" || style.overflowY !== "visible") {
        const bounds = ancestor.getBoundingClientRect();
        visible = {
          left: Math.max(visible.left, bounds.left),
          top: Math.max(visible.top, bounds.top),
          right: Math.min(visible.right, bounds.right),
          bottom: Math.min(visible.bottom, bounds.bottom),
        };
      }
      ancestor = ancestor.parentElement;
    }
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const hit = document.elementFromPoint(centerX, centerY);
    return visible.right - visible.left >= rect.width - 1
      && visible.bottom - visible.top >= rect.height - 1
      && Boolean(hit && (hit === element || element.contains(hit)));
  });
}

async function withinViewport(locator: Locator) {
  return locator.evaluate(element => {
    const rect = element.getBoundingClientRect();
    return rect.left >= 0 && rect.top >= 0 && rect.right <= window.innerWidth && rect.bottom <= window.innerHeight;
  });
}

async function boardGeometry(page: Page) {
  return page.evaluate(() => {
    const candidate = document.querySelector(".candidate-card")!.getBoundingClientRect();
    const detail = document.querySelector(".detail-card")!.getBoundingClientRect();
    const workspace = document.querySelector(".board-workspace")!.getBoundingClientRect();
    return {
      candidate_width: candidate.width,
      candidate_height: candidate.height,
      detail_width: detail.width,
      detail_height: detail.height,
      workspace_width: workspace.width,
      workspace_height: workspace.height,
    };
  });
}

async function visibleBox(locator: Locator) {
  const box = await locator.boundingBox();
  if (!box) throw new Error("Expected element to have a visible bounding box");
  return box;
}

function audit(page: Page) {
  const errors: string[] = [];
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  page.on("pageerror", error => errors.push(error.message));
  return errors;
}
