# 手动跟踪市场 v1.2

一个仅在本机运行的 A 股手工选股与行情查看系统。行情、估值、ST、复权和行业数据只读取：

`C:\Users\hp\Documents\zer0share`

系统没有外部行情源，也不会在线补数或自动回退。人工状态与筛选历史保存在项目本地 SQLite。

## 页面

- `http://localhost:3000/`：综合选股看板，支持行业、市值区间、Top K、ST 等组合筛选与主动快照。
- `http://localhost:3000/market`：本地行情终端，支持完整历史、多图、全屏、连续切股和绘图。

两页复用同一应用侧边栏骨架，并共享股票代码、形态事实和跳转入口。

## 行业大额主动资金雷达

可审计的 5 日/20 日行业资金 PDF、排名数据、状态迁移和集中度报告由
`server/generate_industry_radar.py` 生成。运行方法、输入字段、样本过滤和
指标口径见 [`docs/industry-fund-radar.md`](docs/industry-fund-radar.md)。

## v1.2 要点

- 普通筛选不写历史；用户保存后记录整次条件、完整名单、排名和匹配度，可查看并恢复。
- 行业多选、市值上下限、任意正整数 Top K、ST 和板块条件可组合生效，Top K 默认 50。
- 周期按钮只控制默认可视窗口；完整本地历史一次载入，向左移动或缩放无需重选范围。
- 详情页使用既有三类形态股票池，可鼠标或上下键连续切股并保持周期、布局和面板上下文。
- 支持 1/2/4 图、单图放大、全屏及 resize；补齐斐波那契、趋势线、线段、射线、水平/垂直线、曲线和自由绘制，并支持选择、调整、删除。
- 1600、1366、1024 三档布局已做真实浏览器截图验收；两页侧栏几何一致，底部状态区不遮挡表格。

## 一键启动

在项目目录中运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_app.ps1
```

脚本会启动本地数据服务和页面。停止时运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop_app.ps1
```

## 分开启动

本地数据服务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_backend.ps1 --port 8765
```

页面：

```powershell
pnpm install
pnpm dev
```

## 本地数据口径

- 股票基础资料：`stock_basic`
- 日线、成交量：`daily`
- 市值、换手率：`daily_basic`
- 复权：`adj_factor`
- ST：`stock_st`
- 行业：申万 `index_member_all`
- 状态、自选与历史：`server/market_state.sqlite3`
- 形态阈值：`config/thresholds.json`

每张表按自己的最新本地分区日期读取。行情、估值、复权和 ST 日期不一致时，页面会分别显示日期并给出警告；不会把空 ST 分区误当成“没有 ST”，也不会静默丢掉最新 K 线。“较前一筛选日”仅在本地存在真实可比历史时显示，否则显示“暂无对比”。

## 已实现与明确禁用

已实现：股票搜索、连续换股、五种 K 线周期、完整前复权历史、前端/后端缓存、自选持久化、形态股票池、主动筛选快照、1/2/4 图、全屏和完整绘图工具。

明确禁用：分时和分钟线、指标库、股票对比、预警、回放、布局持久化、因子分析和交易。它们不伪装成可用功能。

## 验证

```powershell
pnpm lint
pnpm typecheck
pnpm test
uv run --project C:/Users/hp/Documents/zer0share python -m unittest server.tests.test_backend
pnpm test:e2e
```

端到端测试使用本机 Google Chrome。运行前先执行 `scripts/start_app.ps1`。

## 验收证据

- 最终报告：`docs/qa/v1.2-acceptance.md`
- 浏览器结果：`docs/qa/evidence/v1.2/browser-results.json`
- 截图：`docs/qa/screenshots/v1.2/`
