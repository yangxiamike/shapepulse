# 形态 V2 独立模板发现 v1

## 触发原因

用户确认 AI 对 15 条单样本的好/坏/边界判断全部一致，但指出健康上升趋势的候选池存在选择偏差：样本普遍接近尾端、波动较大，不能代表完整健康趋势。

根因是此前只在临时距离模型的 Top20 内挑样本。模型本身偏向近期涨幅和末端形态，因此“在偏池里挑较好样本”仍然会继承偏差。

## 修正方法

- 改用尚未参与 tuning 的独立 `template` 分区。
- 排除三轮校准和 baseline-v1.1 tuning 评审证券。
- 从本机 zer0share 快照 `20260727` 的 2,553 个有效候选中筛选。
- 预筛明确要求上升在完整 120 日中展开，前段已经存在趋势。
- 压低尾端涨幅集中、近期高波动、单日尖峰、过度延伸和大区间样本。
- AI 再对 Top20 做视觉筛选，分成代表、边界和剔除三组。

## 新旧候选池对比

| 指标中位数 | 旧模型健康趋势 Top20 | 独立 template Top20 |
|---|---:|---:|
| 20日波动 | 5.16% | 3.84% |
| 60日波动 | 4.06% | 3.34% |
| 末端涨幅集中度 | 70.35% | 36.96% |
| 120日趋势拟合度 | 0.253 | 0.608 |

新候选池显著降低尾端集中和近期波动，并提高完整窗口趋势连续性。

## 当前短名单

- 代表模板：6 条，其中 3 分 4 条、2 分 2 条。
- 边界模板：4 条。
- 明确不进入代表模板：6 条。

这些仍是 `ai_visual_provisional`，用于下一版模板统计与排名对比，不冒充封存评估或成熟人工标签。

产物：

- `outputs/shape-v2/template-discovery-v1/healthy-uptrend/visual-shortlist.html`
- `outputs/shape-v2/template-discovery-v1/healthy-uptrend/visual-shortlist.json`
- `outputs/shape-v2/template-discovery-v1/healthy-uptrend/index.html`
- 私有审计：`outputs/shape-v2/.private/audits/template-discovery-v1-healthy-uptrend-audit.json`
