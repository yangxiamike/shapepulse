# 形态分类 V2 接入影响与兼容约定

## 当前决定

- 本阶段不改正式前端、不接正式 API。
- V1 的 `breakout / pullback / range_bounce`、历史记录和行业强弱继续可读可用。
- V2 用户可见类别固定为：
  - `fresh_breakout`：刚突破
  - `healthy_uptrend`：健康上升趋势
  - `pullback_strengthening`：回调转强
- V2 稳定后停止生成新的 `range_bounce`，但不删除、重写或伪装旧历史。

## 建议 API 契约

研究接口与正式接口都必须显式带版本，避免把 V1/V2 同名字段混用：

```json
{
  "shape_schema_version": "shape-ranking/2",
  "shape_model_version": "shape-v2.x",
  "as_of": "YYYYMMDD",
  "category": "fresh_breakout",
  "category_label": "刚突破",
  "score_scale": {"min": 0, "max": 3},
  "items": [
    {
      "code": "000001.SZ",
      "score": 2.41,
      "distance": 0.82,
      "confidence": "limited",
      "caps": [],
      "largest_distance_contributors": []
    }
  ]
}
```

建议新增 V2 路由，不复用旧路由含义：

- `GET /api/shape-v2/rankings?category=<v2-key>&limit=20|50&as_of=YYYYMMDD`
- `GET /api/shape-v2/{code}?as_of=YYYYMMDD`

研究期接口还应返回 `status=research_only` 和 `formal_scoring_enabled=false`。正式接入前必须去掉证券身份匿名层，但不能引入评分日之后的数据。

## V1 兼容层

现有依赖面包括：

- 后端：`server/patterns.py`、`server/config.py`、`server/http.py` 和服务层的旧类别校验。
- 类型：`app/lib/types.ts` 的 `PatternKey`，以及筛选、形态池、历史记录和行业强弱响应。
- 前端：`BoardClient.tsx` 的三张旧卡片、形态标签和历史复用。
- 行业强弱：`/api/industry-strength?pattern=...` 只接受旧三类。
- 测试与文档：后端单测、渲染测试、E2E、性能证据和 V1.2 API 文档均引用 `range_bounce`。

接入时不要直接把 `PatternKey` 改成 V2 联合类型。应新增 `ShapeV2CategoryKey`，再在明确的版本边界内转换。

## 行业强弱影响

行业强弱当前按 V1 形态池聚合。V2 稳定前继续使用 V1，不读取临时 V2 分数。

未来接入需要同时确定：

- 按 V2 三类分别聚合，不能把 `fresh_breakout` 简单映射成旧 `breakout`。
- 接口参数与缓存键加入 `shape_model_version`。
- 历史快照保留当时的类别键和模型版本。
- 旧 `range_bounce` 历史继续展示为旧口径，不迁移成 `pullback_strengthening`。

## 正式接入门槛

- dedicated template 已标注并冻结。
- tuning 对比达到事先约定的排名指标门槛。
- final evaluation 一次性通过，且未用于继续调参。
- 后端契约测试、TypeScript 类型检查、V1/V2 双读测试、历史兼容测试和文档全部通过。
- 再开始正式前端改造。
