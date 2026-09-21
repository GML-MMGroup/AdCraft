import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useCallHistory } from "../features/model-call-history/useCallHistory";
import { callIntegrity } from "../features/model-call-history/callIntegrity";
import { RawCallJson } from "../features/model-call-history/RawCallJson";
import { extractOutput, jsonText, payload, type AgentModelCallSummary } from "../features/agent-model-call-history";
import "./workflow-model-call-history.css";

type Tab = "input" | "params" | "output" | "integrity" | "raw";
const tabs: Array<[Tab, string]> = [["input", "输入"], ["params", "调用参数"], ["output", "输出"], ["integrity", "错误与完整性"], ["raw", "原始 JSON"]];
function Value({ value }: { value: unknown }) { return <pre className="llm-call-history__value">{typeof value === "string" ? value : jsonText(value)}</pre>; }

export function WorkflowModelCallHistoryPage() {
  const { workflowId = "" } = useParams<{ workflowId: string }>();
  return <WorkflowCallHistory key={workflowId} workflowId={workflowId} />;
}

function WorkflowCallHistory({ workflowId }: { workflowId: string }) {
  const { items, selected, loading, detailLoading, error, detailError, cooldown,
    canPrevious, canNext, refresh, previous, next, select } = useCallHistory(workflowId);
  const [tab, setTab] = useState<Tab>("input");
  function selectCall(call: AgentModelCallSummary) {
    setTab("input");
    void select(call.call_id);
  }
  const request = payload(selected?.request);
  const outcome = payload(selected?.outcome);
  const integrity = useMemo(() => selected ? callIntegrity(selected) : null, [selected]);
  const output = useMemo(() => extractOutput(selected?.outcome), [selected]);
  return <main className="llm-call-history" aria-label="LLM 调用记录">
    <header className="llm-call-history__header"><button type="button" onClick={() => window.close()}>关闭日志页</button><div><span className="eyebrow">READ-ONLY LOG</span><h1>LLM 调用记录</h1></div><button type="button" onClick={() => void refresh()} disabled={loading || cooldown}>刷新</button></header>
    <div className="llm-call-history__layout">
      <section className="llm-call-history__list" aria-label="调用列表"><div className="llm-call-history__list-head"><span>{loading ? "读取中…" : `${items.length} 条记录`}</span><span>仅展示已有记录</span></div>{!loading && !error && items.length === 0 ? <p>暂无已记录的调用。</p> : null}{error ? <p className="llm-call-history__error" role="alert">{error}</p> : null}{items.map((call) => <button className={`llm-call-row${selected?.call_id === call.call_id ? " is-selected" : ""}`} key={call.call_id} type="button" disabled={detailLoading} onClick={() => void selectCall(call)}><small>call {call.call_id}</small><strong>{call.operation_name ?? "未命名操作"}</strong><span>{({ initial: "首次调用", transport_retry: "传输重试", structured_repair: "结构化修复", capability_fallback: "能力回退" } as Record<string, string>)[call.stage ?? ""] ?? call.stage ?? "未提供"} · {call.status ?? "未提供"}</span><small>{call.created_at ?? "未提供"} · run {call.run_id ?? "未提供"}</small></button>)}<nav className="llm-call-history__pagination"><button type="button" disabled={!canPrevious || loading || cooldown} onClick={() => void previous()}>上一页</button><button type="button" disabled={!canNext || loading || cooldown} onClick={() => void next()}>下一页</button></nav></section>
      <section className="llm-call-history__detail" aria-live="polite">{detailLoading ? <p>读取详情…</p> : detailError ? <p className="llm-call-history__error" role="alert">{detailError}</p> : !selected ? <p className="llm-call-history__empty">选择一条记录查看详情。详情不会随列表批量读取。</p> : <><div className="llm-call-history__summary"><div><span className="eyebrow">{selected.call_id}</span><h2>{selected.operation_name ?? "未命名操作"}</h2></div><span className={`status status--${selected.status ?? "unknown"}`}>{selected.status ?? "未提供"}</span></div><div role="status">{integrity?.notices.map(notice => <p key={notice}>{notice}</p>)}</div><div className="llm-call-tabs">{tabs.map(([id, label]) => <button type="button" className={tab === id ? "is-active" : ""} key={id} onClick={() => setTab(id)}>{label}</button>)}</div><div className="llm-call-content">
        {tab === "input" ? <><h3>提示与上下文</h3><Value value={request.system_prompt ?? request.system ?? "未提供"}/><h3>用户提示词</h3><Value value={request.user_prompt ?? request.user ?? "未提供"}/><h3>完整上下文 / Skills / Schema</h3><Value value={{ context: request.context ?? request.agent_request ?? "未提供", skills: request.loaded_skills ?? request.skills ?? "未提供", output_schema: request.output_schema ?? "未提供" }}/></> : null}
        {tab === "params" ? <><h3>模型与执行策略</h3><Value value={{ model: request.model_ref ?? request.model ?? "未提供", provider: request.provider ?? "未提供", timeout: request.timeout ?? "未提供", execution_strategy: request.execution_policy ?? request.execution_strategy ?? "未提供" }}/><h3>实际请求体</h3><Value value={request.provider_request ?? request.request_body ?? "未提供"}/><h3>传输选项</h3><Value value={request.stream_options ?? request.transport_options ?? "未提供"}/></> : null}
        {tab === "output" ? <><h3>模型返回文本</h3><Value value={output.text ?? "未提供"}/><p>{output.partial ? "提示：输出包含流式片段或部分输出。" : ""}</p><h3>结构化 JSON</h3><Value value={output.structured ?? "未提供"}/><h3>工具调用</h3><Value value={output.tools ?? "未提供"}/><h3>流式片段 / 事件（记录原文）</h3><Value value={output.streams ?? "未提供"}/><p>未识别的供应商字段可在原始 JSON 中查看。</p></> : null}
        {tab === "integrity" ? <><h3>供应商返回的用量、结束原因和错误</h3><Value value={integrity?.metadata.length ? integrity.metadata : "未提供"}/><h3>状态与完整性</h3><Value value={{ status: selected.status ?? "未提供", outcome: selected.outcome === null ? "outcome=null：尚未记录到输出，不能判断为运行中" : "已记录",  request_complete: selected.request?.complete ?? "未提供", outcome_complete: selected.outcome?.complete ?? "未提供", boundary: selected.outcome?.boundary ?? selected.request?.boundary ?? "未提供", truncated: outcome.capture_truncated ?? outcome.truncated ?? request.capture_truncated ?? request.truncated ?? "未提供", redacted_paths: { request: selected.request?.redacted_paths ?? "未提供", outcome: selected.outcome?.redacted_paths ?? "未提供" } }}/><p>incomplete 表示记录不完整，不等于正在生成。缺失或截断的内容无法由页面还原。</p><p>completed 仅表示模型调用完成，不代表结构化校验或 Workflow 成功。</p></> : null}
        {tab === "raw" ? <RawCallJson key={selected.call_id} request={selected.request} outcome={selected.outcome} /> : null}
      </div></>}</section>
    </div>
  </main>;
}
