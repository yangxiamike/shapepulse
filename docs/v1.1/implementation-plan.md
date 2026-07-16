# 手动跟踪市场 v1.1 实施计划

状态：执行中

日期：2026-07-16

## 1. 版本管理

- 基线：`d699b25 Build local A-share screening and market terminal`
- 主工作区：`C:\Users\hp\Documents\手动跟踪市场`，保持 `main` 干净。
- v1.1 工作树：`C:\Users\hp\.codex\worktrees\15dd\手动跟踪市场`
- v1.1 分支：`codex/v1.1`
- 不推送远端。

计划提交：

1. `docs: establish v1.1 product and QA baseline`
2. `feat: complete v1.1 screening and market workflows`
3. `perf: add request caching and timing telemetry`
4. `style: finish responsive v1.1 layouts and visual states`
5. `docs: deliver v1.1 acceptance evidence`

提交可按实际依赖拆成少量补充提交，但不能混入无关改动。

## 2. 实施阶段

### 阶段 A：文档基线

- [x] 阅读 README、全部源码、测试与启动脚本。
- [x] 阅读两张批准概念图与概念图说明。
- [x] 核对 zer0share 技能、接口边界和本机路径。
- [x] 建立需求、实施计划、性能预算、验收标准和 QA 报告模板。
- [ ] 审查并提交文档基线。

### 阶段 B：后端核心

- [ ] 扩展 bars 周期：`1d/1w/1m/1q/1y`，校验 OHLCV 聚合。
- [ ] 为默认 110 根日 K 与范围选择提供明确参数。
- [ ] 输出各表日期、警告和分阶段计时。
- [ ] 输出三类独立 Top 50、综合 Top 50，避免前端丢弃 categories。
- [ ] 增加当前股票形态事实、未计算/无匹配状态与形态历史接口。
- [ ] 计算真实前一可比筛选日的分类数量变化。
- [ ] 完善状态接口，使保存、待判断、自选和历史条目可读、可增删。
- [ ] 保持旧 SQLite 向后兼容。

### 阶段 C：前端核心

- [ ] 重做 API 类型和映射，保留 categories、warnings、timings、dates。
- [ ] 看板三类卡实现鼠标/键盘切换，完整展示各类 50 只。
- [ ] 修复候选表、详情、预览图、形态指标、错误/空/进度状态。
- [ ] 修复保存/待判断/历史抽屉为真实记录。
- [ ] 行情页默认 110 日 K；独立缓存详情与周期 bars。
- [ ] 周期、范围、绘图、文本、测量和清除工具可用。
- [ ] 未实现功能统一禁用并用 tooltip/说明告知原因。
- [ ] 新增“形态”标签和事实视图；详情视图去占位。
- [ ] 移除默认自选注入；保证持久化与错误重试。
- [ ] 合并重复行情导航入口。

### 阶段 D：性能与测试

- [ ] 后端单元测试：聚合、分类独立、日期警告、历史对比、状态迁移。
- [ ] 前端/渲染测试：结构、禁用态、信息架构、SSR 稳定。
- [ ] 浏览器测试：键盘、鼠标、搜索、周期缓存、换股、自选、抽屉。
- [ ] 用服务端 timing 与浏览器 Performance API 采集四组性能数据。
- [ ] 首次全市场计算超过 1 秒时提供真实进度；优化至 3 秒内。

### 阶段 E：视觉与响应式

- [ ] 1600×1000：看板右侧有效图表 ≥420×280，形态表与详情同屏可读。
- [ ] 1280×900：看板上下布局，行情右栏仍可访问。
- [ ] 1024×800：行情右栏抽屉/底部面板可打开，图表无固定宽度裁切。
- [ ] 正文 ≥14px、表格 ≥13px、图表坐标和工具栏 ≥12px。
- [ ] 对照批准图检查暖白、近黑、薄荷绿、蓝、荧光黄与模块化边框。

### 阶段 F：独立验收与交付

- [ ] 构建、前端测试、后端测试全部通过。
- [ ] 启动真实本地后端和前端。
- [ ] Chrome/Playwright 三档尺寸逐项点击。
- [ ] 三类形态各抽样至少 5 只并保存截图。
- [ ] 逐张用视觉理解检查标签、排名、理由、K 线、成交量、形态描述、字体、坐标。
- [ ] 修复失败项并重复验证。
- [ ] 完成 `docs/qa/v1.1-acceptance.md`、README、CHANGELOG。
- [ ] 形成验收提交，停止并等待是否推送/发布的决定。

## 3. 验证命令

```powershell
pnpm lint
pnpm build
pnpm test
uv run --project C:/Users/hp/Documents/zer0share python -m unittest server.tests.test_backend
```

端到端验收启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_app.ps1
```

## 4. 截图与结果目录

- 浏览器截图：`docs/qa/screenshots/v1.1/`
- 性能原始数据：`docs/qa/evidence/v1.1/performance.json`
- 浏览器步骤/控制台摘要：`docs/qa/evidence/v1.1/browser-results.json`
- 最终报告：`docs/qa/v1.1-acceptance.md`
