# 模型无关的结构化输出兼容设计

## 目标

让 AdCraft Agent 在 Gemini、Grok、OpenAI-compatible 等模型之间切换时，能够容忍可明确解释的结构差异，同时继续保护工作流状态、用户事实和授权边界。结构化结果无法安全应用时，系统必须保留可显示的普通文字回复，不再因为结构化校验失败而让消息弹窗消失。

本设计只处理 Agent 结构化输出的兼容、校验、修复和安全降级，不改变模型选择、媒体 Provider、视频生成接口或工作流业务规则。

## 当前问题

当前数据流为：

```text
模型输出
  → 合同级归一化（目前主要删除可省略的 null）
  → Pydantic 严格合同校验
  → 语义与原文引用校验
  → 允许一次模型修复
  → 第二次失败则整轮失败
```

Gemini 已经通过 CPA 成功返回内容，但返回了以下非标准结构：

- `explicit_elements.*.presence` 使用合同之外的枚举表达；
- `target_duration_sec` 代替规范字段 `duration_seconds`；
- 部分结果带有合同未声明的额外字段。

模型调用成功与结构化提交失败被绑定在同一个 Turn 中。第二次结构化校验失败后，Agent 不持久化 assistant 消息，前端重新同步时间线时会移除临时消息，因此用户看到“回复出现后闪退”。

## 设计原则

### 语法兼容，事实严格

系统可以兼容字段命名、枚举拼写和无损类型表达差异，但不得猜测用户没有表达的事实，也不得放松以下边界：

- run ID、合同名称、模型策略和操作身份；
- 用户原文引用必须是当前消息的精确子串；
- 工作流 revision、Node ID、Asset ID、权限和 Provider 动作；
- 已冻结事实、能力白名单、数量上限和安全限制；
- 相互冲突的标准字段与别名字段。

### 合同级规则，不按模型分叉

兼容规则归属于具体结果合同，例如 `CompactTurnIntentDecisionV3`，不出现 `if provider == gemini` 或 `if model == grok`。同一份候选 JSON 无论来自哪个模型都产生相同结果。

### 可审计、可回滚

每次兼容变换记录规则 ID、字段路径和变换数量，但不记录密钥、完整 Prompt 或不受限的模型原文。未命中白名单的内容不会静默写入工作流。

## 组件设计

### 1. 合同级兼容注册表

扩展现有 `AgentStructuredNormalizationRegistry`，把每个合同的兼容逻辑保持为独立、纯函数式规则。初始只增强 `CompactTurnIntentDecisionV3`，不全局修改 Pydantic 的 `extra=forbid` 行为。

规则按固定顺序执行：

1. Unicode NFKC 和字段名的有限规范化；
2. 已知字段别名映射；
3. 已知枚举同义词映射；
4. 无损标量类型转换；
5. 仅在明确登记的对象路径删除允许忽略的额外展示字段；
6. 删除现有可省略的 `null`；
7. 生成兼容审计。

初始字段别名包括：

| 输入字段 | 规范字段 | 适用路径 |
|---|---|---|
| `target_duration_sec` | `duration_seconds` | `requirement_patch.controls_to_set` |
| `duration_sec` | `duration_seconds` | `requirement_patch.controls_to_set` |
| `resolution` | `output_resolution` | `requirement_patch.controls_to_set` |
| `fps` | `frame_rate` | `requirement_patch.controls_to_set` |

只有规范字段不存在时才能应用别名。如果标准字段和别名同时存在且值不同，返回 `agent_structured_normalization_alias_conflict`，交给模型进行一次修复。

初始 `presence` 同义词映射包括：

| 规范值 | 可接受输入 |
|---|---|
| `include` | `include`, `included`, `present`, `required`, `包含`, `需要`, `已提及` |
| `exclude` | `exclude`, `excluded`, `absent`, `omit`, `排除`, `不要`, `不需要` |
| `unspecified` | `unspecified`, `unknown`, `not_mentioned`, `not specified`, `未说明`, `未提及`, `不确定` |

匹配前只做 NFKC、首尾空白移除和 ASCII 小写化。未列入白名单的值不猜测。

无损类型转换仅覆盖合同明确为整数、布尔值或枚举的字段，例如纯数字字符串 `"60"` 转为整数 `60`。包含单位、范围或近似词的字符串不转成硬控制值，继续交给修复或安全降级处理。

额外字段不采用全局“全部忽略”。注册表必须为具体对象路径声明可删除策略；初始只覆盖已确认不会驱动工作流、不会参与事实引用且没有规范别名的展示性字段。未登记路径上的额外字段继续触发严格校验，避免未来合同字段或模型动作被静默吞掉。

### 2. 保留严格验证

兼容注册表输出仍进入现有 Pydantic 合同校验和语义校验。兼容层不替代合同，也不直接持久化任何工作流数据。

原文引用校验改为针对归一化后仍保留的字段执行，保证别名映射后的控制项依旧需要合法 `source_quote`。被丢弃的未知字段不会参与工作流变更，但会进入有界审计摘要。

### 3. 一次结构化修复

保留当前最多一次的模型修复请求。修复 Prompt 只包含：

- 合同名称；
- 有界字段路径；
- 错误代码；
- 安全裁剪后的 expected/actual；
- “只修复报告字段，不添加新字段”的指令。

兼容层不能安全处理的冲突、未知枚举、错误原文引用和业务语义错误仍由这一步修复。

### 4. 第二次失败后的安全降级

仅对用户对话入口合同 `CompactTurnIntentDecisionV3` 启用安全降级。其他会直接生成资产、执行 Provider 操作或修改节点的合同继续严格失败。

