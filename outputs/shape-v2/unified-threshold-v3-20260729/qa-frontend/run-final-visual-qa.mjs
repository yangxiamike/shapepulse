import { chromium } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const baseURL = "http://localhost:3101";
const backendURL = "http://127.0.0.1:8876";
const outputDir = import.meta.dirname;
const payload = JSON.parse(
  await readFile(path.resolve(outputDir, "../../../../public/template-breadth-v3.json"), "utf8"),
);
const branch = "codex/unified-threshold-app-v3";
const viewports = [
  { name: "1440", width: 1440, height: 1000 },
  { name: "1024", width: 1024, height: 800 },
  { name: "390", width: 390, height: 844, isMobile: true },
];
const routes = [
  { key: "templates", path: "/templates" },
  { key: "market", path: "/market?code=603986&template=fresh_breakout" },
  { key: "breadth", path: "/template-breadth-v3" },
];

const evidence = {
  checkedAt: new Date().toISOString(),
  branch,
  head: "7f57b3f",
  baseURL,
  backendURL,
  health: null,
  pages: [],
  interactions: {},
  consoleErrors: [],
  pageErrors: [],
  failedResponses: [],
  assertions: [],
};

function assert(name, pass, details = null) {
  evidence.assertions.push({ name, pass: Boolean(pass), details });
}

function monitor(page, label) {
  page.on("console", message => {
    if (message.type() === "error") evidence.consoleErrors.push({ page: label, text: message.text() });
  });
  page.on("pageerror", error => evidence.pageErrors.push({ page: label, text: error.message }));
  page.on("response", response => {
    if (response.status() >= 400) {
      evidence.failedResponses.push({ page: label, status: response.status(), url: response.url() });
    }
  });
}

async function ready(page, key) {
  if (key === "market") {
    await page.locator(".market-shell").waitFor({ timeout: 180_000 });
    await page.locator(".market-rightbar").waitFor({ state: "attached", timeout: 180_000 });
    await page.waitForTimeout(1800);
    return;
  }
  if (key === "breadth") {
    await page.getByRole("navigation", { name: "四模板切换" }).waitFor({ timeout: 60_000 });
    return;
  }
  await page.locator("main").waitFor({ timeout: 180_000 });
  await page.waitForTimeout(1500);
}

async function layout(page) {
  return page.evaluate(() => {
    const root = document.documentElement;
    const visible = element => {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return style.display !== "none" && style.visibility !== "hidden" &&
        Number(style.opacity) !== 0 && rect.width > 0 && rect.height > 0;
    };
    const rect = element => {
      const box = element.getBoundingClientRect();
      return {
        left: Math.round(box.left), top: Math.round(box.top),
        right: Math.round(box.right), bottom: Math.round(box.bottom),
        width: Math.round(box.width), height: Math.round(box.height),
      };
    };
    const interactives = [...document.querySelectorAll("button,a[href],input,select,[tabindex='0']")]
      .filter(visible)
      .map(element => ({
        label: element.getAttribute("aria-label") || element.textContent?.trim().replace(/\s+/g, " ").slice(0, 80) || "",
        tag: element.tagName,
        disabled: "disabled" in element ? element.disabled : false,
        ...rect(element),
      }));
    return {
      viewport: { width: root.clientWidth, height: root.clientHeight },
      scroll: { width: root.scrollWidth, height: root.scrollHeight },
      horizontalOverflow: root.scrollWidth > root.clientWidth + 1,
      visibleInteractiveCount: interactives.length,
      smallTargets: interactives.filter(item => !item.disabled && (item.width < 40 || item.height < 40)),
      enabledHelpExit: interactives.filter(item => !item.disabled && /(帮助|退出系统|退出登录)/.test(item.label)),
      pageText: document.body.innerText.slice(0, 2000),
    };
  });
}

async function baselineScreenshots(browser) {
  for (const viewport of viewports) {
    const context = await browser.newContext({
      viewport: { width: viewport.width, height: viewport.height },
      locale: "zh-CN",
      isMobile: Boolean(viewport.isMobile),
      deviceScaleFactor: 1,
    });
    for (const route of routes) {
      const page = await context.newPage();
      const label = `${route.key}-${viewport.name}`;
      monitor(page, label);
      const started = Date.now();
      const response = await page.goto(`${baseURL}${route.path}`, {
        waitUntil: "domcontentloaded",
        timeout: 180_000,
      });
      await ready(page, route.key);
      const inspected = await layout(page);
      evidence.pages.push({
        route: route.path,
        viewport,
        httpStatus: response?.status() ?? null,
        loadMs: Date.now() - started,
        ...inspected,
      });
      await page.screenshot({
        path: path.join(outputDir, `after-${route.key}-${viewport.name}.png`),
        fullPage: route.key !== "market",
        animations: "disabled",
        caret: "hide",
      });
      await page.close();
    }
    await context.close();
  }
}

