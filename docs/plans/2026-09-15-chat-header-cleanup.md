# Agent 对话面板顶部精简

## 需求

保留 `AdCraft Video Agent` 标题，移除标题下方状态副标题（当前为 active）。
移除其下方的顶部生产提示框（当前为 `A product source is needed` /
`Add or choose a product source to continue`）。保留聊天、角色动效、Working 加载反馈、
Collaboration、文档/折叠按钮、下方产品来源选择交互卡及其提交流程。

## 定位与方案

- `AgentCanvasChatPanel.tsx` 的 `.agent-chat__identity > span` 是状态副标题。
  删除整个副标题，不针对 active 文本做替换，避免状态变化后再次占位。
- 顶部信息框由 `CurrentProductionStep` 渲染。移除面板中的该展示入口，
  不修改 guidanceAwaiting、GuidedInteraction 或后端合同。
- 移除仅用于上述两处展示的 currentTopic、activeContinuation、productionFocus 计算与 import。
  runtime prop 保持调用兼容，但不再在面板中解构使用。
- 不删除独立投影模块及其测试，不扩展为其他状态/错误提示的清理。
- 采用正常 DOM 布局自然收缩，不使用 visibility:hidden 留空；无需新增 CSS 高度、监听或状态。

## 实施计划

- [x] 从 main `94028e82` 创建 `fix/chat-header-cleanup-20260915` 分支及独立 worktree。
- [x] 增加回归测试：标题保留、副标题不渲染、顶部生产框不渲染、交互卡保留。
- [x] 删除两个展示入口及专用计算。
- [x] 运行聊天单测、typecheck 和定向 ESLint。
- [x] 临时预览验证：真实项目已推进且加载较慢，改用隔离的真实面板夹具确认顶部布局；
  产品来源选择卡由面板集成测试验证，不回退或更改真实项目。
- [x] 记录结果；不自动提交、合并 main 或推送远端，不改动 5189 服务。

## 验证记录

交付更新（2026-09-15）：用户随后明确要求合并到本地 main；将这次顶部精简、文档及测试
一并提交，以 fast-forward 合并到本地 main，不推送远端。

- 新增的 3 项回归测试在修改前全部失败，分别捕获 Ready/Working 副标题和产品来源顶部提示框。
- 修改后 `npm run typecheck` 通过；`npm test -- src/features/agent-canvas/chat/`
  共 60 个文件、554 项测试通过（包括角色生命周期及产品来源交互相关测试）。
- 两个改动 TSX 文件定向 ESLint 通过，git diff 空白检查通过。
- Playwright `agent-role-runtime-panel.spec.ts` 与 `agent-role-atomic-entry.spec.ts`
  共 10 项通过，确认角色动效、资源等待及终态行为未受影响。
- 隔离真实面板浏览器检查通过：标题、文档按钮、折叠按钮、Collaboration 保留，
  状态副标题与顶部提示框不存在；header bottom 与 timeline top 均为 92px，间距为 0，未留占位。
- 真实项目在检查期间已推进到 Product 节点 ready，且出现加载等待，因此未宣称在该项目
  当前状态验收产品来源选择卡；产品来源场景由集成测试明确覆盖。
- 遵循 vercel-react-best-practices：移除仅服务于已删展示的计算，不增加状态、监听或请求。
