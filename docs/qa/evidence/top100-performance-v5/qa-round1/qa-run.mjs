import { chromium } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const evidenceDir = path.dirname(fileURLToPath(import.meta.url));
const baseUrl = "http://localhost:3106";
const chromePath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const viewports = [
  { name: "1900x956", width: 1900, height: 956 },
  { name: "1440x900", width: 1440, height: 900 },
  { name: "1024x768", width: 1024, height: 768 },
  { name: "390x844", width: 390, height: 844 },
];
const routes = [
  { name: "breadth", url: "/template-breadth-v3" },
  { name: "templates", url: "/templates" },
  { name: "new-template", url: "/templates/new" },
  {
    name: "market",
    url: "/market?code=301234&template=fresh_breakout&from=breadth&industry=801080&window=20",
  },
];

const browser = await chromium.launch({ headless: true, executablePath: chromePath });
const results = {
  generatedAt: new Date().toISOString(),
  baseUrl,
  viewports: [],
  interactions: {},
};

async function settle(page, routeName) {
  const deadline = Date.now() + (routeName === "market" ? 12000 : 7000);
  while (Date.now() < deadline) {
    const busy = await page
      .getByText(/加载中|读取中|正在读取|计算中/)
      .count()
      .catch(() => 0);
    if (!busy) break;
    await page.waitForTimeout(250);
  }
  await page.waitForTimeout(500);
}

function wireEvents(page, errors, responses) {
  page.on("console", (message) => {
    if (["warning", "error"].includes(message.type())) {
      errors.push({ kind: "console", level: message.type(), text: message.text(), url: page.url() });
    }
  });
  page.on("pageerror", (error) => {
    errors.push({ kind: "pageerror", text: String(error), url: page.url() });
  });
  page.on("response", (response) => {
    responses.push({
      status: response.status(),
      url: response.url(),
      contentType: response.headers()["content-type"] || "",
    });
    if (response.status() >= 400) {
      errors.push({ kind: "http", status: response.status(), url: response.url() });
    }
  });
}

for (const viewport of viewports) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  const viewportResult = { ...viewport, routes: [] };
  for (const route of routes) {
    const page = await context.newPage();
    const errors = [];
    const responses = [];
    wireEvents(page, errors, responses);
    const startedAt = Date.now();
    const response = await page.goto(`${baseUrl}${route.url}`, { waitUntil: "domcontentloaded" });
    const domContentLoadedMs = Date.now() - startedAt;
    await settle(page, route.name);
    const settledMs = Date.now() - startedAt;
    const bodyText = await page.locator("body").innerText();
    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      scrollHeight: document.documentElement.scrollHeight,
      clientHeight: document.documentElement.clientHeight,
    }));
    const controls = await page.locator("button, a, input").evaluateAll((elements) =>
      elements.slice(0, 160).map((element) => ({
        tag: element.tagName.toLowerCase(),
        text: (element.textContent || "").trim().replace(/\s+/g, " ").slice(0, 120),
        ariaLabel: element.getAttribute("aria-label"),
        href: element.getAttribute("href"),
        disabled: "disabled" in element ? element.disabled : false,
      })),
    );
    const navTiming = await page.evaluate(() => {
      const nav = performance.getEntriesByType("navigation")[0];
      return nav
        ? {
            responseStart: Math.round(nav.responseStart),
            domContentLoaded: Math.round(nav.domContentLoadedEventEnd),
            loadEvent: Math.round(nav.loadEventEnd),
            transferSize: nav.transferSize,
            decodedBodySize: nav.decodedBodySize,
          }
        : null;
    });
    const screenshot = `${route.name}-${viewport.name}.png`;
    await page.screenshot({ path: path.join(evidenceDir, screenshot), fullPage: true });
    const viewportScreenshot = `${route.name}-${viewport.name}-viewport.png`;
    await page.screenshot({ path: path.join(evidenceDir, viewportScreenshot), fullPage: false });
    viewportResult.routes.push({
      route: route.name,
      url: page.url(),
      status: response?.status() ?? null,
      domContentLoadedMs,
      settledMs,
      navTiming,
      overflow,
      errors,
      failedResponses: responses.filter((item) => item.status >= 400),
      responseCount: responses.length,
      controls,
      bodyText: bodyText.slice(0, 16000),
      screenshot,
      viewportScreenshot,
    });
    await page.close();
  }
  results.viewports.push(viewportResult);
  await context.close();
}

