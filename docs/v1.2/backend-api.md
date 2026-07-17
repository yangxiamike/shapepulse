# V1.2 后端契约（Gate 2）

数据源保持为本机 `C:\Users\hp\Documents\zer0share`，没有增加网络数据源。

## K 线

`GET /api/bars/{code}` 支持：

- `start`、`end`：可选，格式 `YYYYMMDD`，边界包含；不传 `start` 时不限制历史起点。
- `limit`：可选正整数，返回截至 `end` 的最后 N 根周期 K 线。
- `period`：`1d|1w|1m|1q|1y`。
- `adjust`：`raw|qfq|hfq`。

响应 `range` 给出 `oldest_available`、`newest_available`、`returned_start`、`returned_end`、`has_more_before` 和 `has_more_after`。向前补载时，将当前最早交易日前一天作为下一次 `end`，并继续传相同 `limit`，直到 `has_more_before=false`。

前复权分段统一锚定该股票本地最新复权因子；OHLCV 按唯一交易日规范化，价格字段不会因两位小数截断为零。

## 筛选

`GET|POST /api/screen` 新参数：

- `industries`：申万一级行业名称或代码，多选；GET 使用逗号分隔，POST 使用数组。
- `market_cap_min_yi`、`market_cap_max_yi`：可空，单位亿元，非空边界均包含。两者为空即不限制；下限不能大于上限。
- `top_k`：正整数，默认 50，不再截断到旧版 200 上限；结果自然不超过实际匹配数。
- `exclude_st`：可与以上条件组合。

普通筛选默认不保存历史。返回结果含 `industry_code`、`industry_name`、`rank`、`category_rank`、`score` 和 `match_score`。
每次完成的响应还含有效期 15 分钟的 `screen_token`，用于精确保存这一次结果。

`GET /api/industries` 返回稳定排序的申万一级行业 `items`、`names`、本地文件日期 `as_of` 和来源说明。

## 用户主动筛选快照

- `POST /api/screen/snapshots`：主流程请求体为 `{ "screen_token": "..." }`，直接保存该 token 对应的完整结果和评估明细，不重算；同一 token 重试幂等。请求体为筛选参数本身或 `{ "filters": {...} }` 时会重新执行，作为旧客户端兼容兜底。
- `GET /api/screen/snapshots?page=1&page_size=20`：按保存时间倒序分页。
- `GET /api/screen/snapshots/{run_id}`：返回筛选参数、规则版本、完整结果、分类结果、排名/匹配度和 `restore.filters`。

旧的普通计算记录不会出现在主动快照列表中。

## 三类形态股票池

`GET /api/pattern/pool?category=breakout|pullback|range_bounce&limit=200`

返回项目既有三类形态之一的 `code/name/score/rank` 股票池。优先读取最近主动保存快照；没有可用快照时按当前本地数据计算，但不会写入历史。
