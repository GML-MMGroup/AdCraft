# 视频节点提示词准备态打字机动画

## 目标

在 Agent 生成视频节点的提示词准备阶段，把提示词输入框内部作为唯一的准备态反馈。输入框显示“提示词正在准备...”的循环打字机效果，不再额外显示 queued/working 的准备状态卡片。

## 展示契约

- 仅当视频节点的 `prompt_preparation.status` 为 `queued` 或 `working`，且当前没有真实 `generation_prompt` 时显示动画。
- 动画文字是纯视觉占位，不写入 textarea value、draft、autosave 或 PATCH 请求。
- 动画序列为：空白 → 逐字出现 → 完整停留 → 整句瞬间清空 → 再次逐字出现。
- 后端返回真实 `generation_prompt` 后，动画立即消失，输入框显示真实提示词。
- 用户开始输入后，真实输入优先，动画不覆盖用户内容。
- Prompt preparation 的 `failed`、`superseded`、`waiting_user` 仍保留结构化状态/错误展示，不误用“准备中”动画。
- 保持现有四行输入框高度和底部工具栏布局，不造成布局位移。
- `prefers-reduced-motion: reduce` 下使用静态提示文字，不循环移动或闪烁。

## 实施计划

1. 扩展 `FourLinePromptEditor`，增加准备态视觉层；保持受控 textarea 的真实值不变，并通过 `pointer-events: none` 保证输入行为不受遮挡。
2. 在视频 `MediaPromptWorkbench` 中传入准备态，只对 queued/working 的视频节点启用。
3. 在 `AgentCanvasInlineWorkbench` 中隐藏视频 queued/working 的独立 `NodePromptPreparationState` 视觉内容，但保留其 presentation stream 监听和完成事件刷新；失败和等待用户等需要行动的状态继续展示。
4. 增加工作台测试，覆盖：准备态动画存在且 textarea 为空、准备卡片隐藏、真实提示词到达后动画消失、用户输入优先。
5. 运行工作台测试、类型检查，并检查变更只发生在当前 worktree。

## 动画实现决策

- 工具：CSS animation，避免用定时器驱动逐帧 React 重渲染。
- 属性：使用 `clip-path` 做离散字符式揭示；不改变输入框尺寸或布局属性。
- 循环：打字阶段使用 `steps()`，完整停留后在单个关键帧瞬间清空。
- 目的：状态指示；动画只帮助用户理解提示词仍在准备，不模拟真实生成进度。
- 无障碍：动画层标记为装饰性内容，textarea 保留可读的静态 placeholder；减少动效偏好下降级为静态文字。
