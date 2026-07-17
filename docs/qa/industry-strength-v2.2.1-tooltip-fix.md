# 行业强弱 V2.2.1 Tooltip 可见性小修复

## 结论

PASS。5 个问号注释在 1600×1000 与 1024×800 真实数据页面中均完整可见，未越出视口、未被卡片或图表遮挡，正文为 15px。

## 修复范围

- 弹层挂载到页面最外层，使用视口定位和独立高层级，避开卡片 `overflow` 与层叠上下文。
- 优先放在问号上方；空间不足时改放下方，并保留 12px 视口安全边距。
- 页面滚动、内部滚动和窗口缩放时重新定位。
- 支持鼠标悬停、点击开关、键盘焦点、Escape、失焦和点外关闭。
- 未修改 zer0share 数据源、股票池、形态算法、申万一级行业口径及 31 行业 × 24 节点 × Top 100 固定分母。

## 验证

| 检查 | 结果 |
| --- | --- |
| `pnpm typecheck` | PASS |
| `pnpm lint` | PASS |
| `pnpm build` | PASS |
| `python -m unittest server.tests.test_backend` | PASS，25/25 |
| `node --test tests/rendered-html.test.mjs` | PASS，4/4 |
| Tooltip 交互与代表回归 | PASS，1/1 |
| 真实数据视觉与联动回归 | PASS，3/3 |

## 精简证据

- [结构化浏览器结果](evidence/industry-strength-v2.2.1-tooltip-fix/browser-results.json)
- [1600×1000 Tooltip 截图](screenshots/industry-strength-v2.2.1-tooltip-fix/tooltip-heatmap-1600.png)
- [1024×800 Tooltip 截图](screenshots/industry-strength-v2.2.1-tooltip-fix/tooltip-heatmap-1024.png)
