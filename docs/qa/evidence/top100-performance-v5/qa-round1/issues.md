# Top100 / 真实 K 线 / 纯行情页独立 QA 首轮

- 结果：ISSUES FOUND
- 模式：独立只审查，不修改产品、测试或数据
- 实际分支：`codex/top100-performance-ux-v5`
- 审查时 HEAD：`9c1109c`
- 前端：`http://localhost:3106`
- 后端：`http://127.0.0.1:8882/api`
- 尺寸：1900×956、1440×900、1024×768、390×844

## 问题单

### QA-R1-001 · P1 · 移动端模板抽屉自动遮挡主行情

路径：`/market?code=301234&template=fresh_breakout&from=breadth&industry=801080&window=20`

在 390×844 下，模板上下文加载后抽屉自动打开，背景遮罩可见，主股票和主 K 线被覆盖。Escape 可以关闭，但首次进入不应要求用户先关闭面板。与“当前股票先出、模板上下文延后且不阻塞主内容”的目标冲突。

证据：`market-390x844-viewport.png`、`browser-results.json` 的 `interactions.mobile`。

期望：模板列表在后台渐进就绪；移动端仅在用户点击“打开右侧面板”后打开抽屉。

### QA-R1-002 · P2 · 模板库候选标题未明确 Top100

`/templates` 实际有 100 条候选链接，但候选区标题显示“Top 股票”，正文没有 Top100 字样。固定取前 100 的口径不够明确。

证据：`templates-1900x956-viewport.png`、`templates-390x844.png`、`browser-results.json` 的 `interactions.templates.candidateLinkCount=100`。

期望：标题显示“Top100 股票”或“Top100 · 100只”。

## 已验证通过

- 四尺寸、四页面均为 HTTP 200；未捕获 console error、pageerror 或 ≥400 响应。
- 行业宽度合计 100；默认 10 日；20 日比较日期为 2026-07-01；10/20 切换时 Treemap 几何不变。
- 红色扩张、绿色收缩、中性其他行业均有文字/箭头辅助，不依赖颜色单通道；图块文字居中。
- “其他行业”20只、13个行业；点击后才加载明细，并显示具体行业、当前股票、进入/保留/退出、行业 Top100 数量时间序列。
- 模板库真实模板 K 线可见；100 条候选整行进入行情并保留 template；候选缩略图按可见行加载。
- `/templates/new` 选择 000001 后显示 3292 个真实前复权交易日的完整总览与焦点 K 线；滚轮缩放、焦点背景平移、总览平移、双边界和整段移动均可操作。
- 新建模板的 slider 可聚焦；移动端双边界实际命中宽 43.75px；缩至 19 日后保存按钮禁用。
- 行情页 Top100 为 100 条；主 K 线、模板与候选真实 K 线可见；键盘切股有效且保留 from/industry/window；紧凑/展开有效；无保存模板入口；返回链接保留 template/industry/window。

## 本地浏览器体感

这些是本地服务已启动、后端已预热、浏览器新上下文下的实测，不冒充冷启动：

- Treemap 可操作：265ms
- 行情页 DOM 壳：73ms
- 当前股票可见：330ms
- 主 K 线可见：332ms
- 模板 Top100 可见：443ms
- 行情页本次完全稳定：1740ms
- 新建模板选择股票并完成交互检查：2612ms（含完整历史读取）

## QA 脚本假判定

- `otherComponentCount=0` 是 locator 写成 `li`，实际构成使用卡片；截图确认 13 个具体行业，不是产品问题。
- `invalidRangeShowsInlineHint=false` 是 QA 正则未匹配实际“还差…最少需要 20 日”；role=alert 与保存禁用已确认，不是产品问题。

## 工作区外残留

首轮脚本最初没有解码中文 file URL，误写到：

`C:\Users\hp\.codex\worktrees\b7b3\%E6%89%8B%E5%8A%A8%E8%B7%9F%E8%B8%AA%E5%B8%82%E5%9C%BA`

该目录共 17 个文件、3,151,225 bytes，为 16 张截图和 1 份浏览器结果。依据数据保护规则，QA 未删除、未移动。后续全部证据已写入正确工作区。
