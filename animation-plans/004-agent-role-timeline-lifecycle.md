# Agent Role Timeline 动画生命周期方案

## 目标

让 Agent role 的文字身份与对应动图作为同一个 Timeline 单元进入界面。用户第一次看到
`World Setting`、`Scene Designer` 等 role 时，文字和动图必须同时出现；不能出现“文字先
出现，过一会儿才出现图标”的割裂状态。

动图资源尚未就绪时，不显示静态首帧，也不提前显示 role 文字，而是使用现有的“转圈 +
Working”占位状态。动图资源 ready 后，再把 role 文字与动图作为一个原子视觉单元挂载到
Timeline。

动画表达的是前端可见的“该 role 正在接力工作”区间，不再直接映射后端每一个 queued、
reserved、waiting、continuation 或 Turn hydration 中间状态。

## 用户可见契约

### 进入 Timeline

1. Timeline 投影发现某个 role 首次出现时，先创建该 role 的 loading identity 单元。
2. loading identity 只显示现有“转圈 + Working”占位，不显示 role 文字和静态首帧。
3. 动图模块加载完成后，在同一批次中挂载 role 名称和 animated artwork。
4. 文字与动图必须在同一次 React commit 中出现，不能先提交文字再异步补图标。

### 工作期间

- role 一旦进入 Timeline，就进入 loading/working 生命周期；资源 ready 后保持工作态动画。
- 不因后端的 `queued`、`reserved`、`waiting`、Turn 尚未 hydration 或 planning 文案变化
  而暂停动画。
- 后续同 role 的状态刷新只更新内容，不重置动画组件的挂载周期。

### 结束条件

动画只在 role 明确进入终态时停止：

- `completed` / 成功完成；
- `failed`；
- `cancelled`；
- `superseded`。

终态确认后，动画切回同款静态位图。不要再使用“下一个 role 开始”或“节点 prompt 已准备好”
作为停止条件；这些只能作为辅助展示信息，不能覆盖明确的 role 终态。

## 状态模型

在前端增加独立的 Timeline role lifecycle projection：

```text
absent
  └─ role 首次进入 Timeline
       ↓
    loading (转圈 + Working，占位，不显示 role 文字)
       ↓ 动图资源 ready
    active (role 文字 + 动画，同一批次进入)
       ↓ 明确终态
    settled (静态位图)
```

展示逻辑分成两层：role lifecycle 只消费出现与明确终态；资源门控只消费 ready。合计三个事实：

1. role identity 是否已经在当前 Timeline 中出现过；
2. 动图资源是否 ready；
3. 该 role 最近一次明确终态事件是否已到达。

它不把后端中间态直接转换成动画开关，也不要求同步读取 capability Turn 才允许播放。

## 实施计划

### 1. Timeline 投影层

- 在 `stageThreadProjection.ts` 或相邻的 role projection 模块中，为每个 capability 建立稳定
  的 role identity key。
- 按 workflow + role + activity/turn 或 materialization/attempt 标识本轮操作，以 Timeline
  sequence 和 revision/attempt 拒绝旧快照。终态只锁定本轮，新的一轮仍能重新播放。
- activity/proposal/planning 文案到达时只负责确保 role identity 出现；只有明确终态事件才
  更新 lifecycle 为 settled。
- 只补读对应 activity/materialization 的精确 Turn 终态，未 hydration、queued/running 不作为
  门槛。不读取 Journey active action、节点状态或 Continuation 中间状态，不增加额外请求。
- 当前 ChatTurn/status 合同没有 cancelled 枚举；取消只在对应操作明确返回
  `operation_stage=cancelled` 时识别，不扩大严格 normalizer 的枚举。

### 2. 同批次渲染

- `StageThread` 在动画资源 pending 时显示现有“转圈 + Working”占位，不提前显示 role identity。
- 预加载应在 Timeline 单元准备阶段触发，而不是等 role 文字已经绘制后才开始。
- animated module ready 后，role identity 文字和 `AgentRoleAnimation` 必须在同一次 React
  commit 中挂载。
- 不允许先挂载文字、再异步补动图；也不允许用静态首帧掩盖动图加载过程。
- 动图模块加载失败时，loading 占位应转为明确的资源失败状态；只有 role 进入终态后才使用
  同款静态位图作为稳定展示。

### 3. 终态驱动停止

- 将 `completed`、`failed`、`cancelled`、`superseded` 统一归入 terminal set。
- role 进入 terminal 后停止动画并保留静态位图。
- 后续旧的 working/queued 刷新不能把 terminal role 重新激活；按 identity 的序号和终态序号
  做单调合并。

### 4. 测试与验收

补充以下测试：

