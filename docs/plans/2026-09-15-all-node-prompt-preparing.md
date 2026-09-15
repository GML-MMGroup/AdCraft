# 全类型节点提示词准备打字提示：方案与计划

## 目标与交付范围

将视频节点已有的“提示词正在准备...”循环打字提示，扩展到图片、音频、普通文本和
Script 的提示词编辑区域。沿用同一个展示组件、文案与动画样式，不为各类型另做一套动效。

本轮交付方案和实施计划，尚未修改功能代码、运行实现验收或合并 main。
已从 main `1c0a80df` 创建独立 worktree：

```text
branch: feat/prompt-preparing-all-node-types-20260915
worktree: /data/longwei.wu/AdCraft-worktrees/prompt-preparing-all-node-types-20260915
```

## 已定位的实现

- `apps/web/src/features/agent-canvas/workbench/AgentCanvasInlineWorkbench.tsx`
  当前仅在 `node_type === "video"` 且准备状态为 `queued/working` 时设置
  `preparingVideoPrompt`，并传给媒体提示词面板。
- `MediaPromptWorkbench.tsx` 已将 `preparingPrompt` 传给共享的 `FourLinePromptEditor`。
  因此图片和音频无需新建编辑器，只需统一接入上层条件。
- `FourLinePromptEditor.tsx` 通过 `preparing && !value.trim()` 显示独立覆盖层。
  提示文字不在 textarea value 中，且 `pointer-events: none`，不会拦截用户输入。
- `TextWorkbench.tsx`、`ScriptWorkbench.tsx` 也使用 `FourLinePromptEditor`，
  但目前未传 `preparing`。两者还会根据已有业务规则切换“提示词”和“正文”编辑模式。
- `agent-canvas-inline-workbench.css` 已定义共享循环：2.8 秒、`steps(10, end)`、
  `clip-path` 揭示；启用减少动态效果时静态展示完整提示。

上述短文件名均位于 `apps/web/src/features/agent-canvas/workbench/`。

## 展示规则

### 统一触发条件

必须同时满足：

1. 当前确实是生成提示词编辑器，而不是输出正文编辑器。
2. 后端 `prompt_preparation.status` 明确为 `queued` 或 `working`。
3. 当前编辑器的本地提示词值 `trim()` 后为空。

仅有节点 `status="draft"` 或 `status="working"` 不足以触发。
不凭“提示词为空”、节点创建来源或模型加载状态猜测准备状态。
手动创建与 Agent 创建的节点遵循相同规则：后端进入准备态时都可显示；
没有准备状态或仍在 `waiting_user` 时，空输入框维持原占位提示。

### 覆盖矩阵

| 节点/编辑器 | 覆盖方式 |
| --- | --- |
| Image | 在现有 Generation prompt 中接入 |
| Video | 保持现有行为，作为回归基准 |
| Audio（含 BGM） | 在现有 Generation prompt 中接入 |
| 普通 Text | 只在现有 Text prompt 模式接入；Text content 模式保持正文 |
| Script | 只在现有 Script prompt 模式接入；Script content 模式保持正文 |
| World Setting | 当前直接编辑世界设定正文，不是生成提示词，不叠加该文案 |
| Editing、source-only | 不接入，不改变原有展示 |

普通 Text 的 `canRun` 当前为非 World Setting 且节点状态是 `draft/failed`；
Script 的 `canRun` 当前为节点状态是 `draft/failed`。本次沿用这些提示词/正文切换规则，
不把 `ready/working` 下的正文编辑器强行改回提示词编辑器。

### 动效与退出

统一文案为 `提示词正在准备...`，显示在内容区，不新增外部准备状态框。
顺序保持：打字式逐步出现 → 完整停留 → 整句消失 → 再次开始。
保留现有 2.8 秒周期、字号、颜色和关键帧；不增加逐字删除、光标、扫光或淡出动画。
该循环表达持续准备状态，不是每次点击/键盘操作的入场动画。

- 真实提示词到达或用户输入非空文字：立即移除提示，展示真实内容，不等动画播放完。
- 用户清空文字且准备仍在进行：可以重新显示提示；不改变准备任务。
- 状态进入 `ready/failed/waiting_user/superseded/not_applicable`，或准备字段为空：停止显示。
- 失败即使提示词仍为空，也不能继续显示“正在准备”；保留各面板现有的错误处理。
- 准备状态短暂落后但正文已到达：非空输入优先，不能用动画覆盖真实提示词。
- 关闭面板：随现有组件卸载停止；再次打开时根据当前状态和输入内容重新判断。
- 减少动态效果：沿用现有 CSS 降级，完整静态文案，不循环播报每个字符。

## 实现方案

### 1. 统一父层状态

在 `AgentCanvasInlineWorkbench.tsx` 将视频专用变量改为通用准备标记，例如：

```ts
const preparingGenerationPrompt = requiresPreparedPrompt
  && (preparationStatus === "queued" || preparationStatus === "working");
```

保留现有 source-only 提前退出，以及 `requiresPreparedPrompt` 对 World Setting 的排除。
将标记分别传给 Media、Text、Script workbench，不根据文件名或角色名称推断状态。