function pathYRange(d) {
  const ys = [...String(d || "").matchAll(/[ML][\d.]+,([\d.]+)/g)].map(match => Number(match[1]));
  return ys.length ? Math.max(...ys) - Math.min(...ys) : 0;
}

async function marketDesktop(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: "zh-CN" });
  const page = await context.newPage();
  monitor(page, "market-desktop-final");
  await page.goto(`${baseURL}/market?code=603986&template=fresh_breakout`, {
    waitUntil: "domcontentloaded", timeout: 180_000,
  });
  await ready(page, "market");
  const templateTab = page.getByRole("button", { name: "模板", exact: true });
  const tabActive = await templateTab.evaluate(element => element.classList.contains("active"));
  const select = page.getByTestId("template-group-select");
  await select.waitFor({ timeout: 180_000 });
  const selectValue = await select.inputValue();
  const notRanked = page.getByText("未进入这个模板的当前列表", { exact: true });
  const curve = page.locator(".template-curve-comparison");
  if (await notRanked.count()) {
    await page.getByTestId("template-stock-list").locator("button").first().click();
    await curve.waitFor({ timeout: 180_000 });
  } else {
    await curve.waitFor({ timeout: 180_000 });
  }
  const transform = await curve.getAttribute("data-transform");
  const stats = await curve.evaluate(element => ({
    templateMean: Number(element.getAttribute("data-template-mean")),
    templateStd: Number(element.getAttribute("data-template-std")),
    candidateMean: Number(element.getAttribute("data-candidate-mean")),
    candidateStd: Number(element.getAttribute("data-candidate-std")),
    sourcePath: element.querySelector(".template-source-line")?.getAttribute("d") || "",
    candidatePath: element.querySelector(".template-candidate-line")?.getAttribute("d") || "",
  }));
  const sourceYRange = pathYRange(stats.sourcePath);
  const candidateYRange = pathYRange(stats.candidatePath);
  const before = new URL(page.url());
  const beforeActive = await page.getByTestId("template-stock-list").locator("button[aria-current='true']").first().innerText();
  await page.keyboard.press("ArrowDown");
  await page.waitForFunction(oldURL => location.href !== oldURL, before.toString(), { timeout: 180_000 });
  const after = new URL(page.url());
  const afterActive = await page.getByTestId("template-stock-list").locator("button[aria-current='true']").first().innerText();
  evidence.interactions.marketDesktop = {
    templateTabActiveOnURLLoad: tabActive,
    selectValue,
    transform,
    stats,
    sourceYRange,
    candidateYRange,
    yRangeRatio: Math.max(sourceYRange, candidateYRange) / Math.max(0.001, Math.min(sourceYRange, candidateYRange)),
    keyboard: {
      beforeURL: before.toString(), afterURL: after.toString(),
      beforeActive, afterActive,
      codeChanged: before.searchParams.get("code") !== after.searchParams.get("code"),
      templatePreserved: after.searchParams.get("template") === "fresh_breakout",
    },
  };
  assert("market URL auto-selects Template tab", tabActive && selectValue === "fresh_breakout", { tabActive, selectValue });
  assert("comparison uses frozen independent z transform", transform === "qfq-log-close-independent-z", { transform, stats });
  assert("both comparison curves have meaningful vertical range", sourceYRange >= 30 && candidateYRange >= 30, { sourceYRange, candidateYRange });
  assert("keyboard switch preserves template", evidence.interactions.marketDesktop.keyboard.codeChanged && evidence.interactions.marketDesktop.keyboard.templatePreserved, evidence.interactions.marketDesktop.keyboard);
  await page.screenshot({ path: path.join(outputDir, "after-market-template-1440.png"), animations: "disabled", caret: "hide" });
  await context.close();
}

