import { chromium } from "@playwright/test";
import { createServer } from "node:http";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const projectRoot = path.resolve(import.meta.dirname, "..");
const output = path.join(
  projectRoot,
  "outputs",
  "shape-v2",
  "template-statistical-validation-v1-20260729",
);

const mime = {
  ".html": "text/html; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".csv": "text/csv; charset=utf-8",
  ".png": "image/png",
};

const server = createServer(async (request, response) => {
  const requested = request.url === "/" ? "/index.html" : request.url;
  const file = path.resolve(output, `.${requested}`);
  if (!file.startsWith(`${output}${path.sep}`)) {
    response.writeHead(403);
    response.end("forbidden");
    return;
  }
  try {
    const body = await readFile(file);
    response.writeHead(200, {
      "content-type": mime[path.extname(file)] || "application/octet-stream",
    });
    response.end(body);
  } catch {
    response.writeHead(404);
    response.end("not found");
  }
});

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const address = server.address();
const url = `http://127.0.0.1:${address.port}/`;
const browser = await chromium.launch({ headless: true });
const results = {
  url: "local ephemeral server",
  checkedAt: new Date().toISOString(),
  consoleErrors: [],
  pageErrors: [],
  desktop: {},
  mobile: {},
  interactions: {},
};

async function inspectPage(page, target) {
  page.on("console", (message) => {
    if (message.type() === "error") results.consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => results.pageErrors.push(error.message));
  await page.goto(url, { waitUntil: "networkidle" });
  await page.locator("h1").waitFor();
  const layout = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    title: document.title,
    reviewLabel: document.querySelector(".notice")?.textContent?.trim(),
    tabCount: document.querySelectorAll(".tab").length,
    hypothesisCount: document.querySelectorAll("#hypotheses .card").length,
  }));
  results[target] = {
    ...layout,
    noHorizontalOverflow: layout.scrollWidth <= layout.viewport + 1,
  };
  return page;
}

try {
  const desktopContext = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    deviceScaleFactor: 1,
  });
  const desktop = await desktopContext.newPage();
  await inspectPage(desktop, "desktop");

  const tabLabels = [];
  for (const tab of await desktop.locator(".tab").all()) {
    tabLabels.push((await tab.textContent()).trim());
    await tab.click();
    await desktop.waitForTimeout(40);
    if ((await desktop.locator(".panel.active").count()) !== 1) {
      throw new Error("模板切换后活动面板数量不是1");
    }
  }
  await desktop.locator(".tab").first().click();
  await desktop.locator('.kbtn[data-template="fresh_breakout"][data-k="10"]').click();
  const top10Text = await desktop
    .locator("#concentration-fresh_breakout")
    .textContent();
  await desktop.locator('[data-overlap="100"]').click();
  const overlapCellCount = await desktop.locator("#overlap .overlap div").count();
  results.interactions = {
    templateTabs: tabLabels,
    topKSwitchWorked: top10Text.includes("行业覆盖"),
    overlapSwitchWorked: overlapCellCount === 25,
  };
  await desktop.screenshot({
    path: path.join(output, "qa-desktop.png"),
    fullPage: true,
  });
  await desktopContext.close();

  const mobileContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 1,
    isMobile: true,
  });
  const mobile = await mobileContext.newPage();
  await inspectPage(mobile, "mobile");
  await mobile.locator(".tab").nth(3).click();
  await mobile.waitForTimeout(80);
  results.mobile.activeTemplate = (
    await mobile.locator(".panel.active h2").textContent()
  ).trim();
  await mobile.screenshot({
    path: path.join(output, "qa-mobile.png"),
    fullPage: true,
  });
  await mobileContext.close();

  results.pass =
    results.consoleErrors.length === 0 &&
    results.pageErrors.length === 0 &&
    results.desktop.noHorizontalOverflow &&
    results.mobile.noHorizontalOverflow &&
    results.desktop.tabCount === 4 &&
    results.desktop.hypothesisCount === 8 &&
    Object.values(results.interactions).every(Boolean);
  await writeFile(
    path.join(output, "qa-browser-results.json"),
    `${JSON.stringify(results, null, 2)}\n`,
    "utf8",
  );
  if (!results.pass) throw new Error("页面 QA 未通过");
  console.log(JSON.stringify(results, null, 2));
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
