import { chromium } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";

const baseURL = "http://localhost:3102";
const evidenceDir = path.resolve("docs/qa/evidence/top100-first-pass");
const sizes = [
  { name: "desktop-1440", width: 1440, height: 1000 },
  { name: "narrow-1024", width: 1024, height: 900 },
  { name: "mobile-390", width: 390, height: 844 },
];
const routes = [
  { name: "breadth", path: "/template-breadth-v3" },
  { name: "templates", path: "/templates" },
  { name: "new-template", path: "/templates/new" },
];

await fs.mkdir(evidenceDir, { recursive: true });
const browser = await chromium.launch({
  channel: "chrome",
  headless: true,
  args: ["--disable-gpu"],
});
const result = {
  startedAt: new Date().toISOString(),
  baseURL,
  http: [],
  pages: [],
  interactions: [],
};

for (const size of sizes) {
  const context = await browser.newContext({
    viewport: { width: size.width, height: size.height },
    locale: "zh-CN",
    colorScheme: "light",
  });
  for (const route of routes) {
    const page = await context.newPage();
    const record = {
      size: size.name,
      route: route.path,
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
    try {
      const response = await page.goto(`${baseURL}${route.path}`, {
        waitUntil: "networkidle",
        timeout: 60_000,
      });
      record.status = response?.status() ?? null;
      await page.waitForTimeout(1000);
      record.title = await page.title();
      record.bodyText = (await page.locator("body").innerText()).slice(0, 20_000);
      record.buttons = await page.getByRole("button").allTextContents();
      record.links = await page.getByRole("link").evaluateAll(nodes =>
        nodes.map(node => ({
          text: (node.textContent ?? "").trim(),
          href: node.getAttribute("href"),
        })),
      );
      record.horizontalOverflow = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));
      record.elements = await page.evaluate(() => ({
        canvas: document.querySelectorAll("canvas").length,
        svg: document.querySelectorAll("svg").length,
        focusable: document.querySelectorAll(
          'a[href],button,input,select,textarea,[tabindex]:not([tabindex="-1"])',
        ).length,
      }));
      await page.screenshot({
        path: path.join(evidenceDir, `${size.name}-${route.name}.png`),
        fullPage: true,
      });
    } catch (error) {
      record.navigationError = String(error);
    }
    result.pages.push(record);
    await page.close();
  }
  await context.close();
}

// Desktop interaction path: breadth -> industry -> stock -> market context.
{
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    locale: "zh-CN",
  });
  const page = await context.newPage();
  const record = { name: "breadth-industry-stock", steps: [], errors: [] };
  page.on("pageerror", error => record.errors.push(`pageerror: ${String(error)}`));
  page.on("console", message => {
    if (message.type() === "error") record.errors.push(`console: ${message.text()}`);
  });
  await page.goto(`${baseURL}/template-breadth-v3`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  record.steps.push({
    url: page.url(),
    heading: await page.getByRole("heading").allTextContents(),
    buttons: await page.getByRole("button").allTextContents(),
  });
  const industryButtons = page.locator("button").filter({ hasText: /Top100|新进|保留|退出/ });
  record.industryButtonCount = await industryButtons.count();
  if (record.industryButtonCount > 0) {
    await industryButtons.first().click();
    await page.waitForTimeout(400);
    record.steps.push({
      afterIndustryClick: (await page.locator("body").innerText()).slice(-6000),
    });
    await page.screenshot({
      path: path.join(evidenceDir, "desktop-1440-breadth-after-industry-click.png"),
      fullPage: true,
    });
  }
  result.interactions.push(record);
  await context.close();
}

// Desktop interaction path: template row -> market -> compact/expand.
{
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    locale: "zh-CN",
  });
  const page = await context.newPage();
  const record = { name: "template-market-compact", steps: [], errors: [] };
  page.on("pageerror", error => record.errors.push(`pageerror: ${String(error)}`));
  page.on("console", message => {
    if (message.type() === "error") record.errors.push(`console: ${message.text()}`);
  });
  await page.goto(`${baseURL}/templates`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  const candidateLinks = page.locator('a[href*="/market?"][href*="template="]');
  record.candidateLinkCount = await candidateLinks.count();
  if (record.candidateLinkCount > 0) {
    record.firstCandidateHref = await candidateLinks.first().getAttribute("href");
    await candidateLinks.first().click();
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1200);
    record.steps.push({
      marketUrl: page.url(),
      marketButtons: await page.getByRole("button").allTextContents(),
      marketLinks: await page.getByRole("link").allTextContents(),
      text: (await page.locator("body").innerText()).slice(0, 12_000),
    });
    await page.screenshot({
      path: path.join(evidenceDir, "desktop-1440-market-expanded.png"),
      fullPage: true,
    });
    const compact = page.getByRole("button", { name: /紧凑|收起/ }).first();
    if (await compact.count()) {
      await compact.click();
      await page.waitForTimeout(500);
      record.steps.push({
        afterCompactButtons: await page.getByRole("button").allTextContents(),
      });
      await page.screenshot({
        path: path.join(evidenceDir, "desktop-1440-market-compact.png"),
        fullPage: true,
      });
    }
  }
  result.interactions.push(record);
  await context.close();
}

// New-template real search and selection; do not submit/persist.
{
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    locale: "zh-CN",
  });
  const page = await context.newPage();
  const record = { name: "new-template-search-brush", steps: [], errors: [] };
  page.on("pageerror", error => record.errors.push(`pageerror: ${String(error)}`));
  page.on("console", message => {
    if (message.type() === "error") record.errors.push(`console: ${message.text()}`);
  });
  await page.goto(`${baseURL}/templates/new`, { waitUntil: "networkidle" });
  const search = page.getByPlaceholder(/搜索|代码|名称/).first();
  if (await search.count()) {
    await search.fill("平安银行");
    await page.waitForTimeout(1200);
    record.steps.push({
      afterSearch: (await page.locator("body").innerText()).slice(0, 8000),
    });
    const option = page.getByRole("button", { name: /平安银行/ }).first();
    if (await option.count()) {
      await option.click();
      await page.waitForTimeout(2500);
      record.steps.push({
        afterSelect: (await page.locator("body").innerText()).slice(0, 10_000),
        buttons: await page.getByRole("button").allTextContents(),
        ranges: await page.locator('input[type="range"]').count(),
        canvas: await page.locator("canvas").count(),
      });
      await page.screenshot({
        path: path.join(evidenceDir, "desktop-1440-new-template-selected.png"),
        fullPage: true,
      });
    }
  }
  result.interactions.push(record);
  await context.close();
}

result.finishedAt = new Date().toISOString();
await fs.writeFile(
  path.join(evidenceDir, "browser-results.json"),
  `${JSON.stringify(result, null, 2)}\n`,
  "utf8",
);
await browser.close();
console.log(JSON.stringify({
  pages: result.pages.length,
  interactions: result.interactions.map(item => ({
    name: item.name,
    errors: item.errors?.length ?? 0,
  })),
}, null, 2));
