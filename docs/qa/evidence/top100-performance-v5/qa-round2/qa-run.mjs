import { chromium } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const evidenceDir = path.dirname(fileURLToPath(import.meta.url));
const baseUrl = "http://localhost:3106";
const chromePath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const sizes = [
  ["1900x956", 1900, 956],
  ["1440x900", 1440, 900],
  ["1024x768", 1024, 768],
  ["390x844", 390, 844],
];
const routes = [
  ["breadth", "/template-breadth-v3"],
  ["templates", "/templates"],
  ["new-template", "/templates/new"],
  ["market", "/market?code=301234&template=fresh_breakout&from=breadth&industry=801080&window=20"],
];

const browser = await chromium.launch({ headless: true, executablePath: chromePath });
const report = {
  generatedAt: new Date().toISOString(),
  branch: "codex/top100-performance-ux-v5",
  baseUrl,
  smoke: [],
  closure: {},
  regressions: {},
};

function watch(page, errors) {
  page.on("console", msg => {
    if (msg.type() === "error" || msg.type() === "warning") {
      errors.push({ kind: "console", level: msg.type(), text: msg.text(), url: page.url() });
    }
  });
  page.on("pageerror", err => errors.push({ kind: "pageerror", text: String(err), url: page.url() }));
  page.on("response", res => {
    if (res.status() >= 400) errors.push({ kind: "http", status: res.status(), url: res.url() });
  });
}

async function waitReady(page, route) {
  if (route === "breadth") await page.locator("[data-industry-code]").first().waitFor({ timeout: 15000 });
  if (route === "templates") await page.getByRole("heading", { name: "Top100 股票" }).waitFor({ timeout: 15000 });
  if (route === "market") await page.locator(".market-chart[data-bars]").waitFor({ timeout: 15000 });
  await page.waitForTimeout(500);
}

for (const [size, width, height] of sizes) {
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
  for (const [route, url] of routes) {
    const page = await context.newPage();
    const errors = [];
    watch(page, errors);
    const response = await page.goto(baseUrl + url, { waitUntil: "domcontentloaded", timeout: 20000 });
    await waitReady(page, route);
    const screenshot = `${route}-${size}-viewport.png`;
    await page.screenshot({ path: path.join(evidenceDir, screenshot), fullPage: false });
    report.smoke.push({
      size,
      route,
      status: response?.status() ?? null,
      errors,
      screenshot,
      horizontalOverflow: await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth),
    });
    await page.close();
  }
  await context.close();
}

{
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  const errors = [];
  watch(page, errors);
  await page.goto(baseUrl + routes[3][1], { waitUntil: "domcontentloaded" });
  const drawer = page.locator(".market-rightbar");
  const openButton = page.getByRole("button", { name: "打开右侧面板" });
  await openButton.waitFor();
  await page.waitForFunction(
    () => document.querySelectorAll("[data-testid='template-stock-list'] button").length > 0,
    undefined,
    { timeout: 15000 },
  );
  const initiallyOpen = await drawer.evaluate(el => el.classList.contains("open"));
  const mainChartVisible = await page.locator(".market-chart").first().isVisible();
  await page.screenshot({ path: path.join(evidenceDir, "p1-market-mobile-default-closed.png") });
  await openButton.click();
  await drawer.waitFor({ state: "visible" });
  const openedAfterClick = await drawer.evaluate(el => el.classList.contains("open"));
  await page.screenshot({ path: path.join(evidenceDir, "p1-market-mobile-open.png") });
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await page.waitForTimeout(150);
  const closedAfterButton = !(await drawer.evaluate(el => el.classList.contains("open")));
  const focusReturned = await openButton.evaluate(el => document.activeElement === el);
  report.closure.p1 = { initiallyOpen, mainChartVisible, openedAfterClick, closedAfterButton, focusReturned, errors };
  await context.close();
}

{
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  watch(page, errors);
  await page.goto(baseUrl + "/templates", { waitUntil: "domcontentloaded" });
  const heading = page.getByRole("heading", { name: "Top100 股票" });
  await heading.waitFor({ timeout: 15000 });
  await page.screenshot({ path: path.join(evidenceDir, "p2-templates-top100-heading.png") });
  report.closure.p2 = { exactHeading: await heading.count() === 1, headingText: await heading.innerText(), errors };
  await context.close();
}

{
  const context = await browser.newContext({ viewport: { width: 1900, height: 956 } });
  const page = await context.newPage();
  const errors = [];
  watch(page, errors);
  await page.goto(baseUrl + "/template-breadth-v3", { waitUntil: "domcontentloaded" });
  await page.locator("[data-industry-code]").first().waitFor({ timeout: 15000 });
  const tileState = async () => page.locator("[data-industry-code]").evaluateAll(nodes => nodes.map(el => {
    const r = el.getBoundingClientRect();
    return {
      code: el.getAttribute("data-industry-code"),
      count: Number(el.getAttribute("data-count")),
      direction: el.getAttribute("data-direction"),
      x: Math.round(r.x * 10) / 10, y: Math.round(r.y * 10) / 10,
      width: Math.round(r.width * 10) / 10, height: Math.round(r.height * 10) / 10,
    };
  }));
  const initial = await tileState();
  const default10 = await page.getByRole("button", { name: "10日", exact: true }).getAttribute("aria-pressed");
  await page.getByRole("button", { name: "20日", exact: true }).click();
  await page.waitForTimeout(150);
  const after20 = await tileState();
  const geometry = x => x.map(({ code, x, y, width, height }) => ({ code, x, y, width, height }));
  const other = page.locator("[data-industry-code='other']");
  const otherNeutral = (await other.getAttribute("data-direction")) === "neutral";
  await other.click();
  await page.getByText("“其他行业”具体构成").waitFor({ timeout: 10000 });
  const otherExpanded = await page.getByText("“其他行业”具体构成").isVisible();

  const templateButtons = page.getByRole("navigation", { name: "冻结四模板切换" }).getByRole("button");
  const templateNames = await templateButtons.allTextContents();
  await templateButtons.nth(1).click();
  await templateButtons.nth(3).click();
  await templateButtons.nth(0).click();
  await page.waitForTimeout(1200);
  const activePressed = await templateButtons.evaluateAll(nodes => nodes.map(n => ({
    text: n.textContent?.trim().replace(/\s+/g, " "),
    pressed: n.getAttribute("aria-pressed"),
  })).filter(x => x.pressed === "true"));
  report.regressions.breadth = {
    total: initial.reduce((sum, x) => sum + x.count, 0),
    default10: default10 === "true",
    switched20: (await page.getByRole("button", { name: "20日", exact: true }).getAttribute("aria-pressed")) === "true",
    geometryStable10to20: JSON.stringify(geometry(initial)) === JSON.stringify(geometry(after20)),
    otherNeutral,
    otherExpanded,
    rapidTemplateNames: templateNames,
    rapidFinalActive: activePressed,
    errors,
  };
  await context.close();
}

