# Timeline 连续回复气泡顶部裁剪修复

## 需求与根因

当前 5189 的 `proj_acbc158635ca935d` 中，`Run the current Drafts before continuing guided production.`
气泡顶部约 8px 被裁掉。连续 Agent 消息的 `margin-top: -8px` 让气泡超出
`VirtualizedTimeline` 条目的绘制边界，而条目的 `content-visibility: auto` 引入绘制隔离。
浏览器命中测试及截图已复现；单独取消负边距或 content-visibility 可恢复，取消入场动画不能恢复。

## 方案

1. 移除气泡 article 上的连续回复负边距，让气泡完整留在条目内部。
2. 将同样的 -8px 紧凑间距放到 `.agent-chat__timeline-virtualized-item` 外侧，抵消父级
   16px gap 的一半。父级 flex 容器不做绘制隔离，因此不会切掉气泡。
3. 使用局部直接子元素选择器 `:has(> .agent-chat__message--agent.continues-speaker-run)`
   识别连续 Agent 消息；项目已经使用 :has，不增加新的浏览器能力要求。
   首个条目不使用负外边距；正常消息、用户消息、角色条目及决策卡维持原间距。
4. 不更改消息分组逻辑、内容、动画、后端合同、角色生命周期或自动滚动策略。
5. 保留 content-visibility、contain-intrinsic-size 与 IntersectionObserver 按需挂载。
   不增加 React 状态、DOM 尺寸测量、轮询或滚动监听。

## 实施计划

- [x] 从本地 main `5d30caea` 创建隔离 worktree：
  `/data/longwei.wu/AdCraft-worktrees/chat-bubble-clipping-20260915`。
- [x] 使用真实 VirtualizedTimeline + NaturalMessage + 生产 CSS 建立浏览器回归夹具。
- [x] 修复前确认测试能捕获顶部裁剪，而不是只检查文本可见。
- [x] 将紧凑间距移至外层条目，完成最小 CSS 修复。
- [x] 验证窄/宽面板下顶部绘制、连续消息 8px 间距、普通条目 16px 间距、首条边界。
- [x] 验证滚出再进入视口、长消息展开收起和 content-visibility 保留。
- [x] 运行前端 typecheck、相关单元测试、定向浏览器回归及改动检查。

## 验收与交付

气泡顶部边框与圆角完整，气泡上方 2/4/6px 的中心点均命中气泡自身；气泡 top 不小于
条目 top。连续消息保持紧凑间距，不靠关闭性能优化修复。浏览器夹具不发真实 Workflow
写请求。首次实施仅在 worktree 完成，未自动提交或合并 main，不影响既有 5189 服务。

2026-09-15 用户随后明确要求提交到本地 main：将修复、文档和回归测试一并提交，
采用 fast-forward 合并，不推送远端。

## 验证记录

- 修复前：`npx playwright test tests/browser/chat-bubble-clipping.spec.ts -g 'width 390'`
  稳定失败于顶部边界/命中断言（expected true, received false），截图显示顶部被切平。
- 修复后：`npm run test:browser:chat-bubble`，4 项通过；390/720 viewport、首条 continuation、
  历史按需挂载与滚动返回、长回复展开收起全部通过。
- `npm run typecheck`：通过。
- VirtualizedTimeline、NaturalMessage、naturalMessagePresentation、AgentCanvasChatPanel：
  4 个单元测试文件、83 项测试通过。
- 新增浏览器 TS/TSX 文件定向 ESLint、git diff 空白检查：通过。
- 临时在 worktree 的 5198 端口打开真实 `proj_acbc158635ca935d` 验证，只浏览和折叠决策卡，
  不提交生产操作。气泡 top 与条目 top 均为 734.90625px；article margin 为 0，
  条目 margin 为 -8px；content-visibility 仍为 auto；顶部 2/4/6px 命中全部通过。
  截图 `/tmp/adcraft-bubble-worktree-fixed.png` 中顶部边框与圆角已恢复。
- 按 vercel-react-best-practices 的 content-visibility 建议保留长列表优化，生产代码只调整 CSS。
- npm ci 报告依赖树有 12 项安全告警；未执行自动升级或改动 lockfile，不属于本次裁剪修复。
