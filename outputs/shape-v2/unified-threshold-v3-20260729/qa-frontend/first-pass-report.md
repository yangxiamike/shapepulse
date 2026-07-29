# 统一固定线应用页 V3 · 前端独立 QA 首轮

## 结论

状态：**需要修正后复验**。

- 实际分支：`codex/unified-threshold-app-v3`
- 实际提交：`7f57b3f`
- 页面：`/templates`、`/market?code=603986&template=fresh_breakout`、`/template-breadth-v3`
- 尺寸：1440×1000、1024×800、390×844
- 本地后端：`http://127.0.0.1:8876`
- 本地前端：`http://localhost:3100`
- QA 状态库：`qa-frontend/qa-market-state.sqlite3`
- 数据源：本机 zer0share；health 明确返回 `network: not used`

## 问题清单

### P1 · Market 双曲线数值尺度不一致

模板曲线是“首日归一到 100”，fresh_breakout 实际范围约 92.98–129.11；候选曲线却是窗口内 log-close z 值。两条线共用同一纵轴后，候选线被压在图底部，比较图在视觉上失真。

修复要求：

- 两条曲线使用同一种转换。建议都用窗口内独立 z，或都首日归一到 100。
- Pearson 评分器保持冻结不变。
- 增加自动测试，确认比较图两条输入口径一致。

证据：`market-template-interaction-1440.png`。

### P1 · 390px Market 模板面板无法正常操作

点击“打开右侧面板”后，模板 tab 和模板股票按钮仍位于可视区外。Playwright 普通点击持续返回 `outside of viewport`；截图中也没有出现可操作的右侧模板面板。

修复要求：

- 修正移动断点下 `.market-rightbar.open` 的位置、transform、display 和层叠关系。
- 390px 下必须能完成：打开面板 → 点击模板 tab → 点击首只股票 → 关闭面板。
- E2E 禁止使用 `force` 或 DOM click 绕过真实可点击性。

证据：`market-mobile-panel-open-390.png`、`additional-run-2-error.log`。

### P2 · template 参数没有自动打开 Market 模板页签

模板库 Top 股票链接正确生成 `/market?code=...&template=fresh_breakout`，但进入 Market 后仍默认展示“自选”，而不是对应的模板列表。URL 状态保留了，视觉上下文却中断，用户还要再次点击“模板”。

修复要求：

- URL 含合法 `template` 参数时，初始 rightTab 直接设为“模板”。
- 立即显示对应模板列表、候选比较或明确的“未入榜”说明。
- 无 template 参数时才沿用自选默认页。

证据：`market-1440.png`、`market-1024.png`、`market-390.png`。

### P2 · 最近变化视图遗漏“收缩到 0”的行业

Treemap 无论哪个视图都过滤 `above_count=0`。因此当前宽度为 0、但近 5 日确实退出的行业，在“最近变化”中仍不显示。

已确认遗漏示例：

- 刚突破：交通运输 -1、基础化工 -1。
- 健康上涨：计算机 -1、通信 -1。
- 回调转强：有色金属 -2、建筑材料 -2、环保 -1。

修复要求：

- 当前宽度继续按 `above_count` 编码。
- 最近变化改为按 `abs(change_5d)` 或正负变化分区编码。
- 必须纳入 `above_count=0 && change_5d!=0` 的行业。

### P2 · 缺少最大行业变化的快速摘要

首屏能快速读出当前模板数量及 1/5 日变化，但不能在 30 秒内直接回答“哪个行业扩张最多、哪个收缩最多”，仍需逐块扫描。

修复要求：

- 行业标题区增加“5日最大扩张”和“5日最大收缩”两个摘要。
- 摘要必须覆盖收缩到 0 的行业。

### P2 · 390px Market 点击目标偏小且部分控件被裁到视口外

几何检查记录 43 个低于 40px 的目标：

- 周期按钮通常约 39×32。
- 绘图按钮通常约 34×34。
- 颜色输入约 23×20。
- 月K、季K、年K、线宽及长期范围控件边界超出 390px 可视区。

修复要求：

