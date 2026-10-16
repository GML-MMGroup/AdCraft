import { useTranslation } from "../../i18n/useTranslation";
import { useMemo, useState } from "react";
import type { WorkflowNodeV2 } from "../../types-v2";
import { extractOutput, payload, type AgentModelCallDetail } from "../agent-model-call-history";
import { callIntegrity } from "./callIntegrity";
import { callTime, fieldLabel, operationPresentation, readableInput, stageLabel, statusLabel } from "./callPresentation";
import { CallDisclosure, ReadableCallValue, RecordedValue } from "./ReadableCallValue";
import { RawCallJson } from "./RawCallJson";
import { CallDraftPrompts } from "./CallDraftPrompts";
import { useUiLocale } from "../../i18n/locale";

const tabs = [
  ["overview", "Overview"], ["input", "Input"], ["output", "Model output"],
  ["parameters", "Parameters"], ["draft", "Draft prompts"], ["integrity", "Errors and integrity"], ["raw", "Raw JSON"],
] as const;
type Tab = typeof tabs[number][0];

function InputOverview({ value, locale }: { value: unknown; locale: string }) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return <ReadableCallValue value={value}/>;
  const entries = Object.entries(value);
  const message = (value as Record<string, unknown>).user_input;
  return <>
    {typeof message === "string" && message.trim() ? <ReadableCallValue value={message}/> : null}
    <p className="llm-call-history__muted">{locale.startsWith("en") ? `Structured context with ${entries.length} fields was sent. See Input for each field.` : `本次发送了结构化上下文，包含 ${entries.length} 个字段。可在「输入内容」逐项查看。`}</p>
    <p className="llm-call-history__prose">{entries.slice(0, 6).map(([key]) => fieldLabel(key, locale)).join(" · ")}{entries.length > 6 ? " …" : ""}</p>
  </>;
}

function OutputContent({ output }: { output: ReturnType<typeof extractOutput> }) {
  const t = useTranslation();
  return <>
    {output.partial ? <p className="llm-call-history__notice">{t("Only partial output was recorded; the content may be incomplete.")}</p> : null}
    {output.structured != null || output.text != null ? <ReadableCallValue value={output.structured ?? output.text}/> : <p className="llm-call-history__muted">{t("No reply text could be extracted. Check tool calls or Raw JSON.")}</p>}
    {output.tools ? <CallDisclosure title={t("Tool calls")}><ReadableCallValue value={output.tools}/></CallDisclosure> : null}
  </>;
}

