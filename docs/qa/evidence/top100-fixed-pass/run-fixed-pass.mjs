import { chromium } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";

const baseURL = "http://localhost:3103";
const apiURL = "http://127.0.0.1:8878";
const out = path.resolve("docs/qa/evidence/top100-fixed-pass");
const sizes = [
  { name: "desktop-1440", width: 1440, height: 1000 },
  { name: "narrow-1024", width: 1024, height: 900 },
  { name: "mobile-390", width: 390, height: 844 },
];
const result = {
  startedAt: new Date().toISOString(),
  baseURL,
  apiURL,
  http: [],
  pages: [],
  checks: {},
};

await fs.mkdir(out, { recursive: true });
for (const url of [
  `${baseURL}/templates`,
  `${baseURL}/templates/new`,
  `${baseURL}/template-breadth-v3`,
  `${baseURL}/market?code=301234&template=fresh_breakout`,
  `${apiURL}/api/health`,
  `${apiURL}/api/templates`,
  `${apiURL}/api/templates/fresh_breakout`,
  `${apiURL}/api/templates/fresh_breakout/stocks?limit=3`,
  `${apiURL}/api/bars/301234?period=1d&limit=80`,
]) {
  const response = await fetch(url);
  result.http.push({
    url,
    status: response.status,
    contentType: response.headers.get("content-type"),
  });
}

const browser = await chromium.launch({
  channel: "chrome",
  headless: true,
  args: ["--disable-gpu"],
});

async function observe(page, size, route) {
  const record = {
    size: size.name,
    route,
    console: [],
    pageErrors: [],
    requestFailures: [],
    externalRequests: [],
  };
  page.on("console", message => {
    if (["error", "warning"].includes(message.type())) {
      record.console.push({ type: message.type(), text: message.text() });
    }
  });
  page.on("pageerror", error => record.pageErrors.push(String(error)));
  page.on("requestfailed", request => {
    record.requestFailures.push({
      url: request.url(),
      failure: request.failure()?.errorText ?? "unknown",
    });
  });
  page.on("request", request => {
    const host = new URL(request.url()).hostname;
    if (!["localhost", "127.0.0.1", "::1"].includes(host)) {
      record.externalRequests.push(request.url());
    }
  });
  const response = await page.goto(`${baseURL}${route}`, {
    waitUntil: "networkidle",
    timeout: 60_000,
  });
  record.status = response?.status() ?? null;
  record.overflow = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  result.pages.push(record);
  return record;
}

