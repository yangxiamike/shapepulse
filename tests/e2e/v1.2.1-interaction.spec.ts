import { mkdir, writeFile } from "node:fs/promises";
import { expect, test, type Locator, type Page } from "@playwright/test";

const screenshotDir = "docs/qa/screenshots/v1.2.1";
const evidenceDir = "docs/qa/evidence/v1.2.1";
const evidence: Array<Record<string, unknown>> = [];

test.describe.serial("v1.2.1 interaction acceptance", () => {
  test.beforeAll(async () => {
    await mkdir(screenshotDir, { recursive: true });
    await mkdir(evidenceDir, { recursive: true });
  });

  test.afterAll(async () => {
    await writeFile(`${evidenceDir}/browser-results.json`, `${JSON.stringify({ captured_at: new Date().toISOString(), results: evidence }, null, 2)}\n`, "utf8");
  });

  test("page is unlocked and every drawing tool produces an editable distinct shape", async ({ page }) => {
    test.setTimeout(180_000);
    const errors = audit(page);
    await page.setViewportSize({ width: 1600, height: 1000 });
    await openMarket(page);

    const chart = page.locator(".market-chart").first();
    const overlay = chart.locator("canvas.drawing-overlay");
    await expect(chart).toHaveAttribute("data-drawing-mode", "pan");
    await expect(overlay).toHaveCSS("pointer-events", "none");
    const chartBox = await overlay.boundingBox();
    if (!chartBox) throw new Error("drawing overlay is not visible");
    expect(await page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.classList.contains("drawing-overlay"), { x: chartBox.x + chartBox.width / 2, y: chartBox.y + chartBox.height / 2 })).toBe(false);
    const nativeCanvases = chart.locator("canvas:not(.drawing-overlay)");
    expect(await nativeCanvases.count()).toBeGreaterThan(0);
    const beforeNativeMove = await canvasStackSignature(nativeCanvases);
    await page.mouse.move(chartBox.x + chartBox.width * 0.55, chartBox.y + chartBox.height * 0.45);
    await expect.poll(() => canvasStackSignature(nativeCanvases)).not.toEqual(beforeNativeMove);
    const beforeNativeWheel = await canvasStackSignature(nativeCanvases);
    await page.mouse.wheel(0, -220);
    await expect.poll(() => canvasStackSignature(nativeCanvases)).not.toEqual(beforeNativeWheel);
    const beforeNativePan = await canvasStackSignature(nativeCanvases);
    await page.mouse.down();
    await page.mouse.move(chartBox.x + chartBox.width * 0.42, chartBox.y + chartBox.height * 0.45, { steps: 6 });
    await page.mouse.up();
    await expect.poll(() => canvasStackSignature(nativeCanvases)).not.toEqual(beforeNativePan);

    await page.getByRole("button", { name: "周K", exact: true }).click();
    await expect(page.getByRole("button", { name: "周K", exact: true })).toHaveClass(/active/);
    await page.getByRole("button", { name: "日K", exact: true }).click();
    for (const tab of ["详情", "形态", "指标", "因子", "自选"]) {
      await page.getByRole("button", { name: tab, exact: true }).click();
      await expect(page.getByRole("button", { name: tab, exact: true })).toHaveClass(/active/);
    }

    await page.getByLabel("画线颜色").fill("#e11d48");
    await page.getByLabel("画线线宽").selectOption("4");
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
    const signatures: string[] = [];
    for (const [label, kind] of tools) {
      await page.getByRole("button", { name: label, exact: true }).click();
      if (kind === "text") await page.getByLabel("标注文本").fill("突破位");
      await mouseDraw(page, chartBox, kind === "freehand" ? 14 : 5);
      await expect(chart).toHaveAttribute("data-drawings", "1");
      await expect(chart).toHaveAttribute("data-drawing-kinds", kind);
      await expect(chart).toHaveAttribute("data-drawing-styles", "#e11d48:4");
      signatures.push(await canvasSignature(overlay));
      await page.getByRole("button", { name: "清除画线（全部）" }).click();
      await expect(chart).toHaveAttribute("data-drawings", "0");
    }
    expect(new Set(signatures).size).toBe(tools.length);

    await page.getByRole("button", { name: "线段", exact: true }).click();
    await mouseDraw(page, chartBox, 5);
    const beforeStyle = await canvasSignature(overlay);
    await page.getByLabel("画线颜色").fill("#16a34a");
    await page.getByLabel("画线线宽").selectOption("5");
    await expect(chart).toHaveAttribute("data-drawing-styles", "#16a34a:5");
    await expect.poll(() => canvasSignature(overlay)).not.toBe(beforeStyle);

    const start = { x: chartBox.x + 160, y: chartBox.y + 160 };
    await page.mouse.move(start.x, start.y);
    await expect.poll(() => overlay.evaluate(canvas => canvas.style.cursor)).toBe("nwse-resize");
    await expect(overlay).toHaveAttribute("data-hit-target", "start");
    const beforeEndpoint = await canvasSignature(overlay);
    await page.mouse.down();
    await page.mouse.move(start.x + 30, start.y - 30, { steps: 5 });
    await page.mouse.up();
    await expect.poll(() => canvasSignature(overlay)).not.toBe(beforeEndpoint);

    const movedStart = { x: start.x + 30, y: start.y - 30 };
    const end = { x: chartBox.x + 420, y: chartBox.y + 300 };
    const middle = { x: (movedStart.x + end.x) / 2, y: (movedStart.y + end.y) / 2 };
    await page.mouse.move(middle.x, middle.y);
    await expect.poll(() => overlay.evaluate(canvas => canvas.style.cursor)).toBe("grab");
    await expect(overlay).toHaveAttribute("data-hit-target", "move");
    const beforeMove = await canvasSignature(overlay);
    await page.mouse.down();
    await page.mouse.move(middle.x + 35, middle.y + 20, { steps: 5 });
    await page.mouse.up();
    await expect.poll(() => canvasSignature(overlay)).not.toBe(beforeMove);
    await page.keyboard.press("Delete");
    await expect(chart).toHaveAttribute("data-drawings", "0");

    await page.getByRole("button", { name: "曲线", exact: true }).click();
    await mouseDraw(page, chartBox, 6, { x1: 180, y1: 270, x2: 480, y2: 360 });
    const control = { x: chartBox.x + 330, y: chartBox.y + 222 };
    await page.mouse.move(control.x, control.y);
    await expect.poll(() => overlay.evaluate(canvas => canvas.style.cursor)).toBe("grab");
    await expect(overlay).toHaveAttribute("data-hit-target", "control");
    const beforeControl = await canvasSignature(overlay);
    await page.mouse.down();
    await page.mouse.move(control.x + 20, control.y - 24, { steps: 4 });
    await page.mouse.up();
    await expect.poll(() => canvasSignature(overlay)).not.toBe(beforeControl);
    await page.getByRole("button", { name: "删除所选" }).click();
    await expect(chart).toHaveAttribute("data-drawings", "0");

    await page.getByRole("button", { name: "斐波那契扩展", exact: true }).click();
    await mouseDraw(page, chartBox, 6);
    await page.screenshot({ path: `${screenshotDir}/market-1600-drawing-system.png`, animations: "disabled", caret: "hide" });
    expect(errors).toEqual([]);
    evidence.push({ gate: "G1-G2", unlocked_overlay: true, native_chart: { crosshair: true, wheel_zoom: true, drag_pan: true }, drawing_kinds: tools.map(([, kind]) => kind), unique_canvas_signatures: signatures.length, style: { color: "#16a34a", line_width: 5 }, endpoint_cursor: "nwse-resize", move_cursor: "grab", curve_control: true, result: "pass" });
  });

  test("pattern navigation, rightbar folding and divider stay responsive", async ({ page }) => {
    test.setTimeout(150_000);
    const errors = audit(page);
    await page.setViewportSize({ width: 1600, height: 1000 });
    await page.goto("/market?code=002747&category=pullback");
    await expect(page.getByRole("heading", { name: "埃斯顿" })).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => new URL(page.url()).searchParams.get("category")).toBe("pullback");
    await page.getByRole("button", { name: "周K", exact: true }).click();
    await page.getByRole("button", { name: /图布局/ }).click();
    await page.getByRole("button", { name: "2 图", exact: true }).click();
    await page.getByRole("button", { name: "形态", exact: true }).click();

    await expect(page.getByText("形态股票列表", { exact: true })).toBeVisible();
    await expect(page.getByText("当前个股形态事实", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "交易", exact: true })).toHaveCount(0);
    const pool = page.getByTestId("pattern-pool");
    await expect(pool.locator("button").first()).toBeVisible({ timeout: 30_000 });
    await pool.locator("button").first().click();
    const firstCode = await activePoolCode(pool);
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await expect.poll(() => activePoolCode(pool)).not.toBe(firstCode);
    const keyboardCode = await activePoolCode(pool);
    await expect(page.getByRole("button", { name: "周K", exact: true })).toHaveClass(/active/);
    await expect(page.locator(".chart-pane")).toHaveCount(2);
    await expect(page.getByTestId("pattern-group-select")).toHaveValue("pullback");
    await expect.poll(() => new URL(page.url()).searchParams.get("category")).toBe("pullback");

    const poolBox = await pool.boundingBox();
    if (!poolBox) throw new Error("pattern pool is not visible");
    await page.mouse.move(poolBox.x + poolBox.width / 2, poolBox.y + poolBox.height / 2);
    const wheelStarted = performance.now();
    await page.mouse.wheel(0, 180);
    await expect.poll(() => activePoolCode(pool)).not.toBe(keyboardCode);
    const wheelFeedbackMs = performance.now() - wheelStarted;
    const activeButton = pool.locator("button[aria-current=true]");
    expect(await activeButton.evaluate(button => {
      const item = button.getBoundingClientRect();
      const bounds = button.parentElement!.getBoundingClientRect();
      return item.top >= bounds.top - 1 && item.bottom <= bounds.bottom + 1;
    })).toBe(true);

    const divider = page.getByTestId("market-right-resizer");
    await expect(divider).toBeVisible();
    const beforeWidth = Number(await divider.getAttribute("aria-valuenow"));
    const dividerBox = await divider.boundingBox();
    if (!dividerBox) throw new Error("market divider is not visible");
    await installSeparatorTiming(divider);
    await page.mouse.move(dividerBox.x + dividerBox.width / 2, dividerBox.y + 240);
    await page.mouse.down();
    await page.mouse.move(dividerBox.x - 70, dividerBox.y + 240, { steps: 8 });
    await page.mouse.up();
    await expect.poll(async () => Number(await divider.getAttribute("aria-valuenow"))).toBeGreaterThan(beforeWidth + 40);
    const rightResizeFeedbackMs = Number(await divider.getAttribute("data-feedback-ms"));

    const menu = page.getByRole("button", { name: "折叠或展开右侧栏" });
    await page.evaluate(() => {
      type PerfWindow = Window & { __rightbarPerf?: { start: number; feedback: number } };
      const target = window as PerfWindow;
      target.__rightbarPerf = { start: 0, feedback: 0 };
      const shell = document.querySelector(".market-shell")!;
      const button = document.querySelector<HTMLButtonElement>('button[aria-label="折叠或展开右侧栏"]')!;
      button.addEventListener("pointerdown", () => { target.__rightbarPerf!.start = performance.now(); }, { once: true });
      const observer = new MutationObserver(() => {
        if (shell.getAttribute("data-rightbar-state") === "collapsed" && target.__rightbarPerf!.start) {
          target.__rightbarPerf!.feedback = performance.now() - target.__rightbarPerf!.start;
          observer.disconnect();
        }
      });
      observer.observe(shell, { attributes: true, attributeFilter: ["data-rightbar-state"] });
    });
    await menu.click();
    await expect(page.locator(".market-shell")).toHaveAttribute("data-rightbar-state", "collapsed");
    const collapseFeedbackMs = await page.evaluate(() => (window as Window & { __rightbarPerf?: { feedback: number } }).__rightbarPerf?.feedback || 0);
    await expect(page.locator(".market-rightbar")).toBeHidden();
    await menu.click();
    await expect(page.locator(".market-shell")).toHaveAttribute("data-rightbar-state", "expanded");
    await expect(page.locator(".market-rightbar")).toBeVisible();
    await page.screenshot({ path: `${screenshotDir}/market-1600-rightbar-resized.png`, animations: "disabled", caret: "hide" });

    expect(wheelFeedbackMs).toBeLessThanOrEqual(1000);
    expect(collapseFeedbackMs).toBeLessThanOrEqual(100);
    expect(rightResizeFeedbackMs).toBeLessThanOrEqual(250);
    expect(errors).toEqual([]);
    evidence.push({ gate: "G3-G5", keyboard_code: keyboardCode, wheel_feedback_ms: round(wheelFeedbackMs), collapse_feedback_ms: round(collapseFeedbackMs), rightbar_resize: { before: beforeWidth, after: Number(await divider.getAttribute("aria-valuenow")), feedback_ms: round(rightResizeFeedbackMs) }, context: { period: "W", layout: 2, category: "pullback" }, result: "pass" });
  });

  test("board readability, complete Top K semantics and both responsive layouts", async ({ page }) => {
    test.setTimeout(180_000);
    const errors = audit(page);
    const viewports = [{ width: 1600, height: 1000 }, { width: 1366, height: 900 }, { width: 1024, height: 800 }];
    await page.setViewportSize(viewports[0]);
    await openBoard(page);
    await expect(page.getByRole("spinbutton", { name: "Top K" })).toHaveValue("50");
    const firstViewCodes = await tableCodes(page);
    expect(firstViewCodes.length).toBeLessThanOrEqual(9);
    const expand = page.locator(".view-all-button");
    if (await expand.isVisible()) await expand.click();
    const completeCodes = await tableCodes(page);
    expect(completeCodes.length).toBeGreaterThanOrEqual(firstViewCodes.length);
    expect(completeCodes.slice(0, firstViewCodes.length)).toEqual(firstViewCodes);
    await expect(page.getByRole("spinbutton", { name: "Top K" })).toHaveValue("50");

    const rowReadability = await page.locator(".candidate-table tbody tr").first().evaluate(row => {
      const cell = row.querySelector("td")!;
      return { row_height: row.getBoundingClientRect().height, font_size: Number.parseFloat(getComputedStyle(cell).fontSize) };
    });
    expect(rowReadability.row_height).toBeGreaterThanOrEqual(50);
    expect(rowReadability.font_size).toBeGreaterThanOrEqual(14);

    const boardDivider = page.getByTestId("board-workspace-resizer");
    await expect(boardDivider).toBeVisible();
    const beforeDetail = Number(await page.locator(".board-workspace").getAttribute("data-detail-width"));
    const boardDividerBox = await boardDivider.boundingBox();
    if (!boardDividerBox) throw new Error("board divider is not visible");
    await installSeparatorTiming(boardDivider);
    await page.mouse.move(boardDividerBox.x + 5, boardDividerBox.y + 220);
    await page.mouse.down();
    await page.mouse.move(boardDividerBox.x - 70, boardDividerBox.y + 220, { steps: 8 });
    await page.mouse.up();
    await expect.poll(async () => Number(await page.locator(".board-workspace").getAttribute("data-detail-width"))).toBeGreaterThan(beforeDetail + 40);
    const boardResizeFeedbackMs = Number(await boardDivider.getAttribute("data-feedback-ms"));
    expect(boardResizeFeedbackMs).toBeLessThanOrEqual(250);
    expect(await tableCodes(page)).toEqual(completeCodes);
    await page.screenshot({ path: `${screenshotDir}/board-1600-resized.png`, fullPage: true, animations: "disabled", caret: "hide" });

    for (const viewport of viewports) {
      await page.setViewportSize(viewport);
      await openBoard(page);
      await expect.poll(async () => Number(await page.locator(".detail-chart .market-chart").getAttribute("data-source-bars"))).toBeGreaterThan(0);
      expect(await horizontalOverflow(page)).toBe(false);
      if (viewport.width > 1100) await expect(page.getByTestId("board-workspace-resizer")).toBeVisible();
      else {
        await expect(page.getByTestId("board-workspace-resizer")).toBeVisible();
        await expect(page.getByTestId("board-workspace-resizer")).toHaveAttribute("aria-orientation", "horizontal");
        const candidate = await page.locator(".candidate-card").boundingBox();
        const detail = await page.locator(".detail-card").boundingBox();
        expect(candidate && detail ? detail.y >= candidate.y + candidate.height : false).toBe(true);
      }
      for (const control of [page.getByRole("button", { name: "待判断", exact: true }), page.getByRole("link", { name: "打开行情" })]) {
        await control.scrollIntoViewIfNeeded();
        expect(await fullyInteractable(control)).toBe(true);
      }
      await page.screenshot({ path: `${screenshotDir}/board-${viewport.width}.png`, fullPage: true, animations: "disabled", caret: "hide" });

      await page.goto("/market?code=002747&category=pullback");
      await expect(page.getByRole("heading", { name: "埃斯顿" })).toBeVisible({ timeout: 30_000 });
      if (viewport.width <= 1100) await page.getByRole("button", { name: "打开右侧面板" }).click();
      await page.getByRole("button", { name: "形态", exact: true }).click();
      await expect(page.getByTestId("pattern-pool").locator("button").first()).toBeVisible({ timeout: 30_000 });
      await expect(page.locator(".pattern-facts .pattern-panel, .pattern-facts .pattern-empty").first()).toBeVisible({ timeout: 30_000 });
      expect(await horizontalOverflow(page)).toBe(false);
      await page.screenshot({ path: `${screenshotDir}/market-${viewport.width}.png`, animations: "disabled", caret: "hide" });
    }

    expect(errors).toEqual([]);
    evidence.push({ gate: "G4-G6", top_k: 50, complete_code_count: completeCodes.length, first_view_count: firstViewCodes.length, readability: rowReadability, board_resize_feedback_ms: round(boardResizeFeedbackMs), controls_fully_interactable: true, viewports, result: "pass" });
  });
});