const context = await browser.newContext({ viewport: { width: 1900, height: 956 } });

{
  const page = await context.newPage();
  const errors = [];
  const responses = [];
  wireEvents(page, errors, responses);
  const t0 = Date.now();
  await page.goto(`${baseUrl}/template-breadth-v3`, { waitUntil: "domcontentloaded" });
  const treemapVisibleMs = Date.now() - t0;
  await page.locator("[data-industry-code]").first().waitFor({ state: "visible" });
  const treemapActionableMs = Date.now() - t0;
  const tiles = await page.locator("[data-industry-code]").evaluateAll((elements) =>
    elements.map((element) => {
      const box = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return {
        code: element.getAttribute("data-industry-code"),
        count: Number(element.getAttribute("data-count")),
        direction: element.getAttribute("data-direction"),
        text: (element.textContent || "").trim().replace(/\s+/g, " "),
        box: { x: box.x, y: box.y, width: box.width, height: box.height },
        background: style.backgroundColor,
        color: style.color,
        textAlign: style.textAlign,
      };
    }),
  );
  const before20 = Object.fromEntries(tiles.map((tile) => [tile.code, tile.box]));
  await page.getByRole("button", { name: "20日", exact: true }).click();
  await page.waitForTimeout(300);
  const after20 = Object.fromEntries(
    await page.locator("[data-industry-code]").evaluateAll((elements) =>
      elements.map((element) => {
        const box = element.getBoundingClientRect();
        return [
          element.getAttribute("data-industry-code"),
          { x: box.x, y: box.y, width: box.width, height: box.height },
        ];
      }),
    ),
  );
  const otherTile = page.locator("[data-industry-code='other']");
  const detailsBefore = responses.filter((item) => item.url.includes("template-breadth-v3-details")).length;
  await otherTile.click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(evidenceDir, "breadth-other-expanded-1900x956.png"), fullPage: true });
  const detailsAfter = responses.filter((item) => item.url.includes("template-breadth-v3-details")).length;
  const text = await page.locator("body").innerText();
  results.interactions.breadth = {
    treemapVisibleMs,
    treemapActionableMs,
    tileCount: tiles.length,
    top100Total: tiles.reduce((sum, tile) => sum + tile.count, 0),
    tiles,
    geometryStableAfter20: JSON.stringify(before20) === JSON.stringify(after20),
    window20TextPresent: text.includes("2026-07-29 vs 2026-07-01"),
    otherExpanded: /“其他行业”具体构成/.test(text),
    otherHasStocks: /当前入选股票/.test(text),
    otherHasNewRetainedExit: /新进入[\s\S]*保留[\s\S]*退出/.test(text),
    otherHasSeries: /行业 Top100 数量时间序列/.test(text),
    otherComponentCount: await page.locator("section").filter({ hasText: "“其他行业”具体构成" }).locator("li").count().catch(() => null),
    detailRequestsBeforeClick: detailsBefore,
    detailRequestsAfterClick: detailsAfter,
    errors,
  };
  await page.close();
}

{
  const page = await context.newPage();
  const errors = [];
  const responses = [];
  wireEvents(page, errors, responses);
  const t0 = Date.now();
  await page.goto(`${baseUrl}/templates`, { waitUntil: "domcontentloaded" });
  const shellMs = Date.now() - t0;
  await settle(page, "templates");
  const text = await page.locator("body").innerText();
  const rows = page.locator("table tbody tr, [data-template-candidate]");
  const rowCount = await rows.count();
  const svgCount = await page.locator("svg").count();
  const canvases = await page.locator("canvas").count();
  const links = await page.locator("a").evaluateAll((elements) =>
    elements.map((element) => ({
      text: (element.textContent || "").trim().replace(/\s+/g, " ").slice(0, 100),
      href: element.getAttribute("href"),
    })),
  );
  const firstMarketLink = links.find((link) => link.href?.startsWith("/market?"));
  const candidateLinkCount = links.filter((link) => link.href?.startsWith("/market?")).length;
  let rowNavigation = null;
  if (firstMarketLink) {
    const href = firstMarketLink.href;
    rowNavigation = { href, hasTemplate: href.includes("template=") };
  }
  results.interactions.templates = {
    shellMs,
    settledMs: Date.now() - t0,
    rowCount,
    candidateLinkCount,
    svgCount,
    canvases,
    hasTop100Copy: /Top100/.test(text),
    hasRealKlineCopy: /真实|K线/.test(text),
    firstMarketLink: rowNavigation,
    rankingRequests: responses.filter((item) => item.url.includes("candidates") || item.url.includes("rank")).map((item) => item.url),
    barsRequests: responses.filter((item) => item.url.includes("/bars")).length,
    errors,
  };
  await page.close();
}

