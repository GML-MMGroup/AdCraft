# 角色运行中终态自动同步

## 目标与根因

不刷新页面，角色所属任务完成后自动停止动画，统一覆盖所有 capability。
不改变动画设计、角色入场、占位、Waiting/Working 文案或终态定义。

真实 Prop Designer 响应重放已复现：后端 Proposal applied / materialization completed，
前端连续三次 Timeline 读取仍保留首次 open 详情，Proposal 仅请求一次。
Presentation 合并在相同 revision/sequence 时保留已补齐的旧 Proposal；
hydrateTimelineItems 只识别 pointer，不再刷新该 Proposal。
仅在诊断重放中提高 Presentation revision 后，详情重新加载，角色立即 idle。
这是动态实体详情与展示条目版本被错误耦合，不是 Prop 特有动画问题。

## 方案

1. 保留 Presentation 合并及其版本/序号防回退规则，不为刷新详情伪造更高版本。
2. 从本次响应的原始展示条目中提取 pointer，再单独驱动实体补齐/刷新，
   不依赖合并后的条目是否仍是 pointer。同类型同 ID 的引用去重。
   更新可命中 pointer 或已经展示的 Proposal，保留原有条目位置与展示身份。
3. 详情返回时，既可以替换 pointer，也可以更新同 ID 已补齐的实体；
   不先退回 pointer、不清空当前内容、不重挂整个角色线程。
4. 沿用当前按 chatRevision 失效、按实体 ID 缓存 Promise、Workflow 切换清理的机制。
   普通同修订重复刷新复用请求；聊天修订失效后恢复原本被 Presentation 路径漏掉的详情读取。
   不新增计时器、轮询、逐角色请求入口；不为每次渲染发请求。
   现有失效是整批实体失效，不在本轮宣称历史终态永不再读取。
5. 沿用刷新 generation 与 Workflow generation 保护，旧项目和旧刷新结果不得覆盖新状态。
   单个详情失败保留已有内容，失败缓存清除，后续既有刷新可重试。
6. 已有 role lifecycle 根据新的权威详情继承 completed/failed/superseded，
   防止同一次任务被旧状态重新激活；新任务/重试仍可启动。
7. 同一补齐链路中的 Decision Bundle 同步处理已补齐引用，避免两类实体刷新语义分裂。
   不改变其业务提交或状态语义。

## 实施计划

- [x] 从 main d6e94f5a 创建独立 worktree fix/role-live-terminal-refresh-20260915。
- [x] 将已复现的连续页面场景写为 hook + role lifecycle 回归，确认原代码失败。
- [x] 参数化覆盖 10 个角色及同版本 Presentation 下的终态更新。
- [x] 覆盖保持旧内容、失败后重试、刷新乱序、切换项目、重试及请求去重。
- [x] 实施通用实体引用刷新，保持展示合并语义。
- [x] 聊天测试、typecheck、定向 lint、真实响应只读浏览器重放及角色浏览器回归。
- [x] 更新验证记录；代码在独立分支交付，不自动合并 main 或推送远端。

## 验收

同页先展示未完成任务，再使后端详情变为终态，触发已有 chatRevision 刷新；
Presentation key/revision/sequence 均不变化，前端仍更新实体并停止动画。
测试不得通过 reload、抬高 Presentation revision、换角色名称或直接传入完成动效状态绕过链路。
所有真实项目请求只读，不提交方案、不启动生成、不修改后端。

## 验证记录

- 已将新增 hook 回归对照运行于原实现：15 项因缺失第二次详情请求或仍 working 失败。
  修复后本文件 18 项通过，包括 10 个角色、失败/superseded/重试、旧序号不改变位置、
  同 ID 去重、Decision Bundle 刷新、暂挂/失败保留内容、旧刷新及跨 Workflow 迟到响应。
- `npm test -- src/features/agent-canvas/chat/`：61 个文件，592 项通过。
- `npm run typecheck`：通过；源代码、新测试和浏览器 fixture/spec 定向 ESLint 通过。
- lifecycle/runtime-panel/atomic-entry 浏览器回归完整运行 15 项通过；
  包含新增 live-detail-refresh，固定 Presentation key/revision/sequence，
  不 reload、不直接传入 motionState；验证真实聊天面板由 SVG 切回位图、原 frame 不重挂，
  completed/failed/superseded 后停止，重试再播放。
- 真实 Prop 响应只读重放（5198 worktree）：首次详情 open，第二次 Timeline 刷新后
  详情读取从 1 次增至 2 次，materialization completed，角色 idle；
  同修订显式刷新后仍为 2 次详情读取。没有提高 Presentation 版本才修正的依赖。
- 没有修改后端、动画资源或真实 Workflow；诊断脚本保留在 `/tmp/adcraft-prop-live-terminal-diagnostic.mjs`，
  临时浏览器内替换 API，所有真实写请求被阻断。

## 预防与边界

展示条目版本只控制展示合并，不能充当其引用的可变实体版本。
以后这类回归应同时覆盖 pointer 首次补齐和同页补齐后再更新，不能只用完整实体 fixture 或 reload 验收。
本次依赖现有聊天/SSE 刷新信号；不在网络中断、后端未发布状态或未提供刷新信号时凭空宣布完成。
本轮不处理首次详情加载前可能短暂播放的展示策略，也不实现此前暂停的空白占位方案。