{
  const context = await browser.newContext({ viewport: { width: 1900, height: 956 } });
  const page = await context.newPage();
  const errors = [];
  watch(page, errors);
  await page.goto(baseUrl + "/templates/new", { waitUntil: "domcontentloaded" });
  const search = page.getByRole("combobox", { name: "搜索股票" });
  await search.waitFor();
  await page.waitForTimeout(700);
  await search.click();
  await search.pressSequentially("000001", { delay: 60 });
  await page.getByRole("listbox").waitFor({ timeout: 10000 });
  await page.getByRole("option").first().click();
  const focus = page.getByTestId("focus-kline");
  const overview = page.getByTestId("history-overview");
  await focus.waitFor({ timeout: 15000 });
  const before = await focus.evaluate(el => ({
    viewStart: el.getAttribute("data-view-start"),
    viewEnd: el.getAttribute("data-view-end"),
  }));
  const box = await focus.boundingBox();
  if (box) {
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.wheel(0, -600);
    await page.waitForTimeout(200);
  }
  const afterZoom = await focus.evaluate(el => ({
    viewStart: el.getAttribute("data-view-start"),
    viewEnd: el.getAttribute("data-view-end"),
  }));
  const overviewBox = await overview.boundingBox();
  const viewport = page.getByTestId("overview-viewport");
  const panBefore = await viewport.getAttribute("x");
  if (overviewBox) {
    await page.mouse.move(overviewBox.x + overviewBox.width * .75, overviewBox.y + overviewBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(overviewBox.x + overviewBox.width * .35, overviewBox.y + overviewBox.height / 2, { steps: 8 });
    await page.mouse.up();
    await page.waitForTimeout(200);
  }
  const sliders = page.locator("[role='slider']");
  const body = await page.locator("body").innerText();
  report.regressions.newTemplate = {
    focusCandleGroups: Math.max(0, (await focus.locator("g").count()) - 1),
    hasOverview: await overview.isVisible(),
    zoomChanged: JSON.stringify(before) !== JSON.stringify(afterZoom),
    panChanged: panBefore !== await viewport.getAttribute("x"),
    boundarySliderCount: await sliders.count(),
    has20to240Hint: body.includes("20–240"),
    hasActualTradingDays: body.includes("实际交易日"),
    errors,
  };
  await context.close();
}

{
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  watch(page, errors);
  const start = "/market?code=301234&template=fresh_breakout&from=breadth&industry=801080&window=20";
  await page.goto(baseUrl + start, { waitUntil: "domcontentloaded" });
  await page.getByTestId("template-stock-list").getByRole("button").first().waitFor({ timeout: 15000 });
  const beforeKey = page.url();
  await page.keyboard.press("ArrowDown");
  await page.waitForTimeout(700);
  const afterKey = page.url();
  const select = page.getByTestId("template-group-select");
  const values = await select.locator("option").evaluateAll(nodes => nodes.map(n => n.getAttribute("value")));
  if (values.length >= 4) {
    await select.selectOption(values[1]);
    await select.selectOption(values[3]);
    await select.selectOption(values[0]);
    await page.waitForTimeout(1200);
  }
  const finalValue = await select.inputValue();
  const body = await page.locator("body").innerText();
  const returnHref = await page.locator("a").evaluateAll(nodes => nodes
    .map(node => node.getAttribute("href"))
    .find(href => href?.startsWith("/template-breadth-v3?template=")) ?? null);
  report.regressions.market = {
    keyboardChangedStock: beforeKey !== afterKey,
    returnHref,
    preservedReturnContext: Boolean(returnHref?.includes("industry=801080") && returnHref?.includes("window=20")),
    hasSaveTemplateEntry: body.includes("保存模板") || body.includes("另存为模板"),
    rapidRequestedFinal: values[0] ?? null,
    rapidFinalValue: finalValue,
    staleResponseDidNotOverride: !values.length || finalValue === values[0],
    errors,
  };
  await context.close();
}

report.errorCount = [
  ...report.smoke.flatMap(x => x.errors),
  ...Object.values(report.closure).flatMap(x => x.errors ?? []),
  ...Object.values(report.regressions).flatMap(x => x.errors ?? []),
].length;

await browser.close();
await fs.writeFile(path.join(evidenceDir, "browser-results.json"), JSON.stringify(report, null, 2), "utf8");
console.log(JSON.stringify(report, null, 2));
