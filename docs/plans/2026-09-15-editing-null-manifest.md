# 剪辑 Manifest 可空合同同步

## 目标与证据

后端 `EditingVideoEntryV2.timeline_start_seconds`、
`EditingManifestV2.timeline_duration_seconds`、`EditingPreviewV2.bgm_availability`
均允许显式 null。前端只兼容字段缺失，分别报 finite number / string 错误。
上轮已用后端 schema 和当前前端 normalizer 对照复现：同样的可空值后端接受、前端拒绝。
Hook 吞掉解析错误并返回 null，面板误显示没有有效 composition manifest。

本轮只改前端，保留严格合同校验；不改后端、真实连线、资产和生成任务。
用户尚未提供对应 Workflow，验收使用同合同的匿名数据（两个视频、一个 BGM），
不把该测试冒充用户节点真实响应重放。

## 方案

1. 两个时间字段的 TS 类型增加 null；缺失仍兼容，显式 null 原样保留。
2. 三个 normalizer 分支显式接纳 null，非空数值/枚举继续走原严格校验。
   不全局放宽 number/string helper，不忽略未知字段，不将自动值转换为 0。
3. 时间轴输入类型接纳 nullable start/duration，null 与缺失使用相同自动计算路径。
   测试第二段不会被放回 0，总时长按源素材计算，不硬编码 30 秒。
4. Hook 用一次 memoized 解析得到 content 和独立 contentError，无新增 effect/请求。
   真正缺少 manifest 保留缺失提示；有 manifest 但解析失败显示解析失败提示及可展开错误详情。
   该错误独立于导出/保存错误；非法内容不开放编辑和导出，不用空 manifest 掩盖。
5. 验证合法 null 能进入面板、关联 Ready 素材、播放和编辑；编辑保存仍保留其他自动字段，
   不在打开面板时自动写回或触发导出。

## 计划

- [x] 从 main 72357098 创建独立 worktree `fix/editing-null-manifest-20260915`。
- [x] 添加 normalizer 缺失/null/数值/非法类型/未知字段回归，确认原代码失败。
- [x] 添加可空时间轴计算、面板恢复和诊断分流回归。
- [x] 同步类型、normalizer、时间轴消费和错误展示。
- [x] 验证保存 payload 不丢失 null、不改写为 0，无副作用提交。
- [x] 运行 normalizer、剪辑测试、typecheck、定向 lint、浏览器回归。
- [x] 补充验证记录，作为独立分支提交的一部分；不自动合并 main 或推送远端。

## 验证记录

### 先失败、后通过

修改生产代码前运行：

```bash
npm test -- src/features/agent-canvas/model/normalizers.editingNull.test.ts
```

原实现 23 通过、4 失败：分别传 null 和三个字段一起传 null，稳定触发
`expected finite number` / `expected string`。面板与 Hook 的 3 条定向回归也先失败。
修复后三个可空字段单独和组合均通过；负数、非法类型、错误枚举和未知字段仍拒绝。

### 自动排布和保存

- 两个 Ready 视频各长 15.041667 秒，null 起点解析为 0 和 15.041667；
  null 总时长由素材计算为 30.083334，不截断为整数。
- 修改视频音量只发送一次保存，authoring manifest 中的 null 保持不变；
  不向保存请求混入 preview，打开面板不自动写回。
- 缺少 manifest 与 manifest 解析失败分别展示，错误详情可展开且自动换行。
  后续正确内容到达时面板恢复，非法内容不会开放导出。

### 执行结果

以下命令在 worktree 的 `apps/web` 下执行：

```bash
npm test -- src/features/agent-canvas/model/normalizers.editingNull.test.ts src/features/agent-canvas/editing/AgentCanvasEditingPanel.test.tsx src/features/agent-canvas/editing/useAgentCanvasEditing.test.tsx src/features/agent-canvas/editing/editingPlayableSequence.test.ts
npm test -- src/features/agent-canvas/model/normalizers.test.ts src/features/agent-canvas/model/normalizers.editingNull.test.ts src/features/agent-canvas/editing/
npm run typecheck
PLAYWRIGHT_BASE_URL=http://127.0.0.1:5199 npx playwright test tests/browser/agent-canvas-editing-mock.spec.ts
```

- 本次直接相关的 4 个测试文件：51/51 通过，其中新增 31 条回归。
- 扩大范围：267 通过、4 失败。4 项均在未修改的 main `72357098`
  单独执行 `EditingPreviewStage.test.tsx` 时同样失败（22 通过、4 失败），
  不属于本次 nullable 合同回归：无可播放片段时 BGM 的归零、末片段结束停止、
  缩短裁剪后的播放头收敛、禁用最后片段后的归零。
  本轮没有修改这些断言，也没有扩展修改预览播放策略。
- TypeScript typecheck、全部变更 TS/TSX 文件的定向 ESLint、`git diff --check` 通过。
- 浏览器 3/3 通过：可空 manifest 的两个视频与 BGM 输入展示（无自动写请求）、
  非法合同的诊断和窄屏不溢出、原有导出/下载/导入/连接下游流程。
  使用 mock API，未触发真实生成或导出；不代表用户特定 Workflow 已实测。
- 遵循 React 性能约束：在原 memoized 解析中同时产出内容和解析错误，
  不增加 effect、轮询、请求或持久化状态。

## 交付边界

改动仅在 `fix/editing-null-manifest-20260915`。main 和 5189 服务未改动，
后端合同、数据、连接和任务未改动。缺少对应 Workflow/node ID，
真实项目打开验证需在获得该标识并切换到修复版前端后进行。
