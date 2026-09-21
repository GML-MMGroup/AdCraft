# Workflow LLM 调用记录：方案与实施计划

## 目标

为每个 Workflow 提供独立的只读「LLM 调用记录」页面。页面只展示后端已经记录的调用，不参与 Agent、节点生成或 Workflow 调度。

## 边界与安全

- 浏览器只调用受权限保护的 GET BFF/API 读取入口；内部运维 token 永不进入浏览器。
- 浏览器对接契约（后端尚需提供）：`GET /workflows/{workflow_id}/agent-model-calls?offset=&limit=` 与 `GET /workflows/{workflow_id}/agent-model-calls/{call_id}`。后端必须完成登录、Workflow 访问及日志查看权限校验，并由服务端转发内部接口。
- 页面不存在 POST、PUT、PATCH、DELETE、重试、恢复、运行和删除操作。
- 读取失败只更新本页面状态；不写入聊天、节点、Workflow 状态，也不进入全局错误恢复。
- 记录内容仅在内存中使用，不写 localStorage、埋点、错误上报或媒体目录。

## UI

- Workflow 页面增加「LLM 调用记录」入口，使用 `noopener,noreferrer` 在独立标签页打开 `/workflows/:workflowId/llm-calls`，不卸载原画布。
- 页面采用左右布局：左侧调用列表，右侧调用详情。
- 列表只使用摘要，按 `run_id` 分组显示关系、按 `call_id` 区分调用，保留首次调用、传输重试、结构化修复、能力回退阶段。
- 分页固定大小（固定 50），提供上一页/下一页和手动刷新；分页和刷新最小间隔为 2.5 秒，详情请求单并发且只在点击后发生。
- 详情标签：输入、调用参数、输出、错误与完整性、原始 JSON。
- 输出适配 `chunks`、`assistant_message`、`partial_assistant_message` 及供应商扩展；无法识别时保留原始 JSON。
- `completed` 只代表模型调用完成；`failed`、`incomplete`、`outcome=null` 原样表达，不推断结构化校验通过或运行中。缺失 token 显示“未提供”。
- JSON 按文本展示，支持搜索、展开和复制，不执行 HTML。

## 数据层

新增独立 `agentModelCallHistoryApi` 读取适配器和类型/归一化函数。请求统一 `cache: no-store`、AbortSignal；不会复用任何 mutation 或 Agent 执行函数。组件卸载或 Workflow 切换时中止请求，过期响应丢弃。

## 实施步骤

1. 增加类型、归一化和仅 GET 的 API 适配器。
2. 实现调用记录页面、分页、刷新限流、详情标签和完整性提示。
3. 在 Workflow 页面工具区增加入口，补充独立路由不挂载 WorkspaceProvider、Layout 或生产运行时。
4. 添加 API/组件测试，验证请求方法、分页、详情按需加载、失败隔离和状态语义。
5. 运行 typecheck、lint、测试、build 与 diff 检查。

## 验收标准

打开、刷新、关闭页面和任何日志读取错误均不会调用生产 mutation 或改变 Workflow。列表不请求详情，点击才请求一次详情；分页、刷新、复制和搜索均只影响日志页面。


## 实现与验证记录

- 已核对 Handoff 及后端 `workflow_model_calls.py` Schema：摘要时间为 `started_at`，内容在 `request.payload`、`outcome.payload`；原始 JSON 保留完整信封。
- 浏览器入口契约为 `/api/v2/workflows/{workflow_id}/agent-model-calls`。当前只实现前端读取适配，不会回退到内部接口。后端需完成登录身份、Workflow 访问权限、日志读取权限、服务端限流及 `Cache-Control: no-store`；浏览器限流不能替代服务端保护。
- 页面级 GET 模块独立于 v2 mutation 客户端，无自动重试、持久缓存和全局错误广播。列表与详情最多各一个在途请求。
- 5 项针对性契约测试通过，覆盖信封、阶段独立记录、SDK 流/Pi 输出、只读 GET 和权限错误不重试。
- 真实受保护接口联调尚未完成；页面可使用模拟 GET 响应验证。没有调用任何真实模型或修改 Workflow。
- 先前全量测试观察到失败，尚未做基线归因；不能将其报告为已确认的历史失败。


### 第二轮加固

- 数据状态独立到 `useCallHistory`，同步锁限制列表/详情并发，卸载中止请求，服务端游标栈支持非固定步长分页。
- 手动刷新清空已展示的详情，允许再次点击读取新的 outcome；不自动批量刷新详情。
- 原始 JSON 组件同时保留完整内容和带行号的搜索结果，复制失败只显示本地提示。
- 列表格式错误不会被静默归一化为空列表；缺失 call_id 和无效游标显示读取错误。
- 重新检查本地后端及 Handoff 源后端：仅发现 internal 读取路由，浏览器权限适配仍待完成。


### 第三轮字段核对

- 增加带原始路径的用量、结束原因及错误视图，覆盖 SDK response/choices/chunks 和 Pi assistant_message/partial_assistant_message。
- 修正实际截断字段 `capture_truncated`，完整性提示在详情顶部始终可见。
- 不汇总、不估算 Token，用量只显示记录值，保留真实 0。
- 10 项针对性测试通过。
- 后端待确认项：登录身份来源、Workflow ACL、日志读取权限、受保护 GET 路由和错误契约；不得以内部 token 的存在代替用户级鉴权。
