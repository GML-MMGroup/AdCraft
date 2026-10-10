import { useMemo, useState } from "react";
import type { WorkflowNodeV2 } from "../../types-v2";
import { extractOutput, payload, type AgentModelCallDetail } from "../agent-model-call-history";
import { callIntegrity } from "./callIntegrity";
import { callTime, fieldLabel, operationPresentation, readableInput, stageLabel, statusLabel } from "./callPresentation";
import { CallDisclosure, ReadableCallValue, RecordedValue } from "./ReadableCallValue";
import { RawCallJson } from "./RawCallJson";
import { CallDraftPrompts } from "./CallDraftPrompts";

const tabs = [
  ["overview", "概览"], ["input", "输入内容"], ["output", "模型输出"],
  ["parameters", "调用参数"], ["draft", "生成提示词"], ["integrity", "错误与完整性"], ["raw", "原始 JSON"],
] as const;
type Tab = typeof tabs[number][0];

function InputOverview({ value }: { value: unknown }) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return <ReadableCallValue value={value}/>;
  const entries = Object.entries(value);
  const message = (value as Record<string, unknown>).user_input;
  return <>
    {typeof message === "string" && message.trim() ? <ReadableCallValue value={message}/> : null}
    <p className="llm-call-history__muted">本次发送了结构化上下文，包含 {entries.length} 个字段。可在「输入内容」逐项查看。</p>
    <p className="llm-call-history__prose">{entries.slice(0, 6).map(([key]) => fieldLabel(key)).join(" · ")}{entries.length > 6 ? " …" : ""}</p>
  </>;
}

function OutputContent({ output }: { output: ReturnType<typeof extractOutput> }) {
  return <>
    {output.partial ? <p className="llm-call-history__notice">这里只记录到了部分输出，内容可能尚未完整。</p> : null}
    {output.structured != null || output.text != null ? <ReadableCallValue value={output.structured ?? output.text}/> : <p className="llm-call-history__muted">未提取到回复正文，请查看下方工具调用或原始 JSON。</p>}
    {output.tools ? <CallDisclosure title="工具调用内容"><ReadableCallValue value={output.tools}/></CallDisclosure> : null}
  </>;
}