for (const size of sizes) {
  const context = await browser.newContext({
    viewport: { width: size.width, height: size.height },
    locale: "zh-CN",
    colorScheme: "light",
  });

  // Top100 width, geometry, non-color channels, industry drill-down.
  {
    const page = await context.newPage();
    const record = await observe(page, size, "/template-breadth-v3");
    const map = page.getByRole("group", { name: /Top100 行业矩形树图/ });
    const blocks = map.getByRole("button");
    record.mapBlocks = await blocks.count();
    record.mapGeometry = await blocks.evaluateAll(elements => elements.map(element => {
      const box = element.getBoundingClientRect();
      return {
        text: element.textContent?.trim(),
        width: box.width,
        height: box.height,
        area: box.width * box.height,
        ratio: Math.max(box.width / box.height, box.height / box.width),
      };
    }));
    record.summary = {
      currentTemplate: await page.getByText("当前模板", { exact: true }).locator("..").innerText(),
      widest: await page.getByText("最宽行业", { exact: true }).locator("..").innerText(),
      entrants: await page.getByText("5日新进入最多", { exact: true }).locator("..").innerText(),
      exits: await page.getByText("5日退出最多", { exact: true }).locator("..").innerText(),
      dateUnitDenominatorPresent: /数据日期/.test(await page.locator("body").innerText())
        && /单位：只 \/ %/.test(await page.locator("body").innerText())
        && /分母：本模板当日可选股票/.test(await page.locator("body").innerText()),
      nonColorPresent: /数字、文字和条段共同表达/.test(await page.locator("body").innerText()),
    };
    const first = blocks.first();
    record.focusBefore = await first.evaluate(element => ({
      outline: getComputedStyle(element).outline,
      boxShadow: getComputedStyle(element).boxShadow,
    }));
    await first.hover();
    record.hover = await first.evaluate(element => ({
      outline: getComputedStyle(element).outline,
      filter: getComputedStyle(element).filter,
    }));
    await first.focus();
    record.focus = await first.evaluate(element => ({
      outline: getComputedStyle(element).outline,
      boxShadow: getComputedStyle(element).boxShadow,
    }));
    await page.screenshot({
      path: path.join(out, `${size.name}-breadth.png`),
      fullPage: true,
    });
    await first.click();
    await page.waitForTimeout(350);
    record.drilldown = {
      heading: await page.getByText("已选行业").locator("..").innerText(),
      stockLinks: await page.locator('a[href*="/market?"][href*="template="]').count(),
      transitions: await page.locator("details").count(),
      series: await page.locator('svg[aria-label*="数量时间序列"]').count(),
    };
    await page.screenshot({
      path: path.join(out, `${size.name}-breadth-selected.png`),
      fullPage: true,
    });
    await page.close();
  }

  // Template library real K-line and usable miniatures.
  {
    const page = await context.newPage();
    const record = await observe(page, size, "/templates");
    await page.waitForTimeout(700);
    const candidates = page.locator('a[href*="/market?"][href*="template="]');
    const mini = candidates.first().locator('svg[aria-label*="候选窗口真实前复权 K 线"]');
    record.candidateLinks = await candidates.count();
    record.templateRealKline = await page.locator('svg[aria-label*="真实前复权 K 线"]').count();
    record.firstMiniBox = await mini.boundingBox();
    record.firstCandidateHref = await candidates.first().getAttribute("href");
    await page.screenshot({
      path: path.join(out, `${size.name}-templates.png`),
      fullPage: true,
    });
    await page.close();
  }

  // New template: real full chart, two accessible handles and local preview.
  {
    const page = await context.newPage();
    const record = await observe(page, size, "/templates/new");
    await page.getByPlaceholder(/股票名称、代码或拼音/).fill("平安银行");
    await page.waitForTimeout(700);
    await page.getByRole("button", { name: /平安银行/ }).first().click();
    await page.waitForTimeout(1700);
    const chart = page.locator('svg[aria-label*="完整前复权 K 线"]');
    const sliders = page.getByRole("slider");
    record.fullChart = await chart.count();
    record.sliderCount = await sliders.count();
    record.sliderBoxes = await sliders.evaluateAll(elements => elements.map(element => {
      const box = element.getBoundingClientRect();
      return {
        label: element.getAttribute("aria-label"),
        now: element.getAttribute("aria-valuenow"),
        width: box.width,
        height: box.height,
      };
    }));
    record.preview = await page.locator('svg[aria-label*="选中模板窗口局部真实前复权 K 线"]').count();
    record.initialValidation = (await page.locator("body").innerText()).match(/\d+ 个交易日[\s\S]{0,80}/)?.[0] ?? "";
    const firstSlider = sliders.first();
    await firstSlider.focus();
    const before = Number(await firstSlider.getAttribute("aria-valuenow"));
    await page.keyboard.press("ArrowLeft");
    await page.waitForTimeout(100);
    const after = Number(await firstSlider.getAttribute("aria-valuenow"));
    record.keyboardBoundary = {
      before,
      after,
      moved: after === before - 1,
      focus: await firstSlider.evaluate(element => ({
        outline: getComputedStyle(element).outline,
        fill: getComputedStyle(element.querySelector("rect")).fill,
      })),
    };
    await page.screenshot({
      path: path.join(out, `${size.name}-new-template-selected.png`),
      fullPage: true,
    });
    record.returnHref = await page.getByRole("link", { name: /返回模板库/ }).getAttribute("href");
    await page.close();
  }

  // Pure market duties, template context, double real K-line and compact/expanded mode.
  {
    const page = await context.newPage();
    const record = await observe(page, size, "/market?code=301234&template=fresh_breakout");
    await page.waitForFunction(() => document.body.innerText.includes("五洲医疗"), null, { timeout: 30_000 });
    await page.waitForTimeout(500);
    record.templateContext = {
      url: page.url(),
      poolButtons: await page.locator(".template-stock-list button").count(),
      backHref: await page.getByRole("link", { name: /回到模板库查看完整列表/ }).getAttribute("href"),
      saveEntryCount: await page.getByText(/保存区间|保存当前区间为模板/).count(),
      realPair: await page.locator('.template-kline-pair svg[aria-label*="真实前复权 K 线"]').count(),
      stageNote: await page.getByText(/判断更接近起涨、加速或末端/).count(),
    };
    const activeBefore = await page.locator('.template-stock-list button[aria-current="true"]').innerText();
    await page.keyboard.press("ArrowDown");
    await page.waitForTimeout(1000);
    const activeAfter = await page.locator('.template-stock-list button[aria-current="true"]').innerText();
    record.keyboardSwitch = { activeBefore, activeAfter, changed: activeBefore !== activeAfter };
    const expandedWorkspace = await page.locator(".chart-workspace").boundingBox();
    await page.screenshot({
      path: path.join(out, `${size.name}-market-expanded.png`),
      fullPage: true,
    });
    const closePanel = page.getByRole("button", { name: "关闭", exact: true });
    if (await closePanel.isVisible().catch(() => false)) {
      await closePanel.click();
      await page.waitForTimeout(150);
      record.closedResponsivePanelBeforeCompact = true;
    } else {
      record.closedResponsivePanelBeforeCompact = false;
    }
    const compact = page.getByRole("button", { name: "收起行情页顶部" });
    await compact.click();
    await page.waitForTimeout(350);
    const compactWorkspace = await page.locator(".chart-workspace").boundingBox();
    record.compact = {
      pressed: await page.getByRole("button", { name: "展开行情页顶部" }).getAttribute("aria-pressed"),
      expandedHeight: expandedWorkspace?.height ?? 0,
      compactHeight: compactWorkspace?.height ?? 0,
      gained: (compactWorkspace?.height ?? 0) > (expandedWorkspace?.height ?? 0),
    };
    await page.screenshot({
      path: path.join(out, `${size.name}-market-compact.png`),
      fullPage: true,
    });
    await page.close();
  }

  await context.close();
}

