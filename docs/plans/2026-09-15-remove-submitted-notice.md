# 移除方案提交后的临时提示框

## 定位与需求

`AgentCanvasChatPanel.renderStandaloneGuidedInteractionCard` 在本地乐观收起交互卡时，
会显示 `Submitted / Generating nodes…` 占位卡，外层 overlay 也保留。本次移除此提示框。

## 方案

- 提交后沿用已有 optimisticallyDismissedInteractionId 状态，但不再渲染提示卡或空 overlay。
- 删除仅服务于该提示卡的 CSS；不更改 API、提交参数、节点创建、角色动画或 Timeline 刷新。
- 保留失败恢复：请求返回 false 或抛错时恢复原卡；匹配的 materialization failure 事件恢复交互。
- 保留新交互到达时展开新卡，以及已提交/处理中选择的现有禁用保护。
- 不增加替代 toast、提示文字、监听器或轮询。

## 计划

- [x] 先提交并合入已验证的角色终态修复（`f9c403e9`）。
- [x] 从最新 main 创建 `fix/remove-submitted-notice-20260915` 独立 worktree。
- [x] 添加面板集成回归：提交中与提交成功不出现提示框/空壳；失败恢复、下一交互正常显示。
- [x] 移除占位 JSX、外层占位条件和专用 CSS。
- [x] 验证 typecheck、聊天单测、定向 ESLint 与浏览器交互。
- 交付方式：按本轮授权提交并 fast-forward 合并到本地 main，不推送远端。

## 验证记录

- 原实现下新增测试捕获 Submitted 占位及 overlay 仍存在的行为；修复后通过。
- 同步 AgentConversationShell 中 3 项旧展示断言，保留请求失败及生成失败恢复断言。
- `npm test -- src/features/agent-canvas/chat/`：60 文件、571 项测试通过。
- `npm run typecheck`、改动 TSX 定向 ESLint 和 git diff 空白检查通过。
- 浏览器打开临时 worktree 5198 的真实项目页面，选中方案并提交；浏览器路由拦截所有
  非 GET/HEAD API 请求，暂挂提交后确认提示框/overlay 均不存在，随后模拟网络失败确认选择卡恢复。
  拦截写请求 1 次、转发到后端的写请求 0 次，未改变真实项目状态。
- 截图：`/tmp/adcraft-submitted-notice-removed.png`。临时服务验证后关闭，5189 保持原服务。
- 遵循 vercel-react-best-practices，仅减少展示 DOM 和专用 CSS，不引入额外请求或状态。
