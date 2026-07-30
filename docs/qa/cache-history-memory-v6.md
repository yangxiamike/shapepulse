# Cache and complete-history V6 verification

## Scope

- Data source stayed on the existing local zer0share DuckDB/Pandas/NumPy path.
- Baseline is `codex/top100-performance-ux-v5` at
  `6fb928d1bb423c151a2ab413a65409678df38612`.
- Each profile used one fresh `MarketService`, one screen, 40 sequential stocks,
  then the breakout industry-strength flow.
- RSS is the Windows process working set. Raw figures are in
  `docs/qa/evidence/cache-history-memory-v6/memory-profile.json`.

## Same-workload comparison (170 bars per stock)

| Stage | V5 RSS / peak | V6 RSS / peak | Change |
| --- | ---: | ---: | ---: |
| Screen complete | 247.2 / 638.3 MB | 198.6 / 639.4 MB | RSS -19.7% |
| Stock 40 | 366.9 / 638.3 MB | 329.7 / 639.4 MB | RSS -10.1% |
| Industry strength | 754.6 / 1123.0 MB | 650.7 / 1069.8 MB | RSS -13.8%, peak -4.7% |

At stock 40, V5 retained 40 serialized bars payloads plus 40 stock DataFrames.
V6 retained 8 bars payloads plus 8 short source frames; 32 older entries had
already been evicted.

## Complete-history workload

The stricter V6 profile requested up to 10,000 daily bars for every one of the
40 stocks. The stock-frame cache stayed at zero because a complete DataFrame is
not retained beside its serialized payload.

| Stage | RSS | Peak RSS | Bars / source-frame entries |
| --- | ---: | ---: | ---: |
| Stock 20 | 729.1 MB | 729.6 MB | 8 / 0 |
| Stock 30 | 730.6 MB | 730.7 MB | 8 / 0 |
| Stock 40 | 732.2 MB | 732.8 MB | 8 / 0 |
| Industry strength after stock 40 | 970.3 MB | 1429.5 MB | 8 / 0 |

RSS flattened between stocks 20 and 40 instead of growing with every symbol.
The whole run stayed below 1.5 GB peak RSS. The industry prepared-input cache
contained exactly one entry.

## Functional checks

- Default daily view remains 110 visible bars (about six months).
- The chart data source expands to the complete locally available history in
  the background without moving the current logical range.
- Panning left reaches dates earlier than the initial visible start.
- “全部” makes visible bars equal source bars.
- Switching from `000001` to `000858` restores the 110-bar default viewport,
  then completes that stock's history independently.
