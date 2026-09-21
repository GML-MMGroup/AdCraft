export type CallStage = "initial" | "transport_retry" | "structured_repair" | "capability_fallback" | string;
export type CallStatus = "completed" | "failed" | "incomplete" | string;

export interface AgentModelCallSummary {
  call_id: string;
  run_id: string | null;
  workflow_id: string;
  created_at: string | null;
  operation_name: string | null;
  stage: CallStage | null;
  status: CallStatus | null;
  model?: string | null;
  provider?: string | null;
  token_usage?: Record<string, unknown> | null;
  [key: string]: unknown;
}
export interface AgentModelCallPage { workflow_id: string; items: AgentModelCallSummary[]; next_offset: number | null; }
export interface AgentModelCallDetail extends AgentModelCallSummary { request?: Record<string, unknown> | null; outcome?: Record<string, unknown> | null; error?: unknown; }
const record = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const text = (value: unknown): string | null => typeof value === "string" && value.trim() ? value : null;
function requireRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("调用记录响应格式不正确。");
  return value as Record<string, unknown>;
}
export function normalizeAgentModelCallPage(value: unknown): AgentModelCallPage {
  const input = requireRecord(value);
  if (!Array.isArray(input.items) || typeof input.workflow_id !== "string") throw new Error("调用列表响应格式不正确。");
  const cursor = input.next_offset;
  if (cursor != null && (typeof cursor !== "number" || !Number.isSafeInteger(cursor) || cursor < 0)) throw new Error("调用列表分页信息不正确。");
  return {
    workflow_id: input.workflow_id,
    items: input.items.map(normalizeAgentModelCallSummary),
    next_offset: typeof cursor === "number" ? cursor : null,
  };
}
export function normalizeAgentModelCallSummary(value: unknown): AgentModelCallSummary {
  const input = requireRecord(value);
  const callId = text(input.call_id);
  if (!callId) throw new Error("调用记录缺少 call_id。");
  return {
    ...input, call_id: callId, run_id: text(input.run_id),
    workflow_id: text(input.workflow_id) ?? "",
    created_at: text(input.started_at ?? input.created_at),
    operation_name: text(input.operation_name ?? input.operation),
    stage: text(input.stage), status: text(input.status),
  };
}
export function normalizeAgentModelCallDetail(value: unknown): AgentModelCallDetail {
  const input = requireRecord(value);
  return {
    ...normalizeAgentModelCallSummary(input),
    request: input.request == null ? null : requireRecord(input.request),
    outcome: input.outcome == null ? null : requireRecord(input.outcome),
    error: input.error,
  };
}
export function jsonText(value: unknown): string { try { return JSON.stringify(value ?? null, null, 2); } catch { return String(value); } }
export function payload(value: unknown) { const envelope = record(value); return record(envelope.payload ?? envelope); }
export function extractOutput(outcome: Record<string, unknown> | null | undefined) {
  const source = payload(outcome);
  const texts: string[] = [];
  const tools: unknown[] = [];
  const visit = (value: unknown, depth = 0): void => {
    if (depth > 12 || value == null) return;
    if (typeof value === "string") { texts.push(value); return; }
    if (Array.isArray(value)) { value.forEach(item => visit(item, depth + 1)); return; }
    const item = record(value);
    if (item.type === "toolCall" || item.type === "tool_use") { tools.push(item); return; }
    if (item.tool_calls) tools.push(item.tool_calls);
    if (typeof item.text === "string") texts.push(item.text);
    if (item.content !== undefined) visit(item.content, depth + 1);
    if (item.choices) visit(item.choices, depth + 1);
    if (item.message) visit(item.message, depth + 1);
    if (item.delta) visit(item.delta, depth + 1);
  };
  // Prefer the complete message, avoiding duplication with its recorded stream prefix.
  visit(source.assistant_message ?? source.partial_assistant_message ?? source.response ?? source.chunks ?? source.content);
  if (source.tool_calls) tools.push(source.tool_calls);
  return { text: texts.length ? texts.join("") : null,
    structured: source.structured_json ?? source.json ?? source.parsed ?? null,
    tools: tools.length ? tools : null,
    partial: source.partial_assistant_message !== undefined,
    streams: source.chunks ?? source.events ?? null,
  };
}
