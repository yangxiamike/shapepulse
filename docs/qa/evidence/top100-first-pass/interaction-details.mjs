import { chromium } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";

const baseURL = "http://localhost:3102";
const evidenceDir = path.resolve("docs/qa/evidence/top100-first-pass");
const browser = await chromium.launch({ channel: "chrome", headless: true });
const result = { baseURL, http: [], breadth: {}, newTemplate: {}, keyboard: {} };

for (const endpoint of [
  "/templates",
  "/templates/new",
  "/template-breadth-v3",
  "/market?code=301234&template=fresh_breakout",
]) {
  const response = await fetch(`${baseURL}${endpoint}`);
  result.http.push({
    endpoint,
    status: response.status,
    contentType: response.headers.get("content-type"),
  });
}
for (const endpoint of [
  "/api/health",
  "/api/templates",
  "/api/templates/fresh_breakout",
  "/api/templates/fresh_breakout/stocks?limit=3",
  "/api/bars/301234?period=1d&limit=80",
]) {
  const response = await fetch(`http://127.0.0.1:8877${endpoint}`);
  result.http.push({
    endpoint: `backend:${endpoint}`,
    status: response.status,
    contentType: response.headers.get("content-type"),
  });
}

{
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.goto(`${baseURL}/template-breadth-v3`, { waitUntil: "networkidle" });
  const industry = page.locator("button", { hasText: "21/502" }).first();
  result.breadth.industryMatchCount = await industry.count();
  if (await industry.count()) {
    const before = await industry.evaluate(element => ({
      outline: getComputedStyle(element).outline,
      background: getComputedStyle(element).backgroundColor,
    }));
    await industry.hover();
    const hover = await industry.evaluate(element => ({
      outline: getComputedStyle(element).outline,
      background: getComputedStyle(element).backgroundColor,
      transform: getComputedStyle(element).transform,
    }));
    await industry.focus();
    const focus = await industry.evaluate(element => ({
      outline: getComputedStyle(element).outline,
      boxShadow: getComputedStyle(element).boxShadow,
    }));
    result.breadth.visualStates = { before, hover, focus };
    await industry.click();
    await page.waitForTimeout(500);
    result.breadth.afterIndustryText = (await page.locator("body").innerText()).slice(-9000);
    result.breadth.stockMarketLinks = await page.locator('a[href*="/market?"][href*="template="]').count();
    result.breadth.selectedButtons = await page.locator('button[aria-pressed="true"]').count();
    await page.screenshot({
      path: path.join(evidenceDir, "desktop-1440-breadth-industry-selected.png"),
      fullPage: true,
    });
  }
  await page.close();
}

{
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.goto(`${baseURL}/templates/new`, { waitUntil: "networkidle" });
  const search = page.getByPlaceholder(/股票名称|代码|拼音/);
  await search.fill("平安银行");
  await page.waitForTimeout(800);
  await page.getByRole("button", { name: /平安银行/ }).first().click();
  await page.waitForTimeout(1800);
  const chart = page.locator('svg[aria-label*="K 线"]').first();
  const handles = chart.locator('g[class*="handle"]');
  result.newTemplate.handleCount = await handles.count();
  result.newTemplate.chartBox = await chart.boundingBox();
  result.newTemplate.initialText = (await page.locator("body").innerText()).slice(-2500);
  if ((await handles.count()) === 2) {
    const startHandle = await handles.nth(0).boundingBox();
    const chartBox = await chart.boundingBox();
    if (startHandle && chartBox) {
      await page.mouse.move(startHandle.x + startHandle.width / 2, startHandle.y + 30);
      await page.mouse.down();
      await page.mouse.move(Math.max(chartBox.x + 5, startHandle.x - 150), startHandle.y + 30, { steps: 10 });
      await page.mouse.up();
      await page.waitForTimeout(250);
      result.newTemplate.afterOversizeText = (await page.locator("body").innerText()).slice(-2500);
      await page.screenshot({
        path: path.join(evidenceDir, "desktop-1440-new-template-invalid-over240.png"),
        fullPage: true,
      });
    }
    const endHandle = await handles.nth(1).boundingBox();
    const startAfter = await handles.nth(0).boundingBox();
    if (endHandle && startAfter) {
      await page.mouse.move(endHandle.x + endHandle.width / 2, endHandle.y + 30);
      await page.mouse.down();
      await page.mouse.move(startAfter.x + startAfter.width / 2 + 2, endHandle.y + 30, { steps: 10 });
      await page.mouse.up();
      await page.waitForTimeout(250);
      result.newTemplate.afterUndersizeText = (await page.locator("body").innerText()).slice(-2500);
      await page.screenshot({
        path: path.join(evidenceDir, "desktop-1440-new-template-invalid-under20.png"),
        fullPage: true,
      });
    }
  }
  await page.close();
}

{
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.goto(`${baseURL}/templates/new`, { waitUntil: "networkidle" });
  await page.keyboard.press("Tab");
  result.keyboard.firstFocus = await page.evaluate(() => ({
    tag: document.activeElement?.tagName,
    text: document.activeElement?.textContent?.trim(),
    aria: document.activeElement?.getAttribute("aria-label"),
    outline: document.activeElement ? getComputedStyle(document.activeElement).outline : null,
    boxShadow: document.activeElement ? getComputedStyle(document.activeElement).boxShadow : null,
  }));
  await page.close();
}

await fs.writeFile(
  path.join(evidenceDir, "interaction-details.json"),
  `${JSON.stringify(result, null, 2)}\n`,
  "utf8",
);
await browser.close();
console.log(JSON.stringify({
  http: result.http,
  breadth: {
    industryMatchCount: result.breadth.industryMatchCount,
    stockMarketLinks: result.breadth.stockMarketLinks,
  },
  newTemplate: {
    handleCount: result.newTemplate.handleCount,
    over240: /240/.test(result.newTemplate.afterOversizeText ?? ""),
    under20: /20/.test(result.newTemplate.afterUndersizeText ?? ""),
  },
}, null, 2));