{
  const page = await context.newPage();
  const errors = [];
  const responses = [];
  wireEvents(page, errors, responses);
  const t0 = Date.now();
  await page.goto(`${baseUrl}/templates/new`, { waitUntil: "domcontentloaded" });
  await settle(page, "new-template");
  const initialText = await page.locator("body").innerText();
  const searchInput = page.getByRole("combobox", { name: "搜索股票" });
  await searchInput.fill("000001");
  await page.getByRole("listbox").waitFor({ state: "visible" });
  await page.getByRole("option").first().click();
  const focusTarget = page.getByTestId("focus-kline");
  await focusTarget.waitFor({ state: "visible", timeout: 15000 });
  const allButtons = await page.getByRole("button").allTextContents();
  const svgs = await page.locator("svg").count();
  const focusBox = await focusTarget.boundingBox();
  const stateBefore = await focusTarget.evaluate((element) => ({
    viewStart: element.getAttribute("data-view-start"),
    viewEnd: element.getAttribute("data-view-end"),
    selectionStart: element.getAttribute("data-selection-start"),
    selectionEnd: element.getAttribute("data-selection-end"),
  }));
  let wheelChanged = false;
  let dragChanged = false;
  if (focusBox) {
    await page.mouse.move(focusBox.x + focusBox.width / 2, focusBox.y + focusBox.height / 2);
    await page.mouse.wheel(0, -500);
    await page.waitForTimeout(250);
    const afterWheel = await focusTarget.evaluate((element) => ({
      viewStart: element.getAttribute("data-view-start"),
      viewEnd: element.getAttribute("data-view-end"),
    }));
    wheelChanged = stateBefore.viewStart !== afterWheel.viewStart || stateBefore.viewEnd !== afterWheel.viewEnd;
    await page.mouse.move(focusBox.x + focusBox.width * 0.12, focusBox.y + focusBox.height * 0.18);
    await page.mouse.down();
    await page.mouse.move(focusBox.x + focusBox.width * 0.35, focusBox.y + focusBox.height * 0.18, { steps: 6 });
    await page.mouse.up();
    await page.waitForTimeout(250);
    const afterDrag = await focusTarget.evaluate((element) => ({
      viewStart: element.getAttribute("data-view-start"),
      viewEnd: element.getAttribute("data-view-end"),
    }));
    dragChanged = afterWheel.viewStart !== afterDrag.viewStart || afterWheel.viewEnd !== afterDrag.viewEnd;
  }
  const overview = page.getByTestId("history-overview");
  const overviewViewport = page.getByTestId("overview-viewport");
  const overviewBefore = await overviewViewport.getAttribute("x");
  const overviewBox = await overview.boundingBox();
  if (overviewBox) {
    await page.mouse.move(overviewBox.x + overviewBox.width * 0.75, overviewBox.y + overviewBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(overviewBox.x + overviewBox.width * 0.35, overviewBox.y + overviewBox.height / 2, { steps: 6 });
    await page.mouse.up();
    await page.waitForTimeout(250);
  }
  const overviewAfter = await overviewViewport.getAttribute("x");
  const sliders = page.locator("[role='slider']");
  const sliderCount = await sliders.count();
  const sliderStatesBefore = await sliders.evaluateAll((elements) =>
    elements.map((element) => ({
      label: element.getAttribute("aria-label"),
      now: element.getAttribute("aria-valuenow"),
      text: element.getAttribute("aria-valuetext"),
    })),
  );
  await sliders.first().focus();
  await page.keyboard.press("ArrowLeft");
  const stateAfterWindowMove = await focusTarget.evaluate((element) => ({
    selectionStart: element.getAttribute("data-selection-start"),
    selectionEnd: element.getAttribute("data-selection-end"),
  }));
  const endBoundary = sliders.nth(2);
  await endBoundary.focus();
  for (let i = 0; i < 41; i++) await page.keyboard.press("ArrowLeft");
  await page.waitForTimeout(100);
  const invalidText = await page.locator("body").innerText();
  const saveDisabledWhenInvalid = await page.getByRole("button", { name: "保存模板" }).isDisabled();
  await page.screenshot({ path: path.join(evidenceDir, "new-template-selected-1900x956.png"), fullPage: true });
  const selectedText = await page.locator("body").innerText();
  results.interactions.newTemplate = {
    settledMs: Date.now() - t0,
    svgCount: svgs,
    buttons: allButtons,
    hasOverviewFocusCopy: /总览/.test(selectedText) && /焦点/.test(selectedText),
    hasStartEndDates: /起始|开始/.test(selectedText) && /结束/.test(selectedText),
    hasTradingDayCount: /交易日/.test(selectedText),
    has20To240Hint: /20/.test(selectedText) && /240/.test(selectedText),
    wheelChangedViewRange: wheelChanged,
    backgroundDragChangedViewRange: dragChanged,
    overviewDragChangedViewport: overviewBefore !== overviewAfter,
    sliderCount,
    sliderStatesBefore,
    wholeWindowKeyboardMoved:
      stateBefore.selectionStart !== stateAfterWindowMove.selectionStart ||
      stateBefore.selectionEnd !== stateAfterWindowMove.selectionEnd,
    stateBefore,
    stateAfterWindowMove,
    invalidRangeShowsInlineHint: /至少选择 20 个实际交易日/.test(invalidText),
    saveDisabledWhenInvalid,
    screenshot: "new-template-selected-1900x956.png",
    errors,
  };
  await page.close();
}

{
  const page = await context.newPage();
  const errors = [];
  const responses = [];
  wireEvents(page, errors, responses);
  const t0 = Date.now();
  const url = `${baseUrl}/market?code=301234&template=fresh_breakout&from=breadth&industry=801080&window=20`;
  await page.goto(url, { waitUntil: "domcontentloaded" });
  const shellMs = Date.now() - t0;
  const body = page.locator("body");
  let stockVisibleMs = null;
  let mainKlineVisibleMs = null;
  let templateContextVisibleMs = null;
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    const text = await body.innerText();
    if (stockVisibleMs === null && /301234|五洲医疗/.test(text)) stockVisibleMs = Date.now() - t0;
    if (mainKlineVisibleMs === null && (await page.locator(".market-chart[data-bars]").evaluateAll((elements) => elements.some((element) => Number(element.getAttribute("data-bars")) > 0)))) mainKlineVisibleMs = Date.now() - t0;
    if (templateContextVisibleMs === null && (await page.getByTestId("template-stock-list").locator("button").count()) > 0) templateContextVisibleMs = Date.now() - t0;
    if (stockVisibleMs !== null && mainKlineVisibleMs !== null && templateContextVisibleMs !== null) break;
    await page.waitForTimeout(100);
  }
  await settle(page, "market");
  const initialUrl = page.url();
  const text = await body.innerText();
  const buttons = await page.getByRole("button").allTextContents();
  const links = await page.locator("a").evaluateAll((elements) =>
    elements.map((element) => ({
      text: (element.textContent || "").trim().replace(/\s+/g, " ").slice(0, 100),
      href: element.getAttribute("href"),
    })),
  );
  const beforeKeyboard = page.url();
  await page.keyboard.press("ArrowDown");
  await page.waitForTimeout(700);
  const afterKeyboard = page.url();
  const returnLink = links.find((link) => link.href?.startsWith("/template-breadth-v3?"))
    || links.find((link) => /返回/.test(link.text) || link.href?.includes("template-breadth"));
  const templateStockCount = await page.getByTestId("template-stock-list").locator("button").count();
  const candidateKlineCount = await page.locator(".template-kline-pair svg").count();
  const densityButton = page.getByRole("button", { name: /收起行情页顶部|展开行情页顶部/ });
  const densityBefore = await densityButton.getAttribute("aria-label");
  await densityButton.click();
  const densityAfter = await densityButton.getAttribute("aria-label");
  results.interactions.market = {
    shellMs,
    stockVisibleMs,
    mainKlineVisibleMs,
    templateContextVisibleMs,
    settledMs: Date.now() - t0,
    initialUrl,
    preservedFromBreadth: initialUrl.includes("from=breadth") && initialUrl.includes("industry=801080") && initialUrl.includes("window=20"),
    templateStockCount,
    hasTop100Count: templateStockCount === 100,
    densityModesToggle: densityBefore !== densityAfter,
    hasSaveTemplate: /保存模板|另存为模板/.test(text),
    hasCandidateKline: candidateKlineCount >= 2,
    keyboardChangedStock: beforeKeyboard !== afterKeyboard,
    afterKeyboard,
    returnLink,
    barsRequests: responses.filter((item) => item.url.includes("/bars")).map((item) => item.url),
    candidateRequests: responses.filter((item) => item.url.includes("candidates")).map((item) => item.url),
    errors,
  };
  await page.close();
}