// Explicit 20–240 invalid states through real pointer brush, without saving.
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: "zh-CN" });
  await page.goto(`${baseURL}/templates/new`, { waitUntil: "networkidle" });
  await page.getByPlaceholder(/股票名称、代码或拼音/).fill("平安银行");
  await page.waitForTimeout(700);
  await page.getByRole("button", { name: /平安银行/ }).first().click();
  await page.waitForTimeout(1600);
  const sliders = page.getByRole("slider");
  const chart = page.locator('svg[aria-label*="完整前复权 K 线"]');
  const start = await sliders.first().boundingBox();
  const chartBox = await chart.boundingBox();
  if (start && chartBox) {
    await page.mouse.move(start.x + start.width / 2, start.y + 30);
    await page.mouse.down();
    await page.mouse.move(Math.max(chartBox.x + 5, start.x - 160), start.y + 30, { steps: 12 });
    await page.mouse.up();
    await page.waitForTimeout(250);
    result.checks.over240 = /超出 \d+ 个交易日，最多允许 240 日/.test(await page.locator("body").innerText());
    await page.screenshot({ path: path.join(out, "desktop-1440-new-template-over240.png"), fullPage: true });
  }
  const end = await sliders.nth(1).boundingBox();
  const startAfter = await sliders.first().boundingBox();
  if (end && startAfter) {
    await page.mouse.move(end.x + end.width / 2, end.y + 30);
    await page.mouse.down();
    await page.mouse.move(startAfter.x + startAfter.width / 2 + 2, end.y + 30, { steps: 12 });
    await page.mouse.up();
    await page.waitForTimeout(250);
    result.checks.under20 = /还差 \d+ 个交易日，最少需要 20 日/.test(await page.locator("body").innerText());
    await page.screenshot({ path: path.join(out, "desktop-1440-new-template-under20.png"), fullPage: true });
  }
  await page.close();
}

result.finishedAt = new Date().toISOString();
await fs.writeFile(
  path.join(out, "browser-results.json"),
  `${JSON.stringify(result, null, 2)}\n`,
  "utf8",
);
await browser.close();
console.log(JSON.stringify({
  pages: result.pages.length,
  errors: result.pages.reduce((sum, page) =>
    sum + page.console.length + page.pageErrors.length + page.requestFailures.length, 0),
  externalRequests: result.pages.reduce((sum, page) => sum + page.externalRequests.length, 0),
  over240: result.checks.over240,
  under20: result.checks.under20,
}, null, 2));