- 移动主要触控区至少 44×44。
- 周期、线宽、范围条使用明确的横向滚动容器及视觉提示，或分组折叠。

### P2 · 390px 宽度页模板 tabs 裁切且缺少横滑提示

首屏只完整显示“刚突破”和“健康上涨”，第三个模板只露出边缘，第四个完全不可见。容器虽然可以横滑，但没有箭头、分页点或文字提示。

修复要求：

- 390px 下改为 2×2 完整展示；或
- 保留横滑时加入渐隐、箭头或“左右滑动查看四模板”提示。
- 键盘聚焦模板时必须自动滚入可视区。

证据：`template-breadth-v3-390.png`。

### P2 · 390px 模板库固定底栏遮挡正文

固定底栏在滚动截图中横跨冻结模板列表，遮住分组标题和首行阅读区域。页面尾部虽有留白，但滚动过程中仍持续覆盖约 64px 内容。

修复要求：

- 为正文滚动容器增加与底栏等高的安全区。
- 增加 `scroll-padding-bottom` / 条目 `scroll-margin-bottom`，确保聚焦或点击后的目标不会停在底栏后面。

证据：`templates-390.png`。

### P2 · 侧栏帮助与退出是可见死按钮

桌面页显示帮助和退出按钮，但没有动作、链接或禁用说明。

修复要求：

- 暂不实现时隐藏，或明确 disabled 并提示“暂未开放”。
- 保持可点击外观时必须实现动作。

## 已通过

- 三页面九组主文档 HTTP 均为 200。
- 0 console error、0 page error、0 失败响应。
- 页面根节点无横向溢出。
- `/templates` 冻结四模板齐全。
- 自定义模板创建、改名、删除全部成功；临时 SQLite 无残留。
- 模板 Top 股票链接保留 `template=fresh_breakout`。
- Market 模板选择器仅有冻结四模板。
- `603986` 当前未进入 fresh_breakout Top100 时，页面明确说明，不伪造分数。
- 点击榜首后，候选/模板比较区域、图例、窗口及相似度均出现。
- 键盘向下切股成功，股票代码改变且 template 参数保持。
- Market 返回模板库链接保留模板参数。
- 宽度页四模板摘要均与 JSON 一致。
- 0.80 明确标为试用线和“未验证为四模板统一基准”。
- 当前数量、1日/5日变化、5日均线、历史百分比的单位与数值均正确。
- 行业块点击、行业 60 日序列、返回全部行业均可用。
- 当前宽度/最近变化切换有颜色、箭头、文字和数量等多重编码。
- 模板库焦点环可见，Top 股票 hover 有视觉反馈。
- 1440、1024 的模板库和宽度页字体层级、对比度及主内容布局清晰。

## 30 秒扫读评价

- `/templates`：能快速看懂四个冻结模板、自定义入口、当前模板窗口和 Top 股票，桌面通过；390px 受底栏遮挡影响。
- `/market`：能快速看懂当前股票、价格、涨跌和图表；但带 template 参数仍先显示自选，模板任务上下文不够直接。
- `/template-breadth-v3`：能快速回答当前模板、0.80 试用性质、当前数量、较昨日/5日前及历史位置；不能直接回答“最大扩张/最大收缩行业”，因此该项未通过。

## 证据文件

- `browser-evidence.json`
- `issues-first-pass.json`
- `templates-1440.png`、`templates-1024.png`、`templates-390.png`
- `market-1440.png`、`market-1024.png`、`market-390.png`
- `template-breadth-v3-1440.png`、`template-breadth-v3-1024.png`、`template-breadth-v3-390.png`
- `templates-after-crud-1440.png`
- `market-template-interaction-1440.png`
- `breadth-industry-interaction-1440.png`
- `breadth-healthy_uptrend-change-1440.png`
- `breadth-pullback_strengthening-change-1440.png`
- `market-mobile-panel-open-390.png`

说明：`qa-run-2`、`qa-run-3` 的中途失败分别来自 QA 选择器层级及最初错误假设 603986 应进入最新 Top100，不计为产品问题；最终基础证据来自成功完成的 `qa-run-4`。
