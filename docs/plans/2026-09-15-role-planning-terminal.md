# 规划提示继承所属任务终态

## 问题与证据

`proj_acbc158635ca935d` 的 World Setting 已完成，但图标仍在播放。
真实响应：Activity/Turn completed；序号 7 的 Proposal applied，materialization completed；
序号 8 的历史 planning_progress 为 queued，引用同一 proposal_id 和 materialization_id，无 turn_id。
前端把 planning 当成独立新任务，并只取最大 sequence，因此覆盖已有完成状态。
planning normalizer 还丢弃 metadata，失去 materialization_id 等关联信息。

## 修复方案

1. planning_progress 转成消息时保留已解析的 metadata，与普通 message 分支一致。
   不放宽 Timeline 严格字段校验；metadata 仍遵守现有 record 合同。
2. 在当前角色线程内，为 Proposal、materialization、Activity Turn 建立身份索引。
   有 materialization_id 时只按精确匹配关联，同时核对 proposal_id（若有）。
   无 materialization_id 时可按 proposal_id 关联；仅有 turn_id 时关联对应任务。
   不跨 workflow、role、proposal 或已知不匹配的 materialization 继承终态。
3. 已关联规划提示作为所属任务的展示记录，共用 attemptKey/revision/attempt/terminal，
   sequence 取该提示与所属任务中较大者。后续详情补齐不会因退回较小序号被状态合并器拒绝。
4. 未关联且尚无终态的提示保持 working，避免错误提前停止真实新任务；后续详情到达再收敛。
   保留无 Proposal 的独立 planning + 精确 Turn 终态路径。
5. 仍只依据明确终态停止；不依据下一角色、节点 prompt-ready 或 runtime 中间态停动画。
   复用已有任务详情和缓存，不增加请求、轮询、DOM 测量或全局状态。

## 计划

- [x] 从 main `1add31df` 创建 `fix/role-planning-terminal-20260915` 隔离 worktree。
- [x] 添加原始/Presentation 响应形状 -> normalizer -> stage thread -> lifecycle 回归。
- [x] 添加迟到详情、旧刷新、新重试、未关联提示、精确身份不匹配测试。
- [x] 先验证回归测试在原实现失败，再修改 metadata 保留及任务归属投影。
- [x] 验证 normalizer、聊天测试、typecheck、lint 与浏览器角色动效回归。
- [x] 只读重放真实 Workflow，确认 World Setting idle；记录验证结果。

## 交付边界

仅在 `/data/longwei.wu/AdCraft-worktrees/role-planning-terminal-20260915` 实施。
不修改后端、不提交真实 Workflow 操作、不自动合并 main 或推送远端。
新增测试不使用私有业务文案或真实资源地址，使用等价的匿名响应形状。

## 验证记录

交付更新：用户已明确要求完成后合并本地 main；将本修复连同方案和测试提交，
以 fast-forward 合并，不推送远端。

- 原实现：新增回归中的 7 项失败，覆盖丢失 metadata、完成/失败任务被 queued 提示覆盖、
  迟到详情无法停止及独立 planning 的精确 Turn 关联丢失。
- 修复后：生命周期单测共 39 项通过。
- `npm test -- src/features/agent-canvas/model/normalizers.test.ts src/features/agent-canvas/chat/`：
  61 个文件、681 项测试通过。
- `npm run typecheck`、改动 TS/TSX 文件定向 ESLint、git diff 空白检查通过。
- Playwright lifecycle / runtime-panel / atomic-entry：14 项通过；新增浏览器用例让较晚 queued
  planning 跟随任务完成、失败、取消、superseded 切回位图，重试后恢复动画。
- 真实响应只读重放：World Setting 的 attemptKey 归属于 materialization，sequence 仍为 8，
  terminal=completed、motionState=idle。无需删除历史提示或修改后端响应。
- 临时 worktree 5198 预览真实项目：World Setting frame 为 idle，显示
  `/imgs/agent-role-icons/bitmaps-v1/world_setting-96.png`，无 SVG，运行中动画数为 0。
  截图：`/tmp/adcraft-world-role-terminal-fixed.png`。
- 保留严格解析及现有动效资源。按照 vercel-react-best-practices 用局部 Map 做任务关联，
  避免逐条扫描和新增请求。未更改后端或真实项目状态。