async function marketMobile(browser) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, locale: "zh-CN", isMobile: true, deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  monitor(page, "market-mobile-final");
  await page.goto(`${baseURL}/market?code=603986&template=fresh_breakout`, {
    waitUntil: "domcontentloaded", timeout: 180_000,
  });
  await ready(page, "market");
  const drawer = page.locator(".market-rightbar");
  await drawer.waitFor({ state: "visible", timeout: 180_000 });
  const drawerGeometry = await drawer.evaluate(element => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return {
      left: Math.round(rect.left), right: Math.round(rect.right),
      width: Math.round(rect.width), visibility: style.visibility,
      pointerEvents: style.pointerEvents, transform: style.transform,
      open: element.classList.contains("open"),
    };
  });
  const templateTab = page.getByRole("button", { name: "模板", exact: true });
  const tabActive = await templateTab.evaluate(element => element.classList.contains("active"));
  const select = page.getByTestId("template-group-select");
  await select.waitFor({ timeout: 180_000 });
  await select.selectOption("healthy_uptrend");
  await page.waitForFunction(() => new URL(location.href).searchParams.get("template") === "healthy_uptrend", null, { timeout: 180_000 });
  const selectedValue = await select.inputValue();
  const firstStock = page.getByTestId("template-stock-list").locator("button").first();
  await firstStock.click();
  await page.waitForFunction(() => new URL(location.href).searchParams.get("code") !== "603986", null, { timeout: 180_000 });
  const afterStockClick = page.url();
  const closeButton = drawer.getByRole("button", { name: /关闭/ }).first();
  await closeButton.click();
  await page.waitForTimeout(350);
  const afterClose = await drawer.evaluate(element => ({
    open: element.classList.contains("open"),
    visibility: getComputedStyle(element).visibility,
    pointerEvents: getComputedStyle(element).pointerEvents,
  }));
  evidence.interactions.marketMobileDrawer = {
    autoOpen: drawerGeometry.open,
    drawerGeometry,
    templateTabActive: tabActive,
    normalSelectChanged: selectedValue === "healthy_uptrend",
    normalStockClickChangedURL: new URL(afterStockClick).searchParams.get("code") !== "603986",
    afterStockClick,
    normalCloseWorked: !afterClose.open,
    afterClose,
  };
  assert("390 valid template URL auto-opens usable drawer",
    drawerGeometry.open && drawerGeometry.left >= -1 && drawerGeometry.right <= 391 &&
    drawerGeometry.visibility === "visible" && drawerGeometry.pointerEvents === "auto" && tabActive,
    evidence.interactions.marketMobileDrawer);
  assert("390 drawer supports ordinary select/stock/close clicks",
    selectedValue === "healthy_uptrend" && new URL(afterStockClick).searchParams.get("code") !== "603986" && !afterClose.open,
    evidence.interactions.marketMobileDrawer);

  await page.goto(`${baseURL}/market?code=603986&template=fresh_breakout`, {
    waitUntil: "domcontentloaded", timeout: 180_000,
  });
  await ready(page, "market");
  await page.screenshot({ path: path.join(outputDir, "after-market-mobile-template-open-390.png"), animations: "disabled", caret: "hide" });
  await page.locator(".market-rightbar").getByRole("button", { name: /关闭/ }).first().click();
  await page.waitForTimeout(250);
  const toolbarChecks = {};
  for (const selector of [".period-tabs", ".drawing-toolbar", ".range-toolbar"]) {
    const bar = page.locator(selector);
    await bar.scrollIntoViewIfNeeded();
    const before = await bar.evaluate(element => ({
      clientWidth: element.clientWidth, scrollWidth: element.scrollWidth, scrollLeft: element.scrollLeft,
      targets: [...element.querySelectorAll("button,a[href],select,input")].map(target => {
        const rect = target.getBoundingClientRect();
        return {
          label: target.getAttribute("aria-label") || target.textContent?.trim() || "",
          width: Math.round(rect.width), height: Math.round(rect.height), disabled: target.disabled || false,
        };
      }),
    }));
    await bar.evaluate(element => { element.scrollLeft = element.scrollWidth; });
    await page.waitForTimeout(120);
    const after = await bar.evaluate(element => ({
      scrollLeft: element.scrollLeft,
      maxScroll: element.scrollWidth - element.clientWidth,
      lastRight: Math.round(element.lastElementChild?.getBoundingClientRect().right || 0),
      viewportWidth: document.documentElement.clientWidth,
    }));
    toolbarChecks[selector] = { before, after };
  }
  evidence.interactions.marketMobileToolbars = toolbarChecks;
  const allToolTargets = Object.values(toolbarChecks).flatMap(check => check.before.targets).filter(target => !target.disabled);
  assert("390 market toolbar enabled touch targets are at least 44px",
    allToolTargets.every(target => target.width >= 44 && target.height >= 44),
    allToolTargets.filter(target => target.width < 44 || target.height < 44));
  assert("390 market toolbars can scroll to their final controls",
    Object.values(toolbarChecks).every(check => check.after.maxScroll <= 1 || Math.abs(check.after.scrollLeft - check.after.maxScroll) <= 2),
    toolbarChecks);
  await page.screenshot({ path: path.join(outputDir, "after-market-mobile-tools-end-390.png"), animations: "disabled", caret: "hide" });
  await context.close();
}