第二次结构化校验仍失败时：

1. 不应用 `explicit_elements`、`requirement_patch`、`requested_capability` 或任何工作流动作；
2. 如果候选的顶层 `assistant_message` 是合法、非空且不超过 2000 字符的字符串，将其作为普通文字回复；提取时只读取该字段，不解释嵌套对象或其他文本字段，并移除不可显示控制字符；
3. 如果没有可用文字，使用确定性提示：`已收到你的请求，但本轮结构化解析未能安全完成。你的项目没有被修改，请重试或换一种表达。`；
4. 将 Turn 标记为已完成并持久化 assistant 消息；
5. 写入有界的降级审计，包括合同、失败路径、错误代码、尝试次数和是否使用模型文字；
6. 不把降级结果伪装成成功的结构化 authoring，也不自动推进生产阶段。

这样用户消息和普通回复都会留在时间线中，且错误输出不会修改工作流。

## 数据流

```text
模型候选 JSON
  → 合同级白名单归一化
  → 严格合同与语义校验
      ├─ 通过：按原流程应用结构化结果
      └─ 失败：一次有界修复
                 ├─ 通过：按原流程应用结构化结果
                 └─ 再失败：仅对对话意图合同安全降级
                              → 丢弃动作
                              → 持久化普通回复
                              → Turn completed_with_fallback
```

现有公共 Turn 状态如果不接受新枚举，则保持 `completed`，并在 operation stage、事件或审计元数据中记录 `structured_fallback`，避免破坏前端合同。

## 错误与审计

新增或复用以下稳定错误/规则标识：

- `compact_turn_intent_v3.field_aliases.v1`；
- `compact_turn_intent_v3.presence_aliases.v1`；
- `compact_turn_intent_v3.lossless_scalars.v1`；
- `compact_turn_intent_v3.unknown_fields_dropped.v1`；
- `agent_structured_normalization_alias_conflict`；
- `agent_structured_fallback_applied`。

审计只保存规则 ID、字段路径、计数和布尔状态。生产日志不得保存用户完整请求、模型完整原始 JSON、API Key 或 Provider 凭据。

## 测试策略

### 归一化单元测试

- 规范输入保持逐字段不变；
- Gemini 风格的枚举同义词被映射；
- Grok 风格的标准值直接通过；
- `target_duration_sec`、`duration_sec`、`resolution` 和 `fps` 正确映射；
- 标准字段与别名冲突时拒绝；
- 数字字符串和布尔字符串仅在无损时转换；
- 已登记路径的可忽略额外展示字段被丢弃并产生审计；
- 未登记路径的额外字段继续严格拒绝；
- 未知枚举不被猜测；
- `source_quote` 仍必须来自当前用户消息。

### 修复与降级测试

- 第一次失败、第二次修复成功时正常应用结构化结果；
- 第二次仍失败时不产生 Requirement、Node 或 Provider 副作用；
- 可用的 `assistant_message` 被持久化并显示；
- 缺少可用文字时使用确定性提示；
- 降级 Turn 可在重新加载时间线后继续显示；
- 非对话合同不会被安全降级为成功。

### 跨模型固定样例

测试夹具按输出形状命名，不按供应商分支执行：

- `canonical_openai_shape`；
- `enum_alias_shape`；
- `field_alias_shape`；
- `extra_explanatory_fields_shape`；
- `conflicting_alias_shape`；
- `unrecoverable_shape`。

这些夹具验证同一兼容层能够处理当前 Gemini 问题，同时保持 Grok 和未来模型的规范输出不变。

### 集成验证

1. 使用 CPA Gemini 提交包含产品、60 秒、竖版等信息的中文广告请求；
2. 验证合法结构化结果能进入工作流；
3. 注入一次不可修复的结构化候选，验证文字保留且项目不变；
4. 切换 CPA Grok 重放同一固定输入，验证不需要模型专属代码；
5. 刷新页面，确认用户消息和 assistant 回复均不会消失。

## 文件边界

预计修改：

- `apps/api/app/services/v2_agent_structured_normalization.py`：合同级别名、枚举、类型和未知字段兼容；
- `apps/api/app/services/v2_agent_structured_validation.py`：归一化后语义校验顺序及降级结果入口；
- `apps/api/app/services/agent_canvas_conversation.py`：安全降级的 Turn 持久化和事件；
- `apps/api/agent/src/pi-structured-transport.ts`：第二次拒绝时传递有界降级材料，而不是直接丢失候选；
- `apps/api/agent/tests/` 与 `apps/api/tests/`：归一化、修复、降级和时间线回归测试。

不修改全局 Pydantic 模型配置，不将 `extra=forbid` 改为全局忽略，也不增加 Gemini/Grok 专属执行分支。

## 非目标

- 自动接受任意未知字段或枚举；
- 从模糊字符串猜测用户硬性要求；
- 降低权限、身份、原文引用或工作流 revision 校验；
- 在降级模式下自动创建节点、修改需求或调用媒体 Provider；
- 为每个模型维护独立 Prompt 和解析器；
- 修改 CPA 上游代码。

## 成功标准

- Gemini 当前出现的字段别名和 `presence` 差异不再导致整轮失败；
- Grok 的规范输出路径保持不变；
- 任意模型第二次结构化失败后，用户消息和普通回复刷新后仍存在；
- 降级路径不产生工作流副作用；
- 每次自动兼容与安全降级都有有界审计；
- 全部相关单元、Agent runtime 和 API 集成测试通过。
