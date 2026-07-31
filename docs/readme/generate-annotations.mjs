import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "@playwright/test";

const assetDir = path.resolve("docs/readme");
const jobs = [
  {
    input: "template-library.png",
    output: "template-library-annotated.png",
    markers: [
      [1, 12, 27],
      [2, 51, 24],
      [3, 55, 47],
      [4, 55, 71],
      [5, 95, 6],
    ],
  },
  {
    input: "new-template.png",
    output: "new-template-annotated.png",
    markers: [
      [1, 47, 11],
      [2, 50, 45],
      [3, 55, 94],
    ],
  },
  {
    input: "market-detail.png",
    output: "market-detail-annotated.png",
    markers: [
      [1, 4, 28],
      [2, 46, 16],
      [3, 38, 57],
      [4, 86, 29],
      [5, 86, 72],
      [6, 97, 65],
    ],
  },
  {
    input: "industry-breadth.png",
    output: "industry-breadth-annotated.png",
    markers: [
      [1, 50, 10],
      [2, 50, 16],
      [3, 35, 48],
      [4, 26, 28],
      [5, 87, 38],
      [6, 25, 60],
      [7, 50, 71],
    ],
  },
];

const browser = await chromium.launch({ channel: "chrome", headless: true });
try {
  for (const job of jobs) {
    const bytes = await fs.readFile(path.join(assetDir, job.input));
    const dataUrl = `data:image/png;base64,${bytes.toString("base64")}`;
    const page = await browser.newPage({ viewport: { width: 800, height: 600 } });
    await page.setContent(`
      <!doctype html>
      <meta charset="utf-8">
      <style>
        * { box-sizing: border-box; }
        html, body { margin: 0; padding: 0; background: transparent; }
        #stage { position: relative; display: inline-block; line-height: 0; }
        #source { display: block; max-width: none; }
        .marker {
          position: absolute;
          transform: translate(-50%, -50%);
          display: grid;
          place-items: center;
          width: 54px;
          height: 54px;
          border: 5px solid #78e0c0;
          border-radius: 999px;
          background: #0b0f12;
          color: #ffffff;
          box-shadow: 0 3px 14px rgba(0, 0, 0, 0.34);
          font: 800 28px/1 Arial, "Microsoft YaHei", sans-serif;
        }
      </style>
      <div id="stage">
        <img id="source" src="${dataUrl}" alt="">
        ${job.markers.map(([label, x, y]) =>
          `<span class="marker" style="left:${x}%;top:${y}%">${label}</span>`
        ).join("")}
      </div>
    `);
    await page.locator("#source").evaluate((image) => image.decode());
    const size = await page.locator("#stage").evaluate((element) => ({
      width: Math.ceil(element.getBoundingClientRect().width),
      height: Math.ceil(element.getBoundingClientRect().height),
    }));
    await page.setViewportSize(size);
    await page.locator("#stage").screenshot({
      path: path.join(assetDir, job.output),
      animations: "disabled",
    });
    await page.close();
  }
} finally {
  await browser.close();
}
