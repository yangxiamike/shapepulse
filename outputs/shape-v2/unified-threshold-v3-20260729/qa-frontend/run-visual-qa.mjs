import { chromium } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const baseURL = "http://localhost:3100";
const backendURL = "http://127.0.0.1:8876";
const outputDir = path.resolve(import.meta.dirname);
const payload = JSON.parse(
  await readFile(
    path.resolve(outputDir, "../../../../public/template-breadth-v3.json"),
    "utf8",
  ),
);
const viewports = [
  { name: "1440", width: 1440, height: 1000 },
  { name: "1024", width: 1024, height: 800 },
  { name: "390", width: 390, height: 844, isMobile: true },
];
const routes = [
  { key: "templates", path: "/templates", heading: "模板库" },
  {
    key: "market",
    path: "/market?code=603986&template=fresh_breakout",
    heading: "兆易创新",
  },
  {
    key: "template-breadth-v3",
    path: "/template-breadth-v3",
    heading: "市场形态宽度",
  },
];

const browser = await chromium.launch({
  channel: "chrome",
  headless: true,
  args: ["--disable-gpu"],
});
const evidence = {
  checkedAt: new Date().toISOString(),
  branch: "codex/unified-threshold-app-v3",
  baseURL,
  backendURL,
  health: null,
  pages: [],
  interactions: {},
  consoleErrors: [],
  pageErrors: [],
  failedResponses: [],
};

function pageEvents(page, label) {
  page.on("console", (message) => {
    if (message.type() === "error") {
      evidence.consoleErrors.push({ page: label, text: message.text() });
    }
  });
  page.on("pageerror", (error) => {
    evidence.pageErrors.push({ page: label, text: error.message });
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      evidence.failedResponses.push({
        page: label,
        status: response.status(),
        url: response.url(),
      });
    }
  });
}

async function waitForRoute(page, key) {
  if (key === "templates") {
    await page.getByRole("heading", { name: "冻结四模板" }).waitFor({
      timeout: 180_000,
    });
    await page.getByRole("heading", { name: "Top 股票" }).waitFor({
      timeout: 180_000,
    });
  } else if (key === "market") {
    await page.getByRole("button", { name: "模板", exact: true }).waitFor({
      timeout: 180_000,
    });
    await page.waitForTimeout(1200);
  } else {
    await page.getByRole("navigation", { name: "四模板切换" }).waitFor({
      timeout: 30_000,
    });
  }
}

async function inspectLayout(page) {
  return page.evaluate(() => {
    const root = document.documentElement;
    const visible = (element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return (
        style.display !== "none" &&
        style.visibility !== "hidden" &&
        Number(style.opacity) !== 0 &&
        rect.width > 0 &&
        rect.height > 0
      );
    };
    const interactive = [
      ...document.querySelectorAll("button, a[href], input, select, [tabindex='0']"),
    ].filter(visible);
    const smallTargets = interactive
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          tag: element.tagName,
          label:
            element.getAttribute("aria-label") ||
            element.textContent?.trim().replace(/\s+/g, " ").slice(0, 80) ||
            "",
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        };
      })
      .filter((item) => item.width < 40 || item.height < 40);
    const horizontalClips = [...document.querySelectorAll("main *")]
      .filter(visible)
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          tag: element.tagName,
          className: String(element.className || "").slice(0, 100),
          text: element.textContent?.trim().replace(/\s+/g, " ").slice(0, 80) || "",
          left: Math.round(rect.left),
          right: Math.round(rect.right),
        };
      })
      .filter(
        (item) =>
          item.left < -1 ||
          item.right > root.clientWidth + 1,
      )
      .slice(0, 30);
    const h1 = document.querySelector("h1");
    const h2 = document.querySelector("h2");
    const body = document.body;
    const font = (element) => {
      if (!element) return null;
      const style = getComputedStyle(element);
      return {
        size: style.fontSize,
        weight: style.fontWeight,
        lineHeight: style.lineHeight,
        color: style.color,
        background: style.backgroundColor,
      };
    };
    return {
      title: document.title,
      viewport: { width: root.clientWidth, height: root.clientHeight },
      scroll: { width: root.scrollWidth, height: root.scrollHeight },
      horizontalOverflow: root.scrollWidth > root.clientWidth + 1,
      smallTargets,
      horizontalClips,
      fonts: { h1: font(h1), h2: font(h2), body: font(body) },
      firstScreenText: [...document.querySelectorAll("main h1, main h2, main p, main strong")]
        .filter((element) => {
          const rect = element.getBoundingClientRect();
          return visible(element) && rect.top >= 0 && rect.top < root.clientHeight;
        })
        .map((element) => element.textContent?.trim().replace(/\s+/g, " "))
        .filter(Boolean)
        .slice(0, 35),
    };
  });
}

