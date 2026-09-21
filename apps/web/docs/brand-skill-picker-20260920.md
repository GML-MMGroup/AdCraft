# 品牌 Skill 选择前端接入（2026-09-20）

用户仅本次授权修改前端；后续任务仍默认仅修改后端并提供 handoff。
本次不修改 `apps/api`、canonical 后端业务代码、媒体执行策略或全局风格目录。

## 交互

- 品牌决策面板 Skill Stack 和聊天工具栏均提供选择入口；聊天“调整”打开选择器，
  不再提交为确认。其他品牌阶段不允许重新激活风格；创建模式保留原有选择行为。
- 创意方法多选（1–7 个），视听风格单选。目录 ID、版本和标题来自后端，推荐理由原样展示。
- 复用 `AgentCanvasStyleSelector` 的分页、分类和预览，增加不激活 Run 的草稿选择模式。
- 取消无写入；保存提交 `confirm=false`，使用返回的新卡和 revision；确认提交
  `confirm=true`，随后调用 `next-question` 并刷新会话与决策面板。
- 409 刷新权威面板，刷新失败时禁止继续提交旧卡；422 重新加载目录并保留可编辑选择。
  确认已成功但下一题失败时，只重试下一步，不重复确认。
- 中文会话使用中文新增操作提示；目录原始标题不由前端伪造翻译。
- 新卡生成后补刷新决策面板，避免仍使用空卡/旧卡导致入口禁用。
- 未版本化的历史选择不自动升级；后续阶段的历史组合保持只读。

## 验证

- 测试先红后绿：新增 API/版本理由保留/草稿不激活用例最初 4 failed；
  下一题后的面板刷新用例最初失败（预期 2 次刷新、实际 1 次）。
- 最后相关 6 文件复验：190 passed。
- TypeScript typecheck 和生产构建通过；全仓 lint 无错误，13 个原有警告。
- 完整 Vitest：1972 passed、16 failed（214 文件）。16 个失败在起点 `18959978`
  的独立工作树复现，失败名称集合一致（基线相关文件 66 passed、16 failed）。
  涉及编辑预览、首页路由、字体/样式、项目工具栏和画布边线旧断言；未修改或弱化它们。
  完整运行后补充的卡片刷新修正已做相关 190 项复验，未重跑未改动的完整范围。
- Playwright 浏览器 mock：桌面及 390px 手机宽度通过同一流程验收。
  覆盖取消、方法多选、已有视听目录分页及非推荐风格选择、保存不推进、
  新 revision 确认、恰好一次下一题、零提前激活。真实 API 请求全部拦截。
- 浏览器 fixture 独立 TypeScript 与 lint 检查通过。没有付费真实模型或真实 workflow 写入验收。

日志：`/tmp/adcraft-brand-picker-full-20260920.log`、
`/tmp/adcraft-brand-picker-baseline-20260920.log`、
`/tmp/adcraft-brand-picker-lint-20260920.log`。
截图：`/tmp/adcraft-brand-picker-desktop.png`、`/tmp/adcraft-brand-picker-mobile.png`。

复验命令（在 `apps/web`）：

```bash
npm test -- src/api/brandSkills.test.ts src/api/brandCompletion.test.ts src/features/agent-canvas/brand/BrandSkillPicker.test.tsx src/features/agent-canvas/chat/AgentCanvasStyleSelector.test.tsx src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx src/features/agent-canvas/chat/useAgentCanvasChat.test.tsx
npm run typecheck
npm run build
npx playwright test --config=playwright.config.ts tests/browser/brand-skill-picker.spec.ts
```
