# Top100 / 真实 K 线工作流修复后独立 QA

## 结论

- 实际分支：`codex/top100-kline-workflow-v4`
- 复验时 HEAD：`5ebed30fe6ae6d6ad32e196ad28933a0e38aff81`
- 复验身份：独立 QA；本轮只新增 `docs/qa` 下证据与本报告，未修改应用、测试或数据代码。
- 首轮 4 个 P1 与 2 个 P2 均已关闭。
- 无 P0、无新的 P1。

## 隔离环境

为避免旧进程和其他工作树干扰，本轮重新启动冻结代码实例：

- 页面：`http://localhost:3103`
- API：`http://127.0.0.1:8878/api`

关键 HTTP 均为 200：

- `/templates`
- `/templates/new`
- `/template-breadth-v3`
- `/market?code=301234&template=fresh_breakout`
- `/api/health`
- `/api/templates`
- `/api/templates/fresh_breakout`
- `/api/templates/fresh_breakout/stocks?limit=3`
- `/api/bars/301234?period=1d&limit=80`

三尺寸共 12 条页面路径：

- console errors / warnings：0
- page errors：0
- request failures：0
- 外部网络请求：0
- 横向溢出：1440、1024、390 均为 0

## 首轮问题逐项关闭

### P1-01 Treemap 非真正 squarified：已关闭

修复后：

- 1440：26 块，最小边 47px，最大长宽比 2.45。
- 1024：26 块，最小边 37px，最大长宽比 2.55。
- 390：26 块，最小边 23.1px，最大长宽比 3.33。
- 不再出现成排 1–5px 横向薄条；空间结构已是可辨识的 squarified 布局。
- 面积继续由 `top100_count` 决定，最大块为医药生物 21 只。
- 每块都有完整无障碍名称，包含行业、Top100 数量、入选率和点击动作。
- hover 有饱和度变化；focus 有 3px 深色描边；选中有 4px 描边。

非颜色通道通过：

- 当前宽度由面积与数字共同表达。
- 最近变化由“新/留/退”文字、数量和条段共同表达。
- 页面明确写明颜色不表示涨跌。

证据：

- `desktop-1440-breadth.png`
- `narrow-1024-breadth.png`
- `mobile-390-breadth.png`
- `browser-results.json`

轻微观察：390 下最小行业块约 23px，低于常见 44px 触控建议，但已不影响主要行业读取；小块仍可通过完整无障碍名称读取。

### P1-02 390 固定侧栏覆盖正文：已关闭

修复后：

- `/template-breadth-v3` 与 `/templates/new` 均切换为底部导航。
- 390 下标题、摘要、搜索、完整 K 线、选区预览、保存区不再被左栏裁切。
- `scrollWidth === clientWidth === 390`。
- 模板库、宽度页、新建模板页的移动导航一致。

证据：

- `mobile-390-breadth.png`
- `mobile-390-breadth-selected.png`
- `mobile-390-new-template-selected.png`
- `mobile-390-templates.png`

### P1-03 候选迷你 K 线不可辨识：已关闭

修复后首行缩略图尺寸：

- 1440：约 373 × 56px
- 1024：约 264 × 56px
- 390：约 308 × 46px

每行仍保留：

- 名称、代码、行业
- 相似度
- 候选窗口起止日期
- 真实本地前复权蜡烛图
- 整行行情入口与 `template` 上下文

证据：

- `desktop-1440-templates.png`
- `narrow-1024-templates.png`
- `mobile-390-templates.png`

### P1-04 行情页仍是抽象折线对照：已关闭

修复后：

- “模板与当前窗口”包含两张真实蜡烛图：
  - 模板真实 K 线
  - 候选真实 K 线
- 两图均显示起止日期。
- 页面明确提示用真实 K 线判断起涨、加速或末端，不使用未来表现验证。
- 未发现旧的归一化双折线图。

证据：

- `desktop-1440-market-expanded.png`
- `desktop-1440-market-compact.png`
- `mobile-390-market-expanded.png`
- 浏览器检查 `realPair = 2`

### P2-01 完整历史中默认选区太窄：已关闭

修复后：

- 完整历史 K 线仍保留，符合单窗口双边界工作流。
- 下方新增“选中窗口局部预览”，默认 60 日窗口可直接辨识真实蜡烛。
- 起止日期和交易日数同时显示。
- 1440、1024、390 均可读。

证据：

- `desktop-1440-new-template-selected.png`
- `narrow-1024-new-template-selected.png`
- `mobile-390-new-template-selected.png`

### P2-02 Brush 键盘与触控命中：已关闭

已关闭部分：