async function screenshotRoutes() {
  for (const viewport of viewports) {
    const context = await browser.newContext({
      viewport: { width: viewport.width, height: viewport.height },
      locale: "zh-CN",
      colorScheme: "light",
      isMobile: Boolean(viewport.isMobile),
      deviceScaleFactor: 1,
    });
    for (const route of routes) {
      const page = await context.newPage();
      const label = `${route.key}-${viewport.name}`;
      pageEvents(page, label);
      const started = Date.now();
      const response = await page.goto(`${baseURL}${route.path}`, {
        waitUntil: "domcontentloaded",
        timeout: 180_000,
      });
      await waitForRoute(page, route.key);
      const layout = await inspectLayout(page);
      evidence.pages.push({
        route: route.path,
        viewport,
        httpStatus: response?.status() || null,
        loadMs: Date.now() - started,
        ...layout,
      });
      await page.screenshot({
        path: path.join(outputDir, `${route.key}-${viewport.name}.png`),
        fullPage: route.key !== "market",
        animations: "disabled",
        caret: "hide",
      });
      await page.close();
    }
    await context.close();
  }
}

async function templateInteractions() {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    locale: "zh-CN",
  });
  const page = await context.newPage();
  pageEvents(page, "templates-interactions");
  await page.goto(`${baseURL}/templates`, {
    waitUntil: "domcontentloaded",
    timeout: 180_000,
  });
  await waitForRoute(page, "templates");

  const frozenLabels = ["刚突破", "健康上涨", "回调转强", "抛物线上升"];
  const frozenPresence = {};
  for (const label of frozenLabels) {
    frozenPresence[label] =
      (await page.getByRole("button", { name: new RegExp(label) }).count()) > 0;
  }
  const topLink = page.locator("a[href*='/market?code='][href*='template=']").first();
  const topHref = await topLink.getAttribute("href");

  const firstRailButton = page
    .getByRole("heading", { name: "冻结四模板" })
    .locator("..")
    .locator("..")
    .locator("button")
    .first();
  const focusBefore = await firstRailButton.evaluate((element) => {
    const style = getComputedStyle(element);
    return { outline: style.outline, boxShadow: style.boxShadow, background: style.backgroundColor };
  });
  await firstRailButton.focus();
  const focusAfter = await firstRailButton.evaluate((element) => {
    const style = getComputedStyle(element);
    return { outline: style.outline, boxShadow: style.boxShadow, background: style.backgroundColor };
  });

  const customName = "QA独立视觉模板";
  const renamed = "QA独立视觉模板-已改名";
  await page.getByLabel("模板名称").fill(customName);
  await page.getByLabel("股票代码").fill("603986.SH");
  await page.getByLabel("开始日期").fill("2025-06-19");
  await page.getByLabel("结束日期").fill("2025-08-27");
  await page.getByRole("button", { name: "保存并分析" }).click();
  await page.getByRole("heading", { name: customName }).waitFor({
    timeout: 180_000,
  });
  const renameButton = page.getByRole("button", { name: "重命名" });
  const actionArea = renameButton.locator("..");
  await actionArea.locator("input").fill(renamed);
  await renameButton.click();
  await page.getByRole("heading", { name: renamed }).waitFor({
    timeout: 180_000,
  });
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "删除" }).click();
  await page.getByRole("heading", { name: "刚突破" }).waitFor({
    timeout: 180_000,
  });
  const customRemaining = await page.getByText(renamed, { exact: true }).count();

  evidence.interactions.templates = {
    frozenPresence,
    topHref,
    topLinkPreservesTemplate:
      Boolean(topHref?.includes("/market?code=")) &&
      Boolean(topHref?.includes("template=fresh_breakout")),
    createRenameDelete: {
      created: true,
      renamed: true,
      deleted: customRemaining === 0,
      customRemaining,
    },
    focusVisibleChanged: JSON.stringify(focusBefore) !== JSON.stringify(focusAfter),
    focusBefore,
    focusAfter,
  };
  await page.screenshot({
    path: path.join(outputDir, "templates-after-crud-1440.png"),
    fullPage: true,
    animations: "disabled",
    caret: "hide",
  });
  await context.close();
}