export function CallDetail({ call, readWorkflowNodes }: { call: AgentModelCallDetail; readWorkflowNodes: () => Promise<WorkflowNodeV2[]> }) {
  const [tab, setTab] = useState<Tab>("overview");
  const request = payload(call.request);
  const outcome = payload(call.outcome);
  const input = readableInput(request);
  const output = useMemo(() => extractOutput(call.outcome), [call.outcome]);
  const integrity = useMemo(() => callIntegrity(call), [call]);
  const operation = operationPresentation(call.operation_name);
  return <>
    <header className="llm-call-history__summary">
      <div><span className="llm-call-history__muted">{stageLabel(call.stage)} · {callTime(call.created_at)}</span><h2>{operation.title}</h2><p>{operation.description}</p></div>
      <span className={`llm-call-history__status llm-call-history__status--${call.status}`}>{statusLabel(call.status)}</span>
    </header>
    <div className="llm-call-history__notices" role="status">{integrity.notices.map(notice => <p key={notice}>{notice}</p>)}</div>
    <nav className="llm-call-tabs" aria-label="调用详情分类">{tabs.map(([id, label]) => <button type="button" className={tab === id ? "is-active" : ""} key={id} aria-current={tab === id ? "page" : undefined} onClick={() => setTab(id)}>{label}</button>)}</nav>
    <div className="llm-call-content">
      {tab === "overview" ? <>
        <dl className="llm-call-history__facts"><div><dt>使用模型</dt><dd>{String(request.model_ref ?? request.model ?? call.model ?? "未提供")}</dd></div><div><dt>供应商</dt><dd>{String(request.provider ?? call.provider ?? "未提供")}</dd></div></dl>
        <section className="llm-call-history__reading"><div className="llm-call-history__section-head"><h3>模型收到了什么</h3><button type="button" onClick={() => setTab("input")}>查看完整输入</button></div><InputOverview value={input.message}/></section>
        <section className="llm-call-history__reading"><div className="llm-call-history__section-head"><h3>模型返回了什么</h3><button type="button" onClick={() => setTab("output")}>查看完整输出</button></div><OutputContent output={output}/></section>
        <CallDisclosure title="调用标识 · 用于定位与关联"><dl className="llm-call-history__identifiers"><dt>操作原名</dt><dd>{call.operation_name ?? "未提供"}</dd><dt>Agent 操作 ID（run_id）</dt><dd>{call.run_id ?? "未提供"}</dd><dt>模型调用 ID（call_id）</dt><dd>{call.call_id}</dd></dl></CallDisclosure>
      </> : null}
      {tab === "input" ? <>
        <h3>用户提示词</h3><ReadableCallValue value={input.message}/>
        <CallDisclosure title="随请求发送的上下文"><ReadableCallValue value={input.context}/></CallDisclosure>
        <CallDisclosure title="系统提示词 · 角色与规则"><ReadableCallValue value={request.system_prompt ?? request.system}/></CallDisclosure>
        <CallDisclosure title="已加载的 Skills"><ReadableCallValue value={request.loaded_skills ?? request.skills}/></CallDisclosure>
        <CallDisclosure title="输出格式要求（Schema）"><RecordedValue value={request.output_schema}/></CallDisclosure>
        <CallDisclosure title="用户提示词原文 · 保留原始格式"><RecordedValue value={input.original}/></CallDisclosure>
        <CallDisclosure title="完整 Agent 请求上下文"><ReadableCallValue value={request.agent_request ?? request.context}/></CallDisclosure>
      </> : null}
      {tab === "output" ? <>
        <h3>回复与方案内容</h3><OutputContent output={output}/>
        <CallDisclosure title="模型返回文本原文"><RecordedValue value={output.text}/></CallDisclosure>
        {output.structured != null ? <CallDisclosure title="结构化结果原文"><RecordedValue value={output.structured}/></CallDisclosure> : null}
        {output.streams ? <CallDisclosure title="流式片段与事件 · 按记录原样展示"><RecordedValue value={output.streams}/></CallDisclosure> : null}
        <p className="llm-call-history__muted">无法识别的供应商字段仍保留在「原始 JSON」中。</p>
      </> : null}
      {tab === "parameters" ? <>
        <p className="llm-call-history__muted">只展示实际记录的参数；未记录的值不补默认值。</p>
        <ReadableCallValue value={{ model: request.model_ref ?? request.model ?? call.model, provider: request.provider ?? call.provider, effective_timeout_ms: request.effective_timeout_ms }}/>
        <h3>执行策略</h3><ReadableCallValue value={request.execution_policy}/>
        <CallDisclosure title="传输选项"><ReadableCallValue value={request.transport_options ?? request.stream_options}/></CallDisclosure>
        <CallDisclosure title="实际请求体"><ReadableCallValue value={request.provider_request ?? request.request_body}/></CallDisclosure>
      </> : null}
      {tab === "draft" ? <CallDraftPrompts readWorkflowNodes={readWorkflowNodes} prompts={output.draftPrompts}/> : null}
      {tab === "integrity" ? <>
        <h3>记录完整性</h3>
        <dl className="llm-call-history__facts">{([["输入记录", call.request], ["输出记录", call.outcome]] as const).map(([label, record]) => <div key={label}><dt>{label}</dt><dd>{record == null ? "尚未记录或记录丢失" : record.complete === false ? "记录不完整" : record.complete === true ? "记录完整" : "完整性未提供"}</dd></div>)}</dl>
        <h3>错误、结束原因与 Token 用量</h3>
        {call.error != null ? <ReadableCallValue value={{ error: call.error }}/> : null}
        {integrity.metadata.length ? integrity.metadata.map(entry => <section className="llm-call-history__reading" key={entry.path}><h4>{fieldLabel(entry.path.split(".").at(-1) ?? "")}</h4><ReadableCallValue value={entry.value}/><small className="llm-call-history__source">来源：{entry.path}</small></section>) : <p className="llm-call-history__muted">未提供</p>}
        {!integrity.metadata.some(entry => /\.(usage|token_usage)$/.test(entry.path)) ? <p className="llm-call-history__muted">Token 用量：未提供</p> : null}
        <CallDisclosure title="截断、脱敏与记录边界"><RecordedValue value={{ boundary: call.outcome?.boundary ?? call.request?.boundary ?? "未提供", request_truncated: request.capture_truncated ?? request.truncated ?? "未提供", outcome_truncated: outcome.capture_truncated ?? outcome.truncated ?? "未提供", redacted_paths: { request: call.request?.redacted_paths ?? "未提供", outcome: call.outcome?.redacted_paths ?? "未提供" } }}/></CallDisclosure>
      </> : null}
      {tab === "raw" ? <RawCallJson request={call.request} outcome={call.outcome}/> : null}
    </div>
  </>;
}