- 两个边界均为可聚焦 slider。
- `aria-valuemin`、`aria-valuemax`、`aria-valuenow` 完整。
- 方向键移动 1 个交易日，Shift + 方向键移动 5 个交易日。
- 键盘实测开始边界从 3233 移到 3232。
- focus 时 handle 变为深绿并带白色描边。
- 1440 实际 handle 宽约 32.7px；1024 约 23.7px。
- `<20` 与 `>240` 均出现就地提示并禁用保存：
  - 549 日时显示“超出 309 个交易日，最多允许 240 日”。
  - 少于 20 日时显示仍差的交易日数。

最终定点复验：

- 可见 SVG handle 在 390 下仍约 9.0px，但图表在捕获阶段按屏幕像素提供边界两侧各 22px 的吸附范围。
- 有效命中宽度为 44px，不随 SVG `viewBox` 缩放。
- 在开始边界左侧 18px 处按下并向左拖动 14px，边界从交易日索引 3233 移至 2904。
- 移动方向正确，并随即显示 389 个交易日及“超出 149 个交易日，最多允许 240 日”。
- 定点运行 HTTP 200，console、page errors、request failures 均为 0。

证据：

- `desktop-1440-new-template-over240.png`
- `desktop-1440-new-template-under20.png`
- `manual-observations.json`
- `browser-results.json`
- `final-touch-mobile-offset18.png`
- `final-touch-results.json`

说明：`browser-results.json` 的 `over240=false` 是 QA 采集正则把页面“超出”写成“超过”造成的假阴性；截图明确显示 549 日和正确超限提示，修正记录见 `manual-observations.json`。

## 30 秒任务复验

1440、1024 可在首屏直接回答；390 通过纵向扫读可回答：

1. 当前模板：刚突破。
2. Top100 最宽行业：医药生物，21 只。
3. 5 日新进入最多：医药生物，10 只。
4. 5 日退出最多：医药生物，35 只。
5. 点击行业后：
   - 当前 Top100 股票列表出现；
   - 新进入、保留、退出三个折叠组出现；
   - 行业数量时间序列出现；
   - 股票链接保留模板上下文。
6. 新建模板：模板库右上/移动端全宽“新建模板”进入 `/templates/new`。
7. 收起行情顶部：顶部明确按钮“收起顶部”；点击后按钮变“展开顶部”。

## 行情职责与交互

- 行情页“保存区间/保存当前区间为模板”入口数量：0。
- URL 保留 `template=fresh_breakout`。
- 右侧模板列表：200 只。
- “回到模板库查看完整列表”返回 `/templates?template=fresh_breakout`。
- 键盘向下切股通过：五洲医疗切到伟星股份，活动行和行情均更新。
- 1440 紧凑后图表高度：689px → 793px。
- 1024 紧凑后图表高度：589px → 693px。
- 390 紧凑后图表高度：690px → 790px。
- 1024/390 的响应式股票面板可通过明确“关闭”按钮返回主行情，再使用顶部紧凑按钮。
- 暂未实现功能均为显式 disabled 并带说明；所测主路径未发现死按钮。

## 日期、单位、分母与口径

以下均通过：

- 数据日期：2026-07-29。
- 单位：只 / %。
- 分母：本模板当日可选股票。
- 行业详情明确：当前 Top100 21 只、行业当日可选 502 只、入选率 4.2%。
- 最近变化明确为相对 5 个交易日前。
- 退出数量不计入当前面积。
- Top100 为每个模板独立 Pearson 排名，不跨模板综合。
- 无 0.80 主图分隔线或线上/偏低主语义。
- 无未来收益、IC 或策略表现验证。

## 自动化测试

执行：

`pnpm exec playwright test tests/e2e/templates.spec.ts tests/e2e/top100-remediation.spec.ts --reporter=list`

结果：4/4 通过。

- 模板库与行情上下文
- 真实 bars 与新建模板保存工作流
- 行情模板 URL 状态与股票列表
- Top100 squarified 桌面/移动可用性

## 证据索引

- 原始浏览器结果：`docs/qa/evidence/top100-fixed-pass/browser-results.json`
- 人工复核补充：`docs/qa/evidence/top100-fixed-pass/manual-observations.json`
- 最终触摸定点结果：`docs/qa/evidence/top100-fixed-pass/final-touch-results.json`
- 最终触摸截图：`docs/qa/evidence/top100-fixed-pass/final-touch-mobile-offset18.png`
- 三尺寸与交互截图：`docs/qa/evidence/top100-fixed-pass/*.png`
- 复验脚本：`docs/qa/evidence/top100-fixed-pass/run-fixed-pass.mjs`
- 最终触摸脚本：`docs/qa/evidence/top100-fixed-pass/final-touch-check.mjs`
- 服务日志与进程记录：`docs/qa/evidence/top100-fixed-pass/`

## 最终判定

本轮产品改版达到交付条件。首轮 P1-01～P1-04、P2-01～P2-02 均已关闭；最终定点复验无残留、无新回归。
