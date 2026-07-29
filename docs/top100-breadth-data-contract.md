# Top100 行业宽度数据口径

## 主口径

- 四个冻结模板各自独立排名，不做跨模板综合排名。
- 每个模板、每个交易日按单窗口 Pearson 从高到低取固定 Top100；同分时按证券代码升序，保证结果可复现。
- 相似算法不变：前复权 `log(close)`、模板与候选窗口各自独立 z 标准化、单窗口 Pearson。
- 行业块面积只使用 `top100_count`。
- 行业入选率 `selection_rate = top100_count / eligible_count`；`eligible_count` 是该模板、该交易日有完整候选窗口且仍在上市期内、归属于该行业的股票数。单位是比例，页面转成百分比显示。

## 5 日变化

- “5 日前”指当前交易日前第 5 个实际交易日，不是自然日。
- `new_count`：当前 Top100、但不在 5 个交易日前 Top100。
- `retained_count`：当前和 5 个交易日前都在 Top100。
- `exit_count`：5 个交易日前在 Top100、当前不在。
- 每模板必须满足 `new_count + retained_count = 100` 和 `exit_count + retained_count = 100`。
- 当前、新进、保留股票使用当前截面的分数、排名和行业；退出股票使用比较日截面的分数、排名和行业。

## 文件

- `outputs/shape-v2/top100-breadth-20260729/top100_membership_daily.csv`：四模板最近 65 个交易日的逐股 Top100 成员、排名、分数和候选窗口日期。
- `outputs/shape-v2/top100-breadth-20260729/top100_industry_daily.csv`：逐日行业分母、Top100 数量、入选率和 5 日迁移。
- `public/template-breadth-v3.json`：页面数据，保留旧页面可复用的 `top30`、`marketSeries`、`industrySeries` 键，但不含主产品阈值字段。

## 数据边界

- 只读取本机 `C:\Users\hp\Documents\zer0share` 和仓库既有非 sealed 成果。
- 不联网，不读取 sealed final，不使用未来收益、IC 或策略表现。
- 这些结果描述截至当日的形态相似截面，不验证后续表现，也不能据此判断市场是否仍有抛物线行情。
