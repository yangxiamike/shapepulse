# 手动跟踪市场 v1.1

一个仅在本机运行的 A 股手工选股与行情查看系统。行情、估值、ST、复权和行业数据只读取：

`C:\Users\hp\Documents\zer0share`

系统没有外部行情源，也不会在线补数或自动回退。人工状态与筛选历史保存在项目本地 SQLite。

## 页面

- `http://localhost:3000/`：综合选股看板，含综合榜和三个独立 Top 50。
- `http://localhost:3000/market`：独立本地行情终端，支持日/周/月/季/年 K 与当前股票形态事实。

两页只共享股票代码、形态事实和跳转入口。选股流程不会混入行情终端。

## v1.1 要点

- 突破启动、上升趋势回调、区间下沿反弹独立计算和排序，每类最多显示 50 只。
- 看板可查看完整结果、真实涨跌幅、形态理由、关键指标、K 线/成交量和人工状态历史。
- 默认行情为最近 110 个交易日日 K；周/月/季/年使用各自自然周期 OHLCV 聚合。
- 趋势线、水平线、文本、测量、清除、缩放、拖动和十字光标可用。
- 未实现的分时/分钟、指标、对比、预警、回放、多图布局、因子和交易明确禁用并说明。
- 1600、1280、1024 三档布局已验收；1024 右栏通过抽屉访问。

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

已实现：股票搜索、换股、范围选择、五种 K 线周期、前复权日线、前端/后端缓存、自选持久化、详情、形态事实与历史、基础画线工具。

明确禁用：分时和分钟线、指标库、股票对比、预警、回放、多图布局、布局保存、因子分析和交易。它们不伪装成可用功能。

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

- 最终报告：`docs/qa/v1.1-acceptance.md`
- 浏览器结果：`docs/qa/evidence/v1.1/browser-results.json`
- 性能原始数据：`docs/qa/evidence/v1.1/performance.json`
- 截图：`docs/qa/screenshots/v1.1/`