async function breadth(browser) {
  const desktop = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: "zh-CN" });
  const page = await desktop.newPage();
  monitor(page, "breadth-final");
  await page.goto(`${baseURL}/template-breadth-v3`, { waitUntil: "domcontentloaded", timeout: 60_000 });
  await ready(page, "breadth");
  const nav = page.getByRole("navigation", { name: "四模板切换" });
  const tabs = nav.locator("button");
  const checks = [];
  for (let i = 0; i < payload.templates.length; i += 1) {
    const template = payload.templates[i];
    await tabs.nth(i).click();
    await page.getByRole("button", { name: "最近变化" }).click();
    await page.waitForTimeout(120);
    const expectedChanged = template.industries.filter(item => Math.abs(item.change_5d) > 0);
    const renderedLabels = await page.locator("button[aria-label*='Top100行业占比']").evaluateAll(elements =>
      elements.map(element => element.getAttribute("aria-label") || ""),
    );
    const missingChanged = expectedChanged.filter(item => !renderedLabels.some(label => label.startsWith(`${item.industry}，`)));
    const zeroCurrentChanged = template.industries.filter(item => item.above_count === 0 && Math.abs(item.change_5d) > 0);
    const missingZeroCurrentChanged = zeroCurrentChanged.filter(item => !renderedLabels.some(label => label.startsWith(`${item.industry}，`)));
    const expansion = template.industries.reduce((best, item) => item.change_5d > best.change_5d ? item : best, template.industries[0]);
    const contraction = template.industries.reduce((best, item) => item.change_5d < best.change_5d ? item : best, template.industries[0]);
    const bodyText = await page.locator("main").innerText();
    const expansionMatched = bodyText.includes(expansion.industry) && bodyText.includes(`+${expansion.change_5d}`);
    const contractionMatched = bodyText.includes(contraction.industry) && bodyText.includes(String(contraction.change_5d));
    checks.push({
      key: template.key, label: template.label,
      totalIndustries: template.industries.length,
      expectedChanged: expectedChanged.length,
      renderedBlocks: renderedLabels.length,
      zeroCurrentChanged,
      missingChanged,
      missingZeroCurrentChanged,
      expansion: { industry: expansion.industry, change5d: expansion.change_5d, matched: expansionMatched },
      contraction: { industry: contraction.industry, change5d: contraction.change_5d, matched: contractionMatched },
    });
  }
  evidence.interactions.breadthIndustryChanges = checks;
  assert("change treemap includes every non-zero changed industry", checks.every(check => check.missingChanged.length === 0), checks);
  assert("change treemap includes zero-current but changed industries", checks.every(check => check.missingZeroCurrentChanged.length === 0), checks);
  assert("max expansion/contraction summary matches all 31 industries", checks.every(check => check.expansion.matched && check.contraction.matched), checks);
  await tabs.nth(1).click();
  await page.getByRole("button", { name: "最近变化" }).click();
  await page.screenshot({ path: path.join(outputDir, "after-breadth-change-1440.png"), fullPage: true, animations: "disabled", caret: "hide" });
  await desktop.close();

  const mobile = await browser.newContext({
    viewport: { width: 390, height: 844 }, locale: "zh-CN", isMobile: true, deviceScaleFactor: 1,
  });
  const mobilePage = await mobile.newPage();
  monitor(mobilePage, "breadth-mobile-final");
  await mobilePage.goto(`${baseURL}/template-breadth-v3`, { waitUntil: "domcontentloaded", timeout: 60_000 });
  await ready(mobilePage, "breadth");
  const mobileTabs = mobilePage.getByRole("navigation", { name: "四模板切换" }).locator("button");
  const tabBoxes = [];
  for (let i = 0; i < await mobileTabs.count(); i += 1) {
    tabBoxes.push(await mobileTabs.nth(i).evaluate(element => {
      const rect = element.getBoundingClientRect();
      return { left: Math.round(rect.left), top: Math.round(rect.top), right: Math.round(rect.right), bottom: Math.round(rect.bottom), width: Math.round(rect.width), height: Math.round(rect.height) };
    }));
  }
  const rowTops = [...new Set(tabBoxes.map(box => box.top))];
  evidence.interactions.breadthMobileTabs = { boxes: tabBoxes, rowTops, count: tabBoxes.length };
  assert("390 breadth template tabs form a visible 2x2 grid",
    tabBoxes.length === 4 && rowTops.length === 2 && tabBoxes.every(box => box.left >= 0 && box.right <= 390 && box.width >= 150 && box.height >= 44),
    evidence.interactions.breadthMobileTabs);
  await mobilePage.screenshot({ path: path.join(outputDir, "after-breadth-tabs-390.png"), fullPage: false, animations: "disabled", caret: "hide" });
  await mobile.close();
}