- role identity 首次进入 Timeline 时先显示转圈 + Working 占位，不提前显示文字或静态首帧；
- animated artwork pending 时不会出现 role 文字先行；
- 动图 ready 后，文字和动图同一 render 出现；
- 动图加载失败时显示明确的资源失败占位；
- queued/reserved/waiting/turn 未 hydration 不会让 active role 停止；
- completed、failed、cancelled、superseded 均会停止动画并回到静态位图；
- 旧 working 刷新不能覆盖已经确认的 terminal 状态；
- 多个 role 连续进入 Timeline 时，每个 role 都有独立生命周期。

建议验证命令：

```bash
npm run typecheck
npm test -- src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx
npm test -- src/features/agent-canvas/chat/agent-role-animation/
npm run test:browser:agent-role
```

## 非目标

- 不修改后端 Guided Journey、Continuation 或 Agent runtime 合同。
- 不把所有 Timeline 文案都视为 role 开始；必须有 capability identity 才创建 role lifecycle。
- 不通过忽略未知字段或放宽 normalizer 来解决动画问题。
- 不在每次 SSE、Timeline 刷新或 Turn hydration 时重新挂载动画组件。

## 验收标准

动图资源未就绪时用户只看到转圈 + Working 占位；资源就绪后 role 名称与动图同一帧进入，
在 role 明确终态之前动画持续存在；终态到达后稳定回到静态首帧，且刷新、重试和后端中间态
不会造成文字先行、闪烁、误停或重复挂载。

## 实施边界与进度（2026-09-15）

- Worktree：`/data/longwei.wu/AdCraft-worktrees/agent-role-timeline-atomic-entry-20260915`
- 分支：`feat/agent-role-timeline-atomic-entry-20260915`；首次实施阶段未合入 main。
- 用简化投影替换旧的 Journey/Node 多级投影，删除 next-role handoff 动画规则。
- completed/failed/superseded activity 或精确 Turn 终态停止本轮；open proposal 是等待选择，
  不因创建它的 Turn 已完成而停下；materialization 按其自身明确终态处理。
- 加载过程中已进入终态：直接展示非运行态及结果/错误，不补播迟到的动画。
- 动画模块资源失败：显示资源失败和最多一次重试；不会伪装成 role 工作失败，不无限重试。
- 历史已完成 role 初次打开保持静态，不把每次刷新视作新开始。
- 状态记忆只存在于当前面板内，Workflow 切换即清空，不写 localStorage。
- 继续使用既有 WAAPI artwork，保留 reduced-motion 和后台页面暂停策略，不修改图案设计。
- 浏览器用隔离 mock 页面阻塞资源 Promise 验证，不创建项目或提交真实生产操作。

## 验证结果（2026-09-15）

- [x] Timeline role 生命周期简化、同轮终态锁定及新一轮重新激活。
- [x] pending 阶段使用转圈 + Working；ready 后角色文字与动图同批进入。
- [x] 加载失败的有界重试、加载中终态到达、Workflow 切换隔离。
- [x] 补充单元测试及真实动画资源的浏览器回归；同步旧生命周期测试夹具。
- [x] 将新增 `agent-role-atomic-entry.spec.ts` 纳入标准 `test:browser:agent-role` 脚本。
- `npm run typecheck`：通过。
- `npm test -- src/features/agent-canvas/chat/`：60 个测试文件、551 项测试通过。
- 改动文件定向 ESLint：通过。
- 定向 Playwright：20 项通过（atomic-entry、runtime-panel、identity-readiness、lifecycle）。
  阻塞资源超过 1.65 秒仍不泄露名称或静态首帧；放行后动画实际运行，逐帧采样未发现文字先行。
- `git diff --check` / `git diff --cached --check`：通过。

### 已知验证限制

独立的 `npm run typecheck:browser:agent-role` 仍受现有 Gallery 夹具影响：
`tests/browser/agent-role-gallery-mock.tsx` 保留已废弃的 `waiting` 状态，与当前
`AgentRoleMotionState` 不匹配。本轮未改该展示页，未宣称完整 browser suite 通过；
正式前端 typecheck 与本次相关的 20 项浏览器回归已通过。

首次实施阶段未修改后端、未提交真实 Workflow 操作、未重启 main 的 5189 服务，
未合并 main，因此当时既有 5189 页面没有展示本 worktree 的改动。

## 本地交付安排（2026-09-15）

用户随后明确要求将这组动画改动提交并合入本地 main。采用 fast-forward 合并，
不推送远端；合并前重新检查 typecheck 和聊天单元测试。
本次不包含后来定位的气泡顶部裁剪问题，该问题只完成诊断，尚未修改。
main 中同名未跟踪的初版方案先备份，再由本分支的完整方案取代，避免覆盖丢失。
