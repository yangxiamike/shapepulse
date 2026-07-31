# 形态分类 V2 样本切分与泄漏防护

## 当前样本角色

| 样本 | 数量 | 角色 | 能做什么 | 不能做什么 |
|---|---:|---|---|---|
| C1/C2/C3 | 54 | calibration | 定义、因子方向、权重先验、临时模板 | 独立调优成绩、封存测试成绩 |
| baseline-v1.1 排名包 | 118 | tuning review | 找严重错误、比较调优前后 | 最终评估 |
| dedicated template | 0 | 尚未标注 | 未来构造正式统计模板 | 当前不得虚构 |
| final evaluation | 0 | 尚未生成 | 算法冻结后一次性评估 | 当前不得查看或调参 |

当前临时模板使用了校准样本中人工评分 `>=2` 的片段。它是小样本降级方案，输出文件明确写着 `calibration_prior_only` 和 `formal_scoring_enabled=false`。

## 固定切分

- 分组单位是源证券；同一证券的相邻日期、同一段形态不得跨集合。
- 私有 `source_group_id` 由本机密钥对证券代码做 HMAC 得到。
- 新证券按稳定哈希固定进入 `template / tuning / final_evaluation = 50% / 25% / 25%`。
- 当前排名只读取 `tuning` 分区；`template` 和 `final_evaluation` 分区没有进入排名或人工评审。
- C1/C2/C3 的 54 只证券全部从本轮 tuning 候选中排除。

## 封存规则

1. 先完成独立 template 标注，生成正式模板。
2. 在 tuning 排名上做基准版与调优版对比。
3. 冻结事实、因子向量、模板、权重、软评分和核心门槛。
4. 最后才生成并打开 final evaluation。
5. 若根据 final evaluation 的错误继续修改，原 final evaluation 立即降级为 tuning；必须用未见过的新证券重建封存集。

## 每次生成必须通过

- 公开样本只有匿名 `t/open/high/low/close/volume` 和共用事实。
- 最后一根 K 线等于私有审计中的评分日；不得包含评分日之后的行。
- 公开内容哈希必须同时匹配公开 manifest 和私有 audit。
- 同一证券、同一 `source_group_id` 不得跨 split。
- 校准、模板、调优、封存评估的证券集合必须互斥。
- `network_used=false`，数据快照来自本机 zer0share。
- 不计算或保存任何未来收益字段。
