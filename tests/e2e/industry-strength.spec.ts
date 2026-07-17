import { expect, test } from "@playwright/test";

test("industry strength navigation, clip, heat detail, trend and ranking stay linked", async ({ page }) => {
  const dates = Array.from({ length: 24 }, (_, index) => `202601${String(index + 1).padStart(2, "0")}`);
  const rows = Array.from({ length: 31 }, (_, industryIndex) => {
    const points = dates.map((date, dateIndex) => {
      const count = industryIndex === 30 ? Math.max(0, dateIndex - 20) : Math.max(0, 20 - industryIndex + dateIndex % 3);
      return {
        date,
        count,
        percent: count,
        heat_level: count === 0 ? 0 : count <= 2 ? 1 : count <= 4 ? 2 : count <= 7 ? 3 : count <= 10 ? 4 : 5,
        change: dateIndex ? count - (industryIndex === 30 ? Math.max(0, dateIndex - 21) : Math.max(0, 20 - industryIndex + (dateIndex - 1) % 3)) : 0,
        stocks: count ? [{ ts_code: `${String(industryIndex).padStart(6, "0")}.SZ`, code: String(industryIndex).padStart(6, "0"), name: `股票${industryIndex}`, score: 80 }] : [],
      };
    });
    return {
      code: `I${String(industryIndex).padStart(2, "0")}`,
      name: `行业${String(industryIndex).padStart(2, "0")}`,
      points,
      counts: points.map(point => point.count),
      current_count: points.at(-1)!.count,
      current_percent: points.at(-1)!.count,
      change_previous: points.at(-1)!.change,
      change_four_samples: points.at(-1)!.count - points.at(-5)!.count,
      cumulative_count: points.reduce((sum, point) => sum + point.count, 0),
      rank: industryIndex + 1,
      status: industryIndex === 30 ? "新进入行业" : "相对稳定",
      stocks: points.at(-1)!.stocks,
    };
  });
  rows[30].rank = 8;
  const defaultVisibleCodes = [...rows.slice(0, 15).map(row => row.code), rows[30].code];
  await page.route("**/api/industry-strength?**", route => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      pattern: "breakout",
      pattern_label: "突破启动",
      requested_end_date: null,
      resolved_end_date: dates.at(-1),
      sampling: { top_n: 100, industry_level: 1, lookback_trading_days: 120, sample_every_trading_days: 5, sample_count: 24, dates, denominator: 100 },
      scope: { board: "主板", exclude_st: true, industry_count: 31, industry_source: "申万一级行业（本地 zer0share）" },
      metrics: {
        covered_industries: 21, strongest_industry: "行业00", strongest_count: rows[0].current_count,
        fastest_strengthening: "行业30", fastest_strengthening_change: 3,
        fastest_weakening: "行业20", fastest_weakening_change: -2,
        top_three_percent: 60, new_top_ten_count: 1, concentration_state: "集中", concentration_change: 6,
      },
      analysis: ["当前最强为行业00。", "行业30属于快速启动。", "行业分布集中。"],
      rules: { rapid_start_delta: 3, rapid_start_explanation: "单个 5 交易日采样间隔增加至少 3 只（3 个百分点）", high_rank_cutoff: 5 },
      display: { default_visible_count: 16, default_visible_codes: defaultVisibleCodes, folded_count: 15, folded_current_count: 12, folded_current_percent: 12 },
      industries: rows,
      ranking: [...rows].sort((a, b) => a.rank - b.rank),
      actual_top_by_date: Object.fromEntries(dates.map(date => [date, 100])),
      missing_industry_by_date: Object.fromEntries(dates.map(date => [date, 0])),
      warnings: [],
      cache_hit: false,
      elapsed_ms: 1200,
      as_of: { daily: dates.at(-1), st: dates.at(-1) },
    }),
  }));

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/industry-strength");
  await expect(page.getByRole("heading", { name: "行业强弱", exact: true })).toBeVisible();
  await expect(page.locator(".heat-row-label")).toHaveCount(16);
  await expect(page.getByRole("button", { name: /已折叠 15 个行业/ })).toContainText("12%");

  await page.getByRole("button", { name: /已折叠 15 个行业/ }).click();
  await expect(page.locator(".heat-row-label")).toHaveCount(31);

  const target = page.getByRole("button", { name: /行业30 .* 3只 3%/ });
  await target.click();
  await expect(page.getByTestId("industry-point-detail")).toContainText("行业30");
  await expect(page.getByTestId("industry-point-detail")).toContainText("3 只");
  await expect(page.locator(".trend-legend")).toContainText("行业30");

  await page.locator(".industry-ranking-table tbody tr").filter({ hasText: "行业30" }).getByRole("button", { name: /查看 3 只/ }).click();
  await expect(page.getByTestId("industry-stock-detail")).toContainText("股票30");
  await expect(page.getByRole("link", { name: "行业强弱" })).toHaveAttribute("href", "/industry-strength");
});
