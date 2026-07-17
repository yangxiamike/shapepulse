import { expect, test } from "@playwright/test";

function slope(values: number[]) {
  const recent = values.slice(-4);
  const mean = recent.reduce((sum, value) => sum + value, 0) / recent.length;
  const xMean = 1.5;
  return Number((
    recent.reduce((sum, value, index) => sum + (index - xMean) * (value - mean), 0) / 5
  ).toFixed(2));
}

test("industry rotation heatmap, preview, trend focus, selector and ranking stay linked", async ({ page }) => {
  const dates = Array.from({ length: 24 }, (_, index) => `202601${String(index + 1).padStart(2, "0")}`);
  const rows = Array.from({ length: 31 }, (_, industryIndex) => {
    const counts = dates.map((_, dateIndex) => {
      if (industryIndex === 30) return dateIndex < 23 ? 0 : 3;
      if (industryIndex < 7) return Math.max(0, dateIndex - 19) * (7 - industryIndex);
      if (industryIndex < 27) return Math.max(0, 24 - dateIndex) * Math.max(1, 5 - (industryIndex % 5));
      return industryIndex - 27;
    });
    const recentSlope = slope(counts);
    const points = dates.map((date, dateIndex) => {
      const count = counts[dateIndex];
      return {
        date,
        count,
        percent: count,
        heat_level: count === 0 ? 0 : count <= 2 ? 1 : count <= 4 ? 2 : count <= 7 ? 3 : count <= 10 ? 4 : 5,
        change: dateIndex ? count - counts[dateIndex - 1] : 0,
        stocks: count ? [{ ts_code: `${String(industryIndex).padStart(6, "0")}.SZ`, code: String(industryIndex).padStart(6, "0"), name: `股票${industryIndex}`, score: 80 }] : [],
      };
    });
    const status = industryIndex === 30
      ? "↗ 快速启动"
      : recentSlope > 0
        ? "↑ 持续增强"
        : recentSlope < 0
          ? "↓ 正在走弱"
          : "→ 变化不大";
    return {
      code: `I${String(industryIndex).padStart(2, "0")}`,
      name: `行业${String(industryIndex).padStart(2, "0")}`,
      points,
      counts,
      current_count: counts.at(-1)!,
      current_percent: counts.at(-1)!,
      change_previous: points.at(-1)!.change,
      change_four_samples: counts.at(-1)! - counts.at(-4)!,
      recent_change: counts.at(-1)! - counts.at(-4)!,
      recent_slope: recentSlope,
      recent_persistence: recentSlope === 0 ? 0 : 1,
      latest_effective_percent: [...counts.slice(-4)].reverse().find(Boolean) || 0,
      cumulative_count: counts.reduce((sum, value) => sum + value, 0),
      rank: industryIndex + 1,
      current_rank: industryIndex + 1,
      rotation_rank: 0,
      status,
      status_detail: `${recentSlope >= 0 ? "+" : ""}${recentSlope.toFixed(2)} 只/采样点 · 3/3 个间隔同向`,
      stocks: points.at(-1)!.stocks,
    };
  });
  const ranking = [...rows].sort((a, b) =>
    Math.abs(b.recent_slope) - Math.abs(a.recent_slope) || a.code.localeCompare(b.code),
  );
  ranking.forEach((row, index) => { row.rotation_rank = index + 1; });
  const rising = ranking.filter(row => row.recent_slope > 0).slice(0, 4);
  const falling = ranking.filter(row => row.recent_slope < 0).slice(0, 4);
  const selected = [...rising, ...falling];
  for (const row of ranking) {
    if (selected.length === 12) break;
    if (!selected.includes(row) && row.counts.slice(-4).some(Boolean)) selected.push(row);
  }
  selected.sort((a, b) => b.recent_slope - a.recent_slope || a.code.localeCompare(b.code));
  const defaultVisibleCodes = selected.map(row => row.code);

  let requestCount = 0;
  await page.route("**/api/industry-strength?**", async route => {
    requestCount += 1;
    if (requestCount > 1) await new Promise(resolve => setTimeout(resolve, 300));
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
      pattern: "breakout",
      pattern_label: "突破启动",
      requested_end_date: null,
      resolved_end_date: dates.at(-1),
      sampling: { top_n: 100, industry_level: 1, lookback_trading_days: 120, sample_every_trading_days: 5, sample_count: 24, dates, denominator: 100 },
      scope: { board: "主板", exclude_st: true, industry_count: 31, industry_source: "申万一级行业（本地 zer0share）" },
      metrics: {
        covered_industries: 28,
        strongest_industry: "行业00",
        strongest_count: rows[0].current_count,
        fastest_strengthening: rising[0].name,
        fastest_strengthening_change: rising[0].recent_change,
        fastest_strengthening_speed: rising[0].recent_slope,
        fastest_weakening: falling[0].name,
        fastest_weakening_change: falling[0].recent_change,
        fastest_weakening_speed: falling[0].recent_slope,
        just_started_industry: "行业30",
        just_started_count: 1,
        persistent_strengthening_count: 7,
        rising_industry_count: 8,
        falling_industry_count: 20,
        top_three_percent: 60,
        new_top_ten_count: 1,
        concentration_state: "集中",
        concentration_change: 6,
      },
      analysis: ["行业00上升最快。", "行业07下降最快。", "行业30属于刚启动。", "行业分布集中。"],
      rules: {
        rapid_start_delta: 3,
        rapid_start_explanation: "从低位单个 5 交易日采样间隔增加至少 3 只（3 个百分点）",
        high_rank_cutoff: 5,
        recent_window_points: 4,
        slope_explanation: "最近 4 个采样点做线性回归；斜率单位为只/采样点，正数上升、负数下降",
        stable_sort_explanation: "同速时依次按方向持续性、最新有效占比、行业代码排序",
        directional_slots: 4,
      },
      display: {
        default_visible_count: 12,
        default_visible_codes: defaultVisibleCodes,
        latest_first_dates: [...dates].reverse(),
        hidden_count: 19,
        folded_count: 0,
        folded_current_count: 0,
        folded_current_percent: 0,
      },
      industries: rows,
      ranking,
      actual_top_by_date: Object.fromEntries(dates.map(date => [date, 100])),
      missing_industry_by_date: Object.fromEntries(dates.map(date => [date, 0])),
      warnings: [],
      cache_hit: false,
      elapsed_ms: 1200,
        timings: { prepare_ms: 400, scoring_ms: 700, assembly_ms: 5, total_ms: 1105 },
        as_of: { daily: dates.at(-1), st: dates.at(-1) },
      }),
    });
  });

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/industry-strength");
  await expect(page.getByRole("heading", { name: "行业强弱", exact: true })).toBeVisible();

  await expect(page.locator(".heat-row-label")).toHaveCount(12);
  await expect(page.locator(".heat-time-axis time").first()).toContainText("最新 01.24");
  await expect(page.locator(".industry-fold-toggle")).toHaveCount(0);
  await expect(page.locator(".industry-ranking-table tbody tr")).toHaveCount(15);

  const targetRow = selected[0];
  const targetCell = page.locator(".heat-cell").first();
  await targetCell.hover();
  await expect(page.getByTestId("industry-point-detail")).toContainText(targetRow.name);
  await expect(page.getByTestId("industry-point-detail")).toContainText("当日入选 1 只");
  await targetCell.focus();
  await expect(page.getByTestId("industry-point-detail")).toContainText("完整 24 节点");

  const trendLine = page.locator(".trend-hit-line").first();
  await expect(page.locator(".industry-trend-chart")).toHaveAttribute("data-focus-mode", "all");
  await expect(page.locator(".trend-series.muted")).toHaveCount(0);
  await expect(page.locator(".trend-series.active")).toHaveCount(0);
  await trendLine.dispatchEvent("pointerover");
  await expect(page.locator(".trend-series.muted")).toHaveCount(4);
  await expect(page.locator(".trend-series.active")).toHaveCount(1);
  await expect(page.locator(".industry-trend-chart")).toHaveAttribute("data-focus-mode", "single");
  await expect(page.locator(".trend-focus-summary")).toContainText(rising[0].name);
  await trendLine.dispatchEvent("pointerout");
  await expect(page.locator(".trend-series.muted")).toHaveCount(0);
  await expect(page.locator(".industry-trend-chart")).toHaveAttribute("data-focus-mode", "all");

  await trendLine.focus();
  await expect(page.locator(".trend-series.muted")).toHaveCount(4);
  await expect(page.locator(".trend-series.active")).toHaveCount(1);
  await trendLine.blur();
  await expect(page.locator(".trend-series.muted")).toHaveCount(0);
  await expect(page.locator(".trend-series.active")).toHaveCount(0);

  const selector = page.getByRole("listbox", { name: "行业选择器" });
  const arbitrary = ranking[10];
  await page.getByRole("option", { name: new RegExp(arbitrary.name) }).click();
  await expect(page.getByRole("option", { name: new RegExp(arbitrary.name) })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".trend-series.muted")).toHaveCount(0);
  await selector.focus();
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("Enter");
  await expect(selector.locator('[aria-selected="true"]')).toHaveCount(1);

  const beforeWheel = await selector.locator('[aria-selected="true"]').getAttribute("id");
  const beforeCursor = await selector.getAttribute("data-cursor");
  await selector.dispatchEvent("wheel", { deltaY: -120 });
  await expect(selector).not.toHaveAttribute("data-cursor", beforeCursor || "");
  const afterWheel = await selector.locator('[aria-selected="true"]').getAttribute("id");
  expect(afterWheel).not.toBe(beforeWheel);

  const linkedRow = page.locator(".industry-ranking-table tbody tr").first();
  await linkedRow.getByRole("button", { name: /查看/ }).click();
  await expect(page.getByTestId("industry-stock-detail")).toBeVisible();
  await expect(page.getByRole("link", { name: "行业强弱" })).toHaveAttribute("href", "/industry-strength");

  const infoButton = page.getByRole("button", { name: "趋势图交互说明" });
  await infoButton.focus();
  await expect(infoButton).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(".industry-info-tip.open [role=tooltip]")).toContainText("默认所有展示线条同等清晰");
  await page.keyboard.press("Escape");
  await expect(infoButton).toHaveAttribute("aria-expanded", "false");

  await page.getByRole("button", { name: "刷新截面" }).click();
  await expect(page.getByRole("status")).toContainText("旧结果保持可读");
  await expect(page.locator(".heat-row-label")).toHaveCount(12);
  await expect(page.locator(".industry-ranking-table tbody tr")).toHaveCount(15);
  await expect(page.getByRole("status")).toBeHidden();
});
