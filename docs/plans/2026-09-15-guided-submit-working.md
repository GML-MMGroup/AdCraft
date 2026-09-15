# Guided 方案提交阶段的 Working 衔接

## 根因与需求

方案提交使用 actingInteractionId，而 agentWorking 只包含普通消息 sending、流程推进、
post-ready barrier 和 pending Turn。移除 Submitted / Generating nodes… 后，提交卡收起，
后续 Turn 尚未返回时没有任何通用 Working 提示。本次复用现有转圈 + Working 补齐该窗口。

## 方案

- 将现有 actingInteractionId 纳入 agentWorking 判定，不新增一套并行生命周期或计时器。
- 点击提交时，提交锁与卡片收起同时生效；即使 HTTP 请求尚未返回也显示 Working。
- 接受后仍沿用锁：旧 open 快照及 submitted 状态不会过早清除反馈。
- 后端关闭当前交互或替换为下一交互时清除锁；后续已追踪 Turn/流程推进仍按原规则显示。
  若进入新的用户选择或无后续工作，则回到等待用户，不伪造持续运行。
- 保留现有错误恢复与 Workflow 切换清理，验证不会因失败或旧异步响应永久转圈。
- 不恢复 Submitted 框，不修改角色动图终态规则、API 合同、生成逻辑或请求频率。
- 保持现有 Working 样式与 Timeline 自动跟随逻辑；不引入新增动画资源。

## 计划

- [x] 从 main `d59d7a86` 创建独立分支/worktree `fix/guided-submit-working-20260915`。
- [x] 扩展 hook 回归：请求暂挂、接受后旧 open/submitted、交互关闭/替换、失败、Workflow 切换。
- [x] 回归先捕获 agentWorking=false，再接入既有提交锁；无须新增退出状态。
- [x] 验证面板显示标准 Working，原 Submitted 框/空 overlay 仍不存在。
- [x] typecheck、聊天单测、定向 lint、浏览器提交衔接验证；拦截所有真实写请求。

交付方式：验证通过后提交并 fast-forward 合入本地 main，不推送远端。

## 验证记录

- 修复前定向回归：5 条测试在 `agentWorking` 预期 true、实际 false 处失败。
- `npm test -- src/features/agent-canvas/chat/`：60 个文件、574 条测试全部通过。
- `npm run typecheck`：通过。
- `npx eslint src/features/agent-canvas/chat/useAgentCanvasChat.ts src/features/agent-canvas/chat/useAgentCanvasChat.test.tsx`：通过。
- `git diff --check`：通过。
- 浏览器在 worktree 的 5198 端口加载 `proj_acbc158635ca935d`，拦截 submit，
  先保持请求未返回，再模拟 202 并回放旧 Timeline，两个阶段 Working loader 都为 1，
  overlay 都为 0，并断言 Working 可见；真实后端写请求为 0。
- 单测确认交互关闭/替换、方案 materialization 失败、Product source 失败、请求失败以及
  Workflow 切换后迟到的失败响应能退出此次提交的 Working。
- 测试中的 materialization Turn 使用与终态事件一致的 completed/failed 响应，
  避免默认 queued mock 把独立 Turn 错当作仍有工作。

## 范围与边界

仅修复 guided submit 到后端释放交互锁之间遗漏的通用反馈，不更改角色动画生命周期。
Working 仍由真实已知状态派生：若后端仍保持当前 interaction 为 open/submitted，
继续等待权威刷新；不会用固定超时假装流程完成。若后端先关闭交互、但下一 Turn 尚无任何
证据，此改动不会虚构后续工作，也不承诺覆盖所有后端阶段之间的空窗。
后续已有活跃 Turn 时，仍由原 pending Turn 逻辑接续显示 Working。
