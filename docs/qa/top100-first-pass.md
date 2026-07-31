# Top100 / 真实 K 线工作流首轮独立 QA

## 结论

- 审查分支：`codex/top100-kline-workflow-v4`
- 首轮审查时起点提交：`5ebed30fe6ae6d6ad32e196ad28933a0e38aff81`
- QA 身份：独立审查，仅新增本报告、运行脚本、日志和截图；未修改应用、测试或数据代码。
- 结论：无 P0；4 个 P1、2 个 P2。需开发修复后再独立复验。

## 真实服务与测试结果

为避免串到其他工作树，首轮使用隔离服务：

- 页面：`http://localhost:3102`
- 当前工作树后端：`http://127.0.0.1:8877/api`
- 说明：3000 被另一工作树占用；8765 是旧服务且 `/api/templates` 返回 404；8766 被其他静态文件服务占用。

HTTP 结果：

- `/templates`：200
- `/templates/new`：200
- `/template-breadth-v3`：200
- `/market?code=301234&template=fresh_breakout`：200
- `/api/health`：200
- `/api/templates`：200
- `/api/templates/fresh_breakout`：200
- `/api/templates/fresh_breakout/stocks?limit=3`：200
- `/api/bars/301234?period=1d&limit=80`：200

浏览器结果：

- 首轮所测页面 console errors：0
- page errors：0
- request failures：0
- 外部网络请求：0
- 定向 E2E：`tests/e2e/templates.spec.ts`，3/3 通过。

## 首轮问题单

### P1-01 Treemap 不是可用的 squarified 结果

现象：

- 1440、1024、390 三档下，大量中小行业被排成横向薄条。
- 小行业文字被裁掉，块高和点击区降到几像素。
- 视觉结果接近 slice-and-dice，不符合“块尽量接近正方形”的产品要求。
- 当前面积仍正确承载 Top100 数量，且入选率、分母、日期、单位均有文字说明；问题集中在布局算法与可用性。

证据：

- `desktop-1440-breadth.png`
- `narrow-1024-breadth.png`
- `mobile-390-breadth.png`

关闭标准：

- 修正布局方向/算法，常见中小块不再形成成排 1–5px 薄条。
- 仍严格按 `top100_count` 决定面积。
- 390 下最小可交互块有可靠点击目标；无法放入块内的标签有替代读取方式。

### P1-02 390 下宽度页与新建模板页被固定侧栏遮挡

现象：

- `/template-breadth-v3` 与 `/templates/new` 在 390 宽仍保留约 78px 固定左侧栏。
- 标题、摘要卡、搜索框、图表与说明左侧被覆盖/裁切。
- 模板库页面已经切到底部导航，说明三页响应式行为不一致。
- 30 秒测试中的“最宽行业”“新进/退出最大行业”“如何新建模板”在手机档无法可靠扫读完成。

证据：

- `mobile-390-breadth.png`
- `mobile-390-new-template.png`
- 对照：`mobile-390-templates.png`

关闭标准：

- 两页在 390 使用与模板库一致的移动导航策略，正文不被覆盖。
- 标题、搜索、图表、边界操作和保存区完整可见、可点。

### P1-03 候选股票迷你 K 线过窄，仍有大量横向空白

现象：

- 1440 下候选行的 K 线缩略图视觉宽度约 18px。
- 日期与相似度之间仍保留大段空白，缩略图无法用于判断起涨/加速/末端形态。
- 390 下候选行被拉高，缩略图仍窄，信息密度没有改善。

证据：

- `desktop-1440-templates.png`
- `mobile-390-templates.png`

关闭标准：

- 重新分配行内列宽，让缩略图获得可辨识的固定宽度。
- 名称、代码、行业、相似度、窗口日期仍保留，整行点击仍进入行情页。

### P1-04 行情页模板/候选对照仍是抽象折线

现象：

- 行情主图使用真实本地 K 线。
- 右下“模板与当前窗口”仍以两条归一化折线表达，不是真实模板 K 线与候选窗口 K 线。
- 这不足以让用户直接核对蜡烛的实体、影线和窗口起止位置。

证据：

- `desktop-1440-market-compact.png`

关闭标准：

- 右侧对照改为真实本地前复权 K 线，清楚标出模板/候选起止窗口。
- 不改变四模板、独立 z、单窗口 Pearson 或评分器。

### P2-01 新建模板默认 60 日选区在完整历史中太窄

现象：

- 平安银行完整历史从 2013-01-04 到 2026-07-29。
- 默认 60 交易日选区压在最右侧约 40px，两个边界靠得很近。
- 虽然边界拖拽和整体平移能工作，但第一眼难理解、难精确命中。

证据：

- `desktop-1440-new-template-selected.png`

关闭标准：

- 保留“完整 K 线 + 两边界单窗口”，但让当前选区和双边界更易辨识与命中。

### P2-02 Brush 仅支持 pointer，边界点击区偏小

现象：

- 两个 SVG handle 均可拖动，并能触发 `<20` 与 `>240` 的图上/表单就地提示。
- handle 约 18px，且不是可聚焦控件，没有键盘调整方式。
- 对平板/手机触控和键盘用户不够可靠。

证据：

- `desktop-1440-new-template-invalid-over240.png`
- `desktop-1440-new-template-invalid-under20.png`
- `interaction-details.json`

关闭标准：

- 增大触控命中区；边界具备可见 focus 和键盘微调能力，或提供等价的可访问调整控件。

## 已通过的关键路径

- 模板库顶部已无手输起止日期表单；“新建模板”进入 `/templates/new`。
- 冻结模板展示真实前复权 K 线和明确起止日期。
- 新建模板可搜索真实股票、读取完整真实日线、拖动左右边界和整体选区。
- `<20`、`>240` 可触发就地无效提示，保存按钮随有效性禁用。
- 行情页未发现“保存区间/保存当前区间为模板”入口。
- 点击模板候选整行后 URL 保留 `template=fresh_breakout`，右侧模板股票列表保留。
- 行情页“收起顶部/展开顶部”两档有效，紧凑后 K 线高度明显增加。
- 行业点击后出现当前 Top100 股票、5 日进出明细和行业数量时间序列；股票链接保留模板上下文。
- 当前模板、最宽行业、5 日新进最多、5 日退出最多在 1440/1024 首屏可直接回答。
- Top100 日期、单位“只/%”、行业入选率分母和“相对 5 个交易日前”均有明确文本。
- 最近变化同时使用数字、文字、条段表达，不只依赖颜色。

## 证据索引

- 浏览器原始结果：`docs/qa/evidence/top100-first-pass/browser-results.json`
- 交互与 HTTP：`docs/qa/evidence/top100-first-pass/interaction-details.json`
- 首轮运行脚本：
  - `docs/qa/evidence/top100-first-pass/run-first-pass.mjs`
  - `docs/qa/evidence/top100-first-pass/interaction-details.mjs`
- 三尺寸截图与交互截图：`docs/qa/evidence/top100-first-pass/*.png`

## 待复验

开发修复后，独立 QA 将逐项关闭 P1/P2，并补齐：

- 1440、1024、390 修复后同路径截图。
- 行情页三尺寸紧凑/展开。
- hover/focus、返回路径、键盘切股、死按钮和点击区复验。
- 修复后 HTTP、console/page errors、定向 E2E 与问题关闭表。
