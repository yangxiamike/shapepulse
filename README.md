# 手动跟踪市场

一个仅在本机运行的 A 股手工选股与行情查看系统。数据只读取：

`C:\Users\hp\Documents\zer0share`

系统不会自行访问或切换到外部行情源。

## 页面

- `http://localhost:3000/`：综合选股看板
- `http://localhost:3000/market`：独立本地行情终端

两页只共享股票代码和跳转入口。选股逻辑不会混入行情终端。

## 一键启动

在项目目录中运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_app.ps1
```

脚本会启动本地数据服务和页面，并打开浏览器。停止时运行：

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
- 状态与历史：`server/market_state.sqlite3`
- 形态阈值：`config/thresholds.json`

每张表按自己的最新分区日期读取。行情、估值、复权和 ST 日期不一致时，页面会明确显示口径日期；不会把空 ST 分区误当成“没有 ST”，也不会静默丢掉最新 K 线。

## 验证

```powershell
pnpm build
pnpm test
uv run --project C:/Users/hp/Documents/zer0share python -m unittest server.tests.test_backend
```