### 2. 每种编辑器只处理自己的输入语义

- Media：继续通过 `preparingPrompt` 传给 `FourLinePromptEditor.preparing`。
- Text/Script：新增可选的 `preparingPrompt = false` prop；在提示词模式下传入
  `preparing={canRun && preparingPrompt}`，正文模式不传活动准备状态。
- 共享编辑器继续以实际 `value` 判断空值，不再另外引入一份“后端提示词是否为空”的状态。
  不改变 `onChange`、`onBlur`、本地草稿、自动保存、禁用条件或按钮行为。
- CSS 原则上不改：扩展接入范围，而不是重设计视频已确定的动效。

### 3. 避免重复准备提示，保留现有刷新链路

视频、音频、Script 目前会挂载 `NodePromptPreparationState`。
为活动准备态设置通用 `hideActiveStatus`，不再同时显示外部 Preparing 文案。
不能为了隐藏文案把组件整个卸载：它还承载 Presentation Stream 的终态监听和 Workflow 刷新。
保留组件挂载、已有监听及终态去重，只隐藏活动状态的可见内容。

图片和普通文本此前已不显示该外部状态区域，本轮不重新加入它，也不为打字提示新建 SSE 订阅。
`failed/waiting_user/superseded` 不使用 `hideActiveStatus` 掩盖，保留当前各面板已有处理；
不恢复此前已删除的图片/文本外部状态框。

### 4. 性能与数据安全

沿用 CSS 动画和渲染时派生布尔值；不新增 JS 打字计时器、逐字 React state、轮询或网络请求。
不改变节点挂载/卸载、卡片尺寸、提示词框高度及底部工具栏位置。
不改最近合入的模型缓存、Agent role 动图、节点生成点阵或聊天 Timeline。
提示文案不能进入任何草稿、复制文本、自动保存 payload 或生成请求；
保留 `aria-busy`、提示层 `aria-hidden` 及减少动态效果支持。

## 实施计划

- [x] 定位五类节点的共享编辑器、准备状态条件、正文分支和 Presentation Stream 刷新职责。
- [x] 创建独立 worktree，写明本方案及验收标准。
- [ ] 先扩展 `AgentCanvasInlineWorkbench.test.tsx`：为 image/audio/text/script 的空提示词
  `queued/working` 建立失败用例，同时保留视频基准用例。
- [ ] 统一父层准备标记，向 Media/Text/Script 传递；Text/Script 添加提示词模式防护。
- [ ] 为音频和 Script 隐藏重复的活动准备状态内容，保留现有监听及错误路径。
- [ ] 补齐以下状态矩阵与无副作用测试。
- [ ] 扩展现有 mock 页面，添加跨类型浏览器动画回归。
- [ ] 执行静态检查、组件/自动保存测试、模型缓存回归及浏览器验收。
- [ ] 更新本文件的验证结果，在独立分支提交；本轮不包含自动合并 main 或推送远端。

## 验收清单

1. 五种节点在空提示词 + queued/working 时，各只有一份共享提示，textarea 仍为空。
2. 对 `ready/failed/waiting_user/superseded/not_applicable/null` 参数化验证没有准备动画。
3. 后端已有提示词、仅本地有输入、空白字符串、用户输入后再清空都符合规则。
4. 通过 rerender 验证 queued → working → ready 和 working → failed，无需刷新页面即可退出。
5. 普通 Text/Script 的正文分支，包括空正文，以及 World Setting、Editing、source-only 均不误触发。
6. 手动空白节点不会假装正在准备；真实进入准备态后与 Agent 节点行为一致。
7. 准备提示挂载/循环不调用 patchNode、run 或额外刷新；已存在的 Stream 终态刷新仍正常。
8. 用户输入可以正常自动保存，payload 中不包含提示文案；现有保存/运行按钮行为不变。
9. 浏览器验证准备 → 展示 → 整句清空 → 新循环、输入立即退出，以及 reduced-motion 静态提示。
10. 检查宽窄面板和画布缩放场景，无文本溢出、布局位移或底部工具栏跳动。

建议命令（在 worktree 的 `apps/web` 执行）：

```bash
npm run typecheck
npm test -- src/features/agent-canvas/workbench/ src/features/agent-canvas/model/useAgentCanvasProviderModels.test.tsx
npx eslint src/features/agent-canvas/workbench/AgentCanvasInlineWorkbench.tsx src/features/agent-canvas/workbench/TextWorkbench.tsx src/features/agent-canvas/workbench/ScriptWorkbench.tsx src/features/agent-canvas/workbench/AgentCanvasInlineWorkbench.test.tsx
npx playwright test tests/browser/workbench-prompt-preparing.spec.ts tests/browser/workbench-model-cache.spec.ts
git diff --check
```

`workbench-prompt-preparing.spec.ts` 是拟新增的浏览器验收文件，不是当前已存在的测试。
使用 mock API，不创建真实任务；已有失败需要先与 main 对照，不以放宽断言掩盖。

## 本轮状态

仅完成定位和方案文档。实现、单测/浏览器验收、提交功能改动与合并尚未执行。