async function marketInteractions() {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    locale: "zh-CN",
  });
  const page = await context.newPage();
  pageEvents(page, "market-interactions");
  await page.goto(
    `${baseURL}/market?code=603986&template=fresh_breakout`,
    { waitUntil: "domcontentloaded", timeout: 180_000 },
  );
  await waitForRoute(page, "market");
  await page.getByRole("button", { name: "模板", exact: true }).click();
  const select = page.getByTestId("template-group-select");
  await select.waitFor({ timeout: 180_000 });
  const comparisonCurve = page.getByRole("img", {
    name: "模板窗口与当前候选窗口归一化曲线比较",
  });
  const notRanked = page.getByRole("heading", {
    name: "未进入这个模板的当前列表",
  });
  await Promise.race([
    comparisonCurve.waitFor({ timeout: 180_000 }),
    notRanked.waitFor({ timeout: 180_000 }),
  ]);
  const initialStockRanked = (await comparisonCurve.count()) === 1;
  if (!initialStockRanked) {
    await page
      .getByTestId("template-stock-list")
      .locator("button")
      .first()
      .click();
    await comparisonCurve.waitFor({ timeout: 180_000 });
  }
  const before = new URL(page.url());
  const activeBefore = await page
    .getByTestId("template-stock-list")
    .locator("button[aria-current='true']")
    .first()
    .textContent();
  await page.keyboard.press("ArrowDown");
  await page.waitForFunction(
    (oldURL) => location.href !== oldURL,
    before.toString(),
    { timeout: 180_000 },
  );
  const after = new URL(page.url());
  const activeAfter = await page
    .getByTestId("template-stock-list")
    .locator("button[aria-current='true']")
    .first()
    .textContent();
  const backLink = page.getByRole("link", {
    name: "回到模板库查看完整列表",
  });
  evidence.interactions.market = {
    initialTemplate: await select.inputValue(),
    templateSelectOptions: await select.locator("option").allTextContents(),
    stockButtons: await page
      .getByTestId("template-stock-list")
      .locator("button")
      .count(),
    requested603986Ranked: initialStockRanked,
    requested603986FallbackMessage: initialStockRanked
      ? null
      : "未进入这个模板的当前列表",
    comparisonCurveVisible: (await comparisonCurve.count()) === 1,
    legends: await page.locator(".template-curve-legend").innerText(),
    keyboardSwitch: {
      beforeURL: before.toString(),
      afterURL: after.toString(),
      beforeText: activeBefore?.trim(),
      afterText: activeAfter?.trim(),
      codeChanged: before.searchParams.get("code") !== after.searchParams.get("code"),
      templatePreserved: after.searchParams.get("template") === "fresh_breakout",
    },
    backHref: await backLink.getAttribute("href"),
  };
  await page.screenshot({
    path: path.join(outputDir, "market-template-interaction-1440.png"),
    animations: "disabled",
    caret: "hide",
  });
  await context.close();
}