export function CallDetail({ call, readWorkflowNodes }: { call: AgentModelCallDetail; readWorkflowNodes: () => Promise<WorkflowNodeV2[]> }) {
  const locale = useUiLocale();
  const t = useTranslation();
  const [tab, setTab] = useState<Tab>("overview");
  const request = payload(call.request);
  const outcome = payload(call.outcome);
  const input = readableInput(request);
  const output = useMemo(() => extractOutput(call.outcome), [call.outcome]);
  const integrity = useMemo(() => callIntegrity(call, locale), [call, locale]);
  const operation = operationPresentation(call.operation_name, locale);
  return <>
    <header className="llm-call-history__summary">
      <div><span className="llm-call-history__muted">{stageLabel(call.stage, locale)} · {callTime(call.created_at, locale)}</span><h2>{operation.title}</h2><p>{operation.description}</p></div>
      <span className={`llm-call-history__status llm-call-history__status--${call.status}`}>{statusLabel(call.status, locale)}</span>
    </header>
    <div className="llm-call-history__notices" role="status">{integrity.notices.map(notice => <p key={notice}>{notice}</p>)}</div>
    <nav className="llm-call-tabs" aria-label={t("Call detail tabs")}>{tabs.map(([id, label]) => <button type="button" className={tab === id ? "is-active" : ""} key={id} aria-current={tab === id ? "page" : undefined} onClick={() => setTab(id)}>{t(label as never)}</button>)}</nav>
    <div className="llm-call-content">
      {tab === "overview" ? <>
        <dl className="llm-call-history__facts"><div><dt>{t("Model")}</dt><dd>{String(request.model_ref ?? request.model ?? call.model ?? t("Not provided"))}</dd></div><div><dt>{t("Provider")}</dt><dd>{String(request.provider ?? call.provider ?? t("Not provided"))}</dd></div></dl>
        <section className="llm-call-history__reading"><div className="llm-call-history__section-head"><h3>{t("Model received")}</h3><button type="button" onClick={() => setTab("input")}>{t("View full input")}</button></div><InputOverview value={input.message} locale={locale}/></section>
        <section className="llm-call-history__reading"><div className="llm-call-history__section-head"><h3>{t("Model returned")}</h3><button type="button" onClick={() => setTab("output")}>{t("View full output")}</button></div><OutputContent output={output}/></section>
        <CallDisclosure title={t("Call identifiers · for tracing and association")}><dl className="llm-call-history__identifiers"><dt>{t("Recorded operation name")}</dt><dd>{call.operation_name ?? t("Not provided")}</dd><dt>{t("Agent operation ID (run_id)")}</dt><dd>{call.run_id ?? t("Not provided")}</dd><dt>{t("Model call ID (call_id)")}</dt><dd>{call.call_id}</dd></dl></CallDisclosure>
      </> : null}
      {tab === "input" ? <>
        <h3>{t("User prompt")}</h3><ReadableCallValue value={input.message}/>
        <CallDisclosure title={t("Context sent with the request")}><ReadableCallValue value={input.context}/></CallDisclosure>
        <CallDisclosure title={t("System prompt · role and rules")}><ReadableCallValue value={request.system_prompt ?? request.system}/></CallDisclosure>
        <CallDisclosure title={t("Loaded Skills")}><ReadableCallValue value={request.loaded_skills ?? request.skills}/></CallDisclosure>
        <CallDisclosure title={t("Output schema")}><RecordedValue value={request.output_schema}/></CallDisclosure>
        <CallDisclosure title={t("Original user prompt · formatting preserved")}><RecordedValue value={input.original}/></CallDisclosure>
        <CallDisclosure title={t("Full Agent request context")}><ReadableCallValue value={request.agent_request ?? request.context}/></CallDisclosure>
      </> : null}
      {tab === "output" ? <>
        <h3>{t("Reply and creative content")}</h3><OutputContent output={output}/>
        <CallDisclosure title={t("Original model text")}><RecordedValue value={output.text}/></CallDisclosure>
        {output.structured != null ? <CallDisclosure title={t("Original structured result")}><RecordedValue value={output.structured}/></CallDisclosure> : null}
        {output.streams ? <CallDisclosure title={t("Stream fragments and events · as recorded")}><RecordedValue value={output.streams}/></CallDisclosure> : null}
        <p className="llm-call-history__muted">{t("The provider field is preserved in Raw JSON when it cannot be parsed.")}</p>
      </> : null}
      {tab === "parameters" ? <>
        <p className="llm-call-history__muted">{t("Recorded parameters only; missing values are not filled with defaults.")}</p>
        <ReadableCallValue value={{ model: request.model_ref ?? request.model ?? call.model, provider: request.provider ?? call.provider, effective_timeout_ms: request.effective_timeout_ms }}/>
        <h3>{t("Execution limitations")}</h3><ReadableCallValue value={request.execution_policy}/>
        <CallDisclosure title={t("Transport options")}><ReadableCallValue value={request.transport_options ?? request.stream_options}/></CallDisclosure>
        <CallDisclosure title={t("Actual request body")}><ReadableCallValue value={request.provider_request ?? request.request_body}/></CallDisclosure>
      </> : null}
      {tab === "draft" ? <CallDraftPrompts readWorkflowNodes={readWorkflowNodes} prompts={output.draftPrompts}/> : null}
      {tab === "integrity" ? <>
        <h3>{t("Record integrity")}</h3>
        <dl className="llm-call-history__facts">{([[t("Input record"), call.request], [t("Output record"), call.outcome]] as const).map(([label, record]) => <div key={label}><dt>{label}</dt><dd>{record == null ? t("Not recorded or record missing") : record.complete === false ? t("Record incomplete") : record.complete === true ? t("Record complete") : t("Integrity not provided")}</dd></div>)}</dl>
        <h3>{t("Errors, end reason and token usage")}</h3>
        {call.error != null ? <ReadableCallValue value={{ error: call.error }}/> : null}
        {integrity.metadata.length ? integrity.metadata.map(entry => <section className="llm-call-history__reading" key={entry.path}><h4>{fieldLabel(entry.path.split(".").at(-1) ?? "", locale)}</h4><ReadableCallValue value={entry.value}/><small className="llm-call-history__source">{locale.toLowerCase().startsWith("en") ? "Source: " : "来源："}{entry.path}</small></section>) : <p className="llm-call-history__muted">{t("Not provided")}</p>}
        {!integrity.metadata.some(entry => /\.(usage|token_usage)$/.test(entry.path)) ? <p className="llm-call-history__muted">{t("Token usage: not provided")}</p> : null}
        <CallDisclosure title={t("Truncation, redaction and capture boundaries")}><RecordedValue value={{ boundary: call.outcome?.boundary ?? call.request?.boundary ?? t("Not provided"), request_truncated: request.capture_truncated ?? request.truncated ?? t("Not provided"), outcome_truncated: outcome.capture_truncated ?? outcome.truncated ?? t("Not provided"), redacted_paths: { request: call.request?.redacted_paths ?? t("Not provided"), outcome: call.outcome?.redacted_paths ?? t("Not provided") } }}/></CallDisclosure>
      </> : null}
      {tab === "raw" ? <RawCallJson request={call.request} outcome={call.outcome}/> : null}
    </div>
  </>;
}