{
  const mobileContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  let page = await mobileContext.newPage();
  const errors = [];
  const responses = [];
  wireEvents(page, errors, responses);
  await page.goto(`${baseUrl}/templates`, { waitUntil: "domcontentloaded" });
  await settle(page, "templates");
  const firstCandidate = page.locator("a[href^='/market?']").first();
  await firstCandidate.scrollIntoViewIfNeeded();
  await page.waitForTimeout(700);
  const firstCandidateSvgCount = await firstCandidate.locator("svg").count();

  await page.close();
  page = await mobileContext.newPage();
  await page.goto(`${baseUrl}/templates/new`, { waitUntil: "domcontentloaded" });
  const searchInput = page.getByRole("combobox", { name: "搜索股票" });
  await searchInput.click();
  await searchInput.pressSequentially("000001", { delay: 60 });
  const mobileSearchReady = await page.getByRole("listbox").waitFor({ state: "visible", timeout: 6000 }).then(() => true).catch(() => false);
  let mobileHandleBoxes = [];
  if (mobileSearchReady) {
    await page.getByRole("option").first().click();
    await page.getByTestId("focus-kline").waitFor({ state: "visible", timeout: 15000 });
    mobileHandleBoxes = await page.locator("[role='slider'] rect").evaluateAll((elements) =>
      elements.map((element) => {
        const box = element.getBoundingClientRect();
        return { className: element.getAttribute("class"), width: box.width, height: box.height };
      }),
    );
  }
  await page.screenshot({ path: path.join(evidenceDir, "new-template-selected-390x844-viewport.png"), fullPage: false });

  await page.close();
  page = await mobileContext.newPage();
  const marketUrl = `${baseUrl}/market?code=301234&template=fresh_breakout&from=breadth&industry=801080&window=20`;
  await page.goto(marketUrl, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(150);
  const drawerInitiallyOpen = await page.locator(".market-rightbar").evaluate((element) => element.classList.contains("open"));
  await page.getByTestId("template-stock-list").locator("button").first().waitFor({ state: "visible", timeout: 15000 });
  const drawerAfterTemplateLoad = await page.locator(".market-rightbar").evaluate((element) => element.classList.contains("open"));
  const backdropVisible = await page.locator(".rightbar-backdrop").isVisible().catch(() => false);
  await page.keyboard.press("Escape");
  const drawerClosedByEscape = !(await page.locator(".market-rightbar").evaluate((element) => element.classList.contains("open")));
  await page.screenshot({ path: path.join(evidenceDir, "market-390x844-after-escape-viewport.png"), fullPage: false });
  results.interactions.mobile = {
    templatesFirstVisibleCandidateThumbnailLoaded: firstCandidateSvgCount > 0,
    firstCandidateSvgCount,
    mobileNewTemplateSearchReady: mobileSearchReady,
    mobileHandleBoxes,
    minBoundaryHitWidth: mobileHandleBoxes.length
      ? Math.min(...mobileHandleBoxes.filter((item) => /handleHit/.test(item.className || "")).map((item) => item.width))
      : null,
    drawerInitiallyOpen,
    drawerAfterTemplateLoad,
    backdropVisible,
    drawerClosedByEscape,
    errors,
    responses: responses.filter((item) => item.status >= 400),
  };
  await mobileContext.close();
}

await context.close();
await browser.close();
await fs.writeFile(path.join(evidenceDir, "browser-results.json"), JSON.stringify(results, null, 2), "utf8");
console.log(JSON.stringify(results.interactions, null, 2));
