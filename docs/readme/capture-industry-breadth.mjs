import path from "node:path";
import { chromium } from "@playwright/test";

const baseUrl = process.env.SHAPEPULSE_BASE_URL || "http://localhost:3000";
const output = path.resolve("docs/readme/industry-breadth.png");

const browser = await chromium.launch({
  channel: "chrome",
  headless: true,
  args: ["--disable-gpu"],
});

try {
  const page = await browser.newPage({
    viewport: { width: 1900, height: 956 },
    locale: "zh-CN",
    colorScheme: "light",
  });
  await page.goto(`${baseUrl}/template-breadth-v3`, {
    waitUntil: "networkidle",
  });
  await page
    .getByRole("slider", { name: "选择行业空间历史交易日" })
    .waitFor({ state: "visible" });
  await page.screenshot({
    path: output,
    fullPage: true,
    animations: "disabled",
    caret: "hide",
  });
} finally {
  await browser.close();
}