async function openMarket(page: Page) {
  await page.goto("/market?code=002747");
  await expect(page.getByRole("heading", { name: "埃斯顿" })).toBeVisible({ timeout: 30_000 });
}

async function openBoard(page: Page) {
  await page.goto("/");
  await expect(page.locator(".candidate-table tbody tr").first()).toBeVisible({ timeout: 30_000 });
}

async function mouseDraw(page: Page, box: NonNullable<Awaited<ReturnType<Locator["boundingBox"]>>>, steps: number, points = { x1: 160, y1: 160, x2: 420, y2: 300 }) {
  await page.mouse.move(box.x + points.x1, box.y + points.y1);
  await page.mouse.down();
  await page.mouse.move(box.x + points.x2, box.y + points.y2, { steps });
  await page.mouse.up();
}

async function canvasSignature(overlay: Locator) {
  return overlay.evaluate((canvas: HTMLCanvasElement) => canvas.toDataURL());
}

async function canvasStackSignature(canvases: Locator) {
  return canvases.evaluateAll(items => items.map(canvas => (canvas as HTMLCanvasElement).toDataURL()));
}

async function installSeparatorTiming(separator: Locator) {
  await separator.evaluate(element => {
    delete element.dataset.feedbackMs;
    let startedAt = 0;
    const observer = new MutationObserver(() => {
      if (!startedAt || element.dataset.feedbackMs) return;
      element.dataset.feedbackMs = String(performance.now() - startedAt);
      observer.disconnect();
    });
    observer.observe(element, { attributes: true, attributeFilter: ["aria-valuenow"] });
    element.addEventListener("pointerdown", () => {
      startedAt = performance.now();
    }, { once: true });
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

async function activePoolCode(pool: Locator) {
  return (await pool.locator("button[aria-current=true] small").innerText()).trim();
}

async function tableCodes(page: Page) {
  return (await page.locator(".candidate-table tbody .code-cell").allTextContents()).map(value => value.trim());
}

function audit(page: Page) {
  const errors: string[] = [];
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  page.on("pageerror", error => errors.push(error.message));
  return errors;
}

async function horizontalOverflow(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
}

function round(value: number) {
  return Math.round(value * 10) / 10;
}