async function templateMobileAndDeadButtons(browser) {
  const mobile = await browser.newContext({
    viewport: { width: 390, height: 844 }, locale: "zh-CN", isMobile: true, deviceScaleFactor: 1,
  });
  const page = await mobile.newPage();
  monitor(page, "templates-mobile-final");
  await page.goto(`${baseURL}/templates`, { waitUntil: "domcontentloaded", timeout: 180_000 });
  await ready(page, "templates");
  const lastInteractive = page.locator("main button,main a[href],main input,main select").last();
  await lastInteractive.scrollIntoViewIfNeeded();
  await page.waitForTimeout(150);
  const bottomSafety = await lastInteractive.evaluate(element => {
    const rect = element.getBoundingClientRect();
    const sidebar = document.querySelector(".app-sidebar");
    const sidebarRect = sidebar?.getBoundingClientRect();
    const style = getComputedStyle(document.querySelector("main"));
    return {
      target: { top: Math.round(rect.top), bottom: Math.round(rect.bottom), height: Math.round(rect.height) },
      sidebarTop: sidebarRect ? Math.round(sidebarRect.top) : null,
      sidebarBottom: sidebarRect ? Math.round(sidebarRect.bottom) : null,
      mainPaddingBottom: style.paddingBottom,
      viewportHeight: document.documentElement.clientHeight,
      targetAboveMobileNav: sidebarRect ? rect.bottom <= sidebarRect.top + 1 : false,
    };
  });
  evidence.interactions.templateMobileBottomSafety = bottomSafety;
  assert("390 template final control can scroll above fixed bottom navigation", bottomSafety.targetAboveMobileNav, bottomSafety);
  await page.screenshot({ path: path.join(outputDir, "after-templates-bottom-390.png"), animations: "disabled", caret: "hide" });
  await mobile.close();

  const desktop = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: "zh-CN" });
  const dead = [];
  for (const route of routes) {
    const p = await desktop.newPage();
    monitor(p, `dead-buttons-${route.key}`);
    await p.goto(`${baseURL}${route.path}`, { waitUntil: "domcontentloaded", timeout: 180_000 });
    await ready(p, route.key);
    dead.push({
      route: route.path,
      enabled: await p.locator("button:not(:disabled),a[href]").evaluateAll(elements =>
        elements.filter(element => /(帮助|退出系统|退出登录)/.test(
          element.getAttribute("aria-label") || element.textContent || "",
        )).map(element => element.getAttribute("aria-label") || element.textContent?.trim() || ""),
      ),
    });
    await p.close();
  }
  evidence.interactions.deadButtons = dead;
  assert("no enabled visible Help/Exit dead buttons remain", dead.every(item => item.enabled.length === 0), dead);
  await desktop.close();
}

const browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--disable-gpu"] });
try {
  const health = await fetch(`${backendURL}/api/health`);
  evidence.health = { status: health.status, body: await health.json() };
  assert("backend uses local zer0share with no network", evidence.health.status === 200 && evidence.health.body.network === "not used" && String(evidence.health.body.state_db).endsWith("qa-market-state.sqlite3"), evidence.health);
  await baselineScreenshots(browser);
  await marketDesktop(browser);
  await marketMobile(browser);
  await breadth(browser);
  await templateMobileAndDeadButtons(browser);
  assert("all 9 route/viewport documents return HTTP 200", evidence.pages.length === 9 && evidence.pages.every(page => page.httpStatus === 200), evidence.pages.map(page => ({ route: page.route, viewport: page.viewport.name, status: page.httpStatus })));
  assert("no console/page/failed-response errors", evidence.consoleErrors.length === 0 && evidence.pageErrors.length === 0 && evidence.failedResponses.length === 0, {
    consoleErrors: evidence.consoleErrors, pageErrors: evidence.pageErrors, failedResponses: evidence.failedResponses,
  });
} catch (error) {
  evidence.fatalError = {
    message: error instanceof Error ? error.message : String(error),
    stack: error instanceof Error ? error.stack : "",
  };
} finally {
  await writeFile(path.join(outputDir, "browser-evidence-final.json"), `${JSON.stringify(evidence, null, 2)}\n`, "utf8");
  await browser.close();
}

if (evidence.fatalError) throw new Error(evidence.fatalError.message);
