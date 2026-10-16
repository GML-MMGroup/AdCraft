import { payload, type AgentModelCallDetail } from "../agent-model-call-history";

/** Keep source paths beside provider-specific metadata; never calculate missing values. */
export function callIntegrity(detail: AgentModelCallDetail, locale = "zh-CN") {
  const english = locale.toLowerCase().startsWith("en");
  const outcome = payload(detail.outcome);
  const sources: Array<[string, unknown]> = [
    ["outcome.payload", outcome],
    ["outcome.payload.response", outcome.response],
    ["outcome.payload.assistant_message", outcome.assistant_message],
    ["outcome.payload.partial_assistant_message", outcome.partial_assistant_message],
  ];
  if (Array.isArray(outcome.chunks)) outcome.chunks.forEach((chunk, index) => sources.push([`outcome.payload.chunks[${index}]`, chunk]));
  const metadata: Array<{ path: string; value: unknown }> = [];
  for (const [path, value] of sources) {
    if (!value || typeof value !== "object" || Array.isArray(value)) continue;
    const source = value as Record<string, unknown>;
    for (const key of ["usage", "token_usage", "finish_reason", "end_reason", "stopReason", "stop_reason", "error", "errorMessage"]) {
      if (source[key] !== undefined && source[key] !== null) metadata.push({ path: `${path}.${key}`, value: source[key] });
    }
    if (Array.isArray(source.choices)) source.choices.forEach((choice, index) => {
      if (choice && typeof choice === "object" && "finish_reason" in choice && choice.finish_reason != null) {
        metadata.push({ path: `${path}.choices[${index}].finish_reason`, value: choice.finish_reason });
      }
    });
  }
  const notices: string[] = [];
  if (detail.status === "completed") notices.push(english ? "The model call completed; this does not mean schema validation or the whole Workflow succeeded." : "模型调用完成，不代表结构化校验或整个 Workflow 成功。");
  if (detail.status === "failed") notices.push(english ? "The call record reports a failure." : "调用记录显示失败。");
  if (detail.status === "incomplete") notices.push(english ? "The record is incomplete; it cannot be treated as currently generating." : "记录不完整，不能据此判断正在生成。");
  if (!detail.request) notices.push(english ? "The request record is missing." : "请求记录缺失。");
  if (!detail.outcome) notices.push(english ? "No output was recorded; it may also be a missing record. Running state cannot be inferred." : "尚未记录到输出，也可能是记录丢失；无法判断是否运行中。");
  for (const [phase, envelope] of [["request", detail.request], ["outcome", detail.outcome]] as const) {
    const label = phase === "request" ? "输入记录" : "输出记录";
    if (envelope?.complete === false) notices.push(english ? `${phase === "request" ? "Input" : "Output"} record is marked incomplete.` : `${label}标记为不完整。`);
    const body = payload(envelope);
    if (body.capture_truncated === true || body.truncated === true) notices.push(english ? `${phase === "request" ? "Input" : "Output"} content was truncated; the missing part cannot be restored.` : `${label}内容已截断，缺失部分无法还原。`);
  }
  return { metadata, notices };
}
