# Whole-machine memory V7 verification

## Scope and invariant

- Baseline: `codex/top100-performance-ux-v5` at
  `50d55838d10472427650300a96dc4b753dee40f5`.
- Data source and calculation path remain the existing local zer0share
  DuckDB + Pandas + NumPy implementation.
- No history was clipped and no data source, adjustment, screening, or
  industry-strength definition changed.
- The same driver and the same local data were used for the baseline and V7.

## What changed

1. Complete-history and exact-bound scans use a 256 MB, two-thread,
   short-lived DuckDB connection. Closing it after each heavy stock query
   releases that scan's buffer pool instead of retaining it in the process-wide
   connection.
2. Backend metadata, stock-frame, bars, screen, completed-screen,
   industry-result, and prepared-industry-input caches have both entry and
   estimated-byte limits in addition to TTL/LRU behavior. An item larger than
   its entire budget is returned to the caller but not retained, and does not
   evict existing hot data.
3. Browser bars caching has a 16 MB byte budget, 30,000-bar budget, 12-entry
   limit, and 10-minute TTL. Complete-history source pages are removed after
   merging so the cache retains one representation.
4. One immutable chart preparation now supplies all 1/2/4 panes. Date
   normalization and candle, volume, MA5, MA10, and MA20 arrays are created once
   per bars update rather than once per chart.

## Reproduction

From the V7 worktree:

```powershell
uv run --project C:/Users/hp/Documents/zer0share python scripts/profile_memory_v7.py `
  --label v7 `
  --app-root . `
  --output docs/qa/evidence/whole-machine-memory-v7/v7-raw.json `
  --stocks 40
```

For the baseline, pass its worktree through `--app-root` and use a different
output file. The script runs a production build first, then uses vinext's
development server only as the browser asset host because the baseline
`vinext start` returns 404 for its generated `/assets/*` modules. The reported
`app_total_rss_mb` is therefore the actual application pair (backend + all
Chrome processes); development compiler RSS is recorded separately as
`host_total_including_frontend_rss_mb`.

The workload is:

- all-market combined screen with TopK 200;
- continuous complete-history browsing of 40 screened stocks;
- left drag and `全部`;
- one-chart and four-chart transitions at stocks 20 and 40;
- stock switching through the UI;
- full breakout industry-strength calculation.

Windows process trees are sampled every 0.5 seconds. Each sample includes
backend RSS/private bytes, all Chrome child-process RSS/private bytes,
application total RSS, frontend-host RSS, available physical memory, system
memory load, and pagefile usage. Browser checkpoints include CDP JS heap and DOM
metrics.

## Same-machine result

| Metric | V6 baseline | V7 | Change |
| --- | ---: | ---: | ---: |
| Backend peak RSS | 1,285.5 MB | 762.4 MB | -40.7% |
| Chrome peak RSS | 518.2 MB | 561.6 MB | +8.4% |
| Backend + Chrome peak RSS | 1,761.8 MB | 1,258.0 MB | -28.6% |
| View 20 application RSS | 1,181.9 MB | 792.6 MB | -32.9% |
| View 40 application RSS | 1,225.0 MB | 803.8 MB | -34.4% |
| View 20 to 40 change | +43.1 MB | +11.2 MB | slope reduced 74.0% |
| Industry-strength completion | 1,354.6 MB | 1,132.4 MB | -16.4% |
| Minimum system available memory | 14,745.6 MB | 14,661.6 MB | observational |

The older V6 backend-only report observed a 1,429.5 MB transient peak. The
same-harness baseline measured 1,285.5 MB, while V7 measured 762.4 MB. Both
comparisons put the backend heavy-flow peak safely below the suggested 1.1 GB
target.

V7 does not meet a strict 1.1 GB whole-application target. Its measured safe
upper bound on this workload is approximately 1.26 GB. At that peak, backend
RSS was 759.9 MB and Chrome RSS was 493.0 MB. Further reduction without changing
history or data semantics would require reducing the distinct Chrome chart
instances or reworking the industry-strength Pandas/NumPy working set; cache
trimming alone cannot safely remove that overlap.

## Stability and four-chart evidence

| Checkpoint | Backend RSS | Chrome RSS | Application RSS | JS heap |
| --- | ---: | ---: | ---: | ---: |
| View 10, one chart | 287.4 MB | 469.3 MB | 756.7 MB | 52.5 MB |
| View 20, four charts | 290.8 MB | 501.7 MB | 792.6 MB | 65.5 MB |
| View 30, one chart | 294.8 MB | 488.8 MB | 783.5 MB | 27.4 MB |
| View 40, four charts | 297.4 MB | 499.1 MB | 796.5 MB | 46.0 MB |

The four-chart application checkpoint is about 1.05 times the nearby one-chart
checkpoint, not four times. From stock 20 to stock 40, backend RSS rose only
12.1 MB and application RSS 11.2 MB; Chrome was effectively flat. This is a
bounded plateau rather than retained complete-history data per symbol.

System pagefile usage was also captured, but the machine was not isolated from
other applications. The observed range was 27,788.2–29,248.7 MB for the
baseline run and 28,001.8–28,948.8 MB for V7. These values are evidence of host
state, not an attribution to this application.

## Functional and automated verification

- Backend unit tests cover byte-weight eviction, combined TTL/LRU behavior,
  oversized single entries, and data snapshot-token invalidation.
- V7 E2E covers complete history, default 110-bar viewport, left drag, `全部`,
  one/four charts, stock switching, viewport reset, and attached CDP browser
  memory evidence.
- Raw data:
  - `docs/qa/evidence/whole-machine-memory-v7/v6-baseline-raw.json`
  - `docs/qa/evidence/whole-machine-memory-v7/v6-baseline-raw.events.jsonl`
  - `docs/qa/evidence/whole-machine-memory-v7/v7-raw.json`
  - `docs/qa/evidence/whole-machine-memory-v7/v7-raw.events.jsonl`
