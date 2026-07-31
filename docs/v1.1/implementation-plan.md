# 手动跟踪市场 v1.1 实施计划

状态：已完成

日期：2026-07-16

## 1. 版本管理

- 基线：`d699b25 Build local A-share screening and market terminal`
- 主工作区：`C:\Users\hp\Documents\手动跟踪市场`，保持 `main` 干净。
- v1.1 工作树：`C:\Users\hp\.codex\worktrees\15dd\手动跟踪市场`
- v1.1 分支：`codex/v1.1`
- 未推送远端。

已形成可审查提交：

1. `docs: establish v1.1 product and QA baseline`
2. `feat: complete v1.1 screening and market workflows`
3. `perf: cache local bars and add browser timing checks`
4. `style: finish responsive v1.1 layouts and visual hierarchy`
5. `docs: deliver v1.1 acceptance evidence`

## 2. 实施阶段

### 阶段 A：文档基线

- [x] 阅读 README、全部源码、测试与启动脚本。
- [x] 阅读两张批准概念图与概念图说明。
- [x] 核对 zer0share 技能、接口边界和本机路径。
- [x] 建立需求、实施计划、性能预算、验收标准和 QA 报告模板。
- [x] 审查并提交文档基线。

### 阶段 B：后端核心

- [x] 扩展 bars 周期：`1d/1w/1m/1q/1y`，校验 OHLCV 聚合。
- [x] 为默认 110 根日 K 与范围选择提供明确参数。
- [x] 输出各表日期、警告和分阶段计时。
- [x] 输出三类独立 Top 50、综合 Top 50，避免前端丢弃 categories。
- [x] 增加当前股票形态事实、未计算/无匹配状态与形态历史接口。
- [x] 计算真实前一可比筛选日的分类数量变化。
- [x] 完善状态接口，使保存、待判断、自选和历史条目可读、可增删。
- [x] 保持旧 SQLite 向后兼容。

### 阶段 C：前端核心

- [x] 重做 API 类型和映射，保留 categories、warnings、timings、dates。
- [x] 看板三类卡实现鼠标/键盘切换，完整展示各类 50 只。
- [x] 修复候选表、详情、预览图、形态指标、错误/空/进度状态。
- [x] 修复保存/待判断/历史抽屉为真实记录。
- [x] 行情页默认 110 日 K；独立缓存详情与周期 bars。
- [x] 周期、范围、绘图、文本、测量和清除工具可用。
- [x] 未实现功能统一禁用并用 tooltip/说明告知原因。
- [x] 新增“形态”标签和事实视图；详情视图去占位。
- [x] 移除默认自选注入；保证持久化与错误重试。
- [x] 合并重复行情导航入口。

### 阶段 D：性能与测试

- [x] 后端单元测试：聚合、分类独立、日期警告、历史对比、状态迁移。
- [x] 前端/渲染测试：结构、禁用态、信息架构、SSR 稳定。
- [x] 浏览器测试：键盘、鼠标、搜索、周期缓存、换股、自选、抽屉。
- [x] 用服务端 timing 与浏览器 Performance API 采集四组性能数据。
- [x] 首次全市场计算超过 1 秒时提供真实进度；优化至 3 秒内。

### 阶段 E：视觉与响应式

- [x] 1600×1000：看板右侧有效图表 ≥420×280，形态表与详情同屏可读。
- [x] 1280×900：看板上下布局，行情右栏仍可访问。
- [x] 1024×800：行情右栏抽屉可打开，图表无固定宽度裁切。
- [x] 正文 ≥14px、表格 ≥13px、图表坐标和工具栏 ≥12px。
- [x] 对照批准图检查暖白、近黑、薄荷绿、蓝、荧光黄与模块化边框。

### 阶段 F：独立验收与交付

- [x] 构建、前端测试、后端测试全部通过。
- [x] 启动真实本地后端和前端。
- [x] Chrome/Playwright 三档尺寸逐项点击。
- [x] 三类形态各抽样 5 只并保存截图。
- [x] 逐张用视觉理解检查标签、排名、理由、K 线、成交量、形态描述、字体、坐标。
- [x] 修复失败项并重复验证。
- [x] 完成 `docs/qa/v1.1-acceptance.md`、README、CHANGELOG。
- [x] 形成验收提交，停止并等待是否推送/发布的决定。

## 3. 最终验证命令

```powershell
pnpm lint
pnpm typecheck
pnpm test
uv run --project C:/Users/hp/Documents/zer0share python -m unittest server.tests.test_backend
pnpm test:e2e
```

## 4. 证据目录

- 浏览器截图：`docs/qa/screenshots/v1.1/`
- 性能原始数据：`docs/qa/evidence/v1.1/performance.json`
- 浏览器步骤/控制台摘要：`docs/qa/evidence/v1.1/browser-results.json`
- 最终报告：`docs/qa/v1.1-acceptance.md`
