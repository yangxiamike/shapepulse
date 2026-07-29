import { chromium } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";

const baseURL = "http://localhost:3103";
const out = path.resolve("docs/qa/evidence/top100-fixed-pass");
const browser = await chromium.launch({ channel: "chrome", headless: true });
const context = await browser.newContext({
  viewport: { width: 390, height: 844 },
  locale: "zh-CN",
  hasTouch: true,
  isMobile: true,
});
const page = await context.newPage();
const result = {
  baseURL,
  viewport: { width: 390, height: 844 },
  console: [],
  pageErrors: [],
  requestFailures: [],
};
page.on("console", message => {
  if (["error", "warning"].includes(message.type())) {
    result.console.push({ type: message.type(), text: message.text() });
  }
});
page.on("pageerror", error => result.pageErrors.push(String(error)));
page.on("requestfailed", request => {
  result.requestFailures.push({
    url: request.url(),
    failure: request.failure()?.errorText ?? "unknown",
  });
});

const response = await page.goto(`${baseURL}/templates/new`, {
  waitUntil: "networkidle",
  timeout: 60_000,
});
result.httpStatus = response?.status() ?? null;
await page.getByPlaceholder(/股票名称、代码或拼音/).fill("平安银行");
await page.waitForTimeout(700);
await page.getByRole("button", { name: /平安银行/ }).first().click();
await page.waitForTimeout(1700);

const start = page.getByRole("slider", { name: "模板窗口开始边界" });
const box = await start.boundingBox();
if (!box) throw new Error("start boundary was not rendered");
const before = Number(await start.getAttribute("aria-valuenow"));
const boundaryCenterX = box.x + box.width / 2;
const testX = boundaryCenterX - 18;
const testY = box.y + Math.min(80, box.height / 2);

await page.mouse.move(testX, testY);
await page.mouse.down();
await page.mouse.move(testX - 14, testY, { steps: 8 });
await page.mouse.up();
await page.waitForTimeout(250);

const after = Number(await start.getAttribute("aria-valuenow"));
Object.assign(result, {
  renderedHandleBox: box,
  captureRadiusPx: 22,
  effectiveHitWidthPx: 44,
  testedOffsetPx: -18,
  draggedScreenDistancePx: -14,
  before,
  after,
  moved: after !== before,
  directionCorrect: after < before,
  bodyValidation: (await page.locator("body").innerText()).match(/\d+ 个交易日[\s\S]{0,80}/)?.[0] ?? "",
});

await page.screenshot({
  path: path.join(out, "final-touch-mobile-offset18.png"),
  fullPage: true,
});
await fs.writeFile(
  path.join(out, "final-touch-results.json"),
  `${JSON.stringify(result, null, 2)}\n`,
  "utf8",
);
await browser.close();
console.log(JSON.stringify(result, null, 2));