async function breadthInteractions() {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    locale: "zh-CN",
  });
  const page = await context.newPage();
  pageEvents(page, "breadth-interactions");
  await page.goto(`${baseURL}/template-breadth-v3`, {
    waitUntil: "domcontentloaded",
    timeout: 60_000,
  });
  await waitForRoute(page, "template-breadth-v3");

  const tabButtons = page
    .getByRole("navigation", { name: "四模板切换" })
    .locator("button");
  const templateChecks = [];
  for (let index = 0; index < (await tabButtons.count()); index += 1) {
    const button = tabButtons.nth(index);
    await button.click();
    const selected = payload.templates[index];
    const summary = await page
      .getByLabel(`${selected.label}市场宽度概览`)
      .innerText();
    templateChecks.push({
      key: selected.key,
      label: selected.label,
      summary,
      hasCount: summary.includes(`${selected.summary.count} 只`),
      hasChange1d: summary.includes(
        `${selected.summary.change1d > 0 ? "+" : ""}${selected.summary.change1d} 只`,
      ),
      hasChange5d: summary.includes(
        `${selected.summary.change5d > 0 ? "+" : ""}${selected.summary.change5d} 只`,
      ),
      hasMa5: summary.includes(`${selected.summary.ma5.toFixed(1)} 只`),
      hasPercent: summary.includes(
        `${selected.summary.historicalPercentile.toFixed(0)}%`,
      ),
    });
  }
  await tabButtons.first().click();

  const blocks = page.locator("button[aria-label*='Top100行业占比']");
  const areaData = await blocks.evaluateAll((elements) =>
    elements.map((element) => {
      const rect = element.getBoundingClientRect();
      const label = element.getAttribute("aria-label") || "";
      const count = Number(label.match(/当前 (\d+) 只/)?.[1] || 0);
      return {
        label,
        count,
        width: rect.width,
        height: rect.height,
        area: rect.width * rect.height,
      };
    }),
  );
  const firstBlock = blocks.first();
  const widthBackground = await firstBlock.evaluate(
    (element) => getComputedStyle(element).backgroundColor,
  );
  await page.getByRole("button", { name: "最近变化" }).click();
  const changeBackground = await firstBlock.evaluate(
    (element) => getComputedStyle(element).backgroundColor,
  );
  const industryLabel = await firstBlock.getAttribute("aria-label");
  await firstBlock.click();
  const selectedHeading = page.locator("section[aria-live='polite'] h2");
  await selectedHeading.waitFor();
  const selectedIndustry = await selectedHeading.textContent();
  const industryChartVisible =
    (await page
      .getByRole("img", {
        name: new RegExp(`${selectedIndustry}近60日超过观察线股票数量`),
      })
      .count()) === 1;
  await page.getByRole("button", { name: "返回全部行业" }).click();
  const returned =
    (await page.getByText("点击一个行业块查看变化", { exact: true }).count()) === 1;

  const warning = await page
    .getByRole("note", { name: "试用观察线提醒" })
    .innerText();
  evidence.interactions.breadth = {
    displayThreshold: payload.displayThreshold,
    warning,
    warningShowsTrial080:
      payload.displayThreshold === 0.8 &&
      warning.includes("0.80") &&
      warning.includes("试用") &&
      warning.includes("未验证"),
    tabs: await tabButtons.allTextContents(),
    templateChecks,
    areaData,
    viewModeVisualChange: widthBackground !== changeBackground,
    widthBackground,
    changeBackground,
    selectedIndustry,
    industryLabel,
    industryChartVisible,
    returned,
  };
  await page.screenshot({
    path: path.join(outputDir, "breadth-industry-interaction-1440.png"),
    fullPage: true,
    animations: "disabled",
    caret: "hide",
  });
  await context.close();
}

try {
  const health = await fetch(`${backendURL}/api/health`);
  evidence.health = { status: health.status, body: await health.json() };
  await screenshotRoutes();
  await templateInteractions();
  await marketInteractions();
  await breadthInteractions();
} catch (error) {
  evidence.fatalError = {
    message: error instanceof Error ? error.message : String(error),
    stack: error instanceof Error ? error.stack : "",
  };
} finally {
  await writeFile(
    path.join(outputDir, "browser-evidence.json"),
    `${JSON.stringify(evidence, null, 2)}\n`,
    "utf8",
  );
  await browser.close();
}

if (evidence.fatalError) {
  throw new Error(evidence.fatalError.message);
}
