import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { v2Api } from "../api/v2Client";
import type { WorkflowNodeV2 } from "../types-v2";
import { useCallHistory } from "../features/model-call-history/useCallHistory";
import { callIntegrity } from "../features/model-call-history/callIntegrity";
import { RawCallJson } from "../features/model-call-history/RawCallJson";
import { extractOutput, jsonText, payload, type AgentModelCallSummary } from "../features/agent-model-call-history";
import "./workflow-model-call-history.css";

type Tab = "input" | "output" | "draft" | "integrity" | "raw";
const tabs: Array<[Tab, string, string]> = [
  ["input", "Agent 输入", "模型实际收到的创作上下文"],
  ["output", "Agent 原始输出", "模型返回的原文与结构化结果"],
  ["draft", "草稿 Prompt", "输出中可写入草稿节点的 Prompt"],
  ["integrity", "诊断", "状态、错误和记录完整性"],
  ["raw", "原始 JSON", "完整底层记录"],
];
function Value({ value }: { value: unknown }) { return <pre className="llm-call-history__value">{typeof value === "string" ? value : jsonText(value)}</pre>; }
function Disclosure({ title, children }: { title: string; children: ReactNode }) {
  return <details className="llm-call-history__disclosure"><summary>{title}</summary>{children}</details>;
}
function persistedPromptRows(nodes: WorkflowNodeV2[]) {
  return nodes.flatMap((node) => (node.items ?? []).flatMap((item) => {
    const rows: Array<{ key: string; title: string; value: string }> = [];
    if (item.item_prompt?.trim()) rows.push({ key: `${node.node_id}:${item.item_id}:item`, title: `${node.title} / ${item.display_name} · item_prompt`, value: item.item_prompt });
    if (item.shot_summary_prompt?.trim()) rows.push({ key: `${node.node_id}:${item.item_id}:summary`, title: `${node.title} / ${item.display_name} · shot_summary_prompt`, value: item.shot_summary_prompt });
    (item.slots ?? []).forEach((slot) => {
      if (slot.slot_prompt?.trim()) rows.push({ key: `${node.node_id}:${item.item_id}:${slot.slot_id}:slot`, title: `${node.title} / ${slot.slot_type} · slot_prompt`, value: slot.slot_prompt });
      if (slot.system_suggested_prompt?.trim()) rows.push({ key: `${node.node_id}:${item.item_id}:${slot.slot_id}:system`, title: `${node.title} / ${slot.slot_type} · system_suggested_prompt`, value: slot.system_suggested_prompt });
      if (slot.user_prompt?.trim()) rows.push({ key: `${node.node_id}:${item.item_id}:${slot.slot_id}:user`, title: `${node.title} / ${slot.slot_type} · user_prompt`, value: slot.user_prompt });
    });
    return rows;
  }));
}

export function WorkflowModelCallHistoryPage() {
  const { workflowId = "" } = useParams<{ workflowId: string }>();
  return <WorkflowCallHistory key={workflowId} workflowId={workflowId} />;
}

function WorkflowCallHistory({ workflowId }: { workflowId: string }) {
  const { items, selected, loading, detailLoading, error, detailError, cooldown,
    canPrevious, canNext, refresh, previous, next, select } = useCallHistory(workflowId);
  const [tab, setTab] = useState<Tab>("input");
  const [workflowNodes, setWorkflowNodes] = useState<WorkflowNodeV2[]>([]);
  const [workflowReadError, setWorkflowReadError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    setWorkflowNodes([]);
    setWorkflowReadError(null);
    if (!workflowId) return () => { active = false; };
    void v2Api.workflow(workflowId).then((workflow) => {
      if (active) setWorkflowNodes(workflow.nodes);
    }).catch(() => {
      if (active) setWorkflowReadError("Workflow 草稿节点暂时无法读取；Agent 输出仍可正常查看。");
    });
    return () => { active = false; };
  }, [workflowId]);
  function selectCall(call: AgentModelCallSummary) {
    setTab("input");
    void select(call.call_id);
  }
  const request = payload(selected?.request);
  const outcome = payload(selected?.outcome);
  const integrity = useMemo(() => selected ? callIntegrity(selected) : null, [selected]);
  const output = useMemo(() => extractOutput(selected?.outcome), [selected]);
  const savedPromptRows = useMemo(() => persistedPromptRows(workflowNodes), [workflowNodes]);
  return <main className="llm-call-history" aria-label="LLM 调用记录">
    <header className="llm-call-history__header"><button type="button" onClick={() => window.close()}>关闭日志页</button><div><span className="eyebrow">READ-ONLY LOG</span><h1>LLM 调用记录</h1></div><button type="button" onClick={() => void refresh()} disabled={loading || cooldown}>刷新</button></header>
    <div className="llm-call-history__layout">
      <section className="llm-call-history__list" aria-label="调用列表"><div className="llm-call-history__list-head"><span>{loading ? "读取中…" : `${items.length} 条记录`}</span><span>仅展示已有记录</span></div>{!loading && !error && items.length === 0 ? <p>暂无已记录的调用。</p> : null}{error ? <p className="llm-call-history__error" role="alert">{error}</p> : null}{items.map((call) => <button className={`llm-call-row${selected?.call_id === call.call_id ? " is-selected" : ""}`} key={call.call_id} type="button" disabled={detailLoading} onClick={() => void selectCall(call)}><small>call {call.call_id}</small><strong>{call.operation_name ?? "未命名操作"}</strong><span>{({ initial: "首次调用", transport_retry: "传输重试", structured_repair: "结构化修复", capability_fallback: "能力回退" } as Record<string, string>)[call.stage ?? ""] ?? call.stage ?? "未提供"} · {call.status ?? "未提供"}</span><small>{call.created_at ?? "未提供"} · run {call.run_id ?? "未提供"}</small></button>)}<nav className="llm-call-history__pagination"><button type="button" disabled={!canPrevious || loading || cooldown} onClick={() => void previous()}>上一页</button><button type="button" disabled={!canNext || loading || cooldown} onClick={() => void next()}>下一页</button></nav></section>
      <section className="llm-call-history__detail" aria-live="polite">{detailLoading ? <p>读取详情…</p> : detailError ? <p className="llm-call-history__error" role="alert">{detailError}</p> : !selected ? <p className="llm-call-history__empty">选择一条记录查看详情。详情不会随列表批量读取。</p> : <><div className="llm-call-history__summary"><div><span className="eyebrow">{selected.call_id}</span><h2>{selected.operation_name ?? "未命名操作"}</h2></div><span className={`status status--${selected.status ?? "unknown"}`}>{selected.status ?? "未提供"}</span></div><div role="status">{integrity?.notices.map(notice => <p key={notice}>{notice}</p>)}</div><div className="llm-call-tabs">{tabs.map(([id, label, description]) => <button type="button" className={tab === id ? "is-active" : ""} key={id} title={description} aria-label={`${label}：${description}`} onClick={() => setTab(id)}>{label}</button>)}</div><div className="llm-call-content">
        {tab === "input" ? <>
          <div className="llm-call-history__focus-note"><strong>先看这两项</strong><span>用户提示词决定 Agent 看到了什么；角色规则决定 Agent 应该怎么创作。</span></div>
          <h3>用户提示词 / 创作上下文</h3><Value value={request.user_prompt ?? request.user ?? "未提供"}/>
          <Disclosure title="角色规则（system prompt）"><Value value={request.system_prompt ?? request.system ?? "未提供"}/></Disclosure>
          <Disclosure title="已加载的 Skills"><Value value={request.loaded_skills ?? request.skills ?? "未提供"}/></Disclosure>
          <Disclosure title="完整上下文与输出 Schema"><Value value={{ context: request.context ?? request.agent_request ?? "未提供", output_schema: request.output_schema ?? "未提供" }}/></Disclosure>
          <Disclosure title="模型与执行参数"><Value value={{ model: request.model_ref ?? request.model ?? "未提供", provider: request.provider ?? "未提供", execution_policy: request.execution_policy ?? "未提供" }}/></Disclosure>
        </> : null}
        {tab === "output" ? <>
          <div className="llm-call-history__focus-note"><strong>重点看模型原话</strong><span>这里是 Agent 实际返回的创作内容；不要先看外层 response 元数据。</span></div>
          <h3>模型返回文本</h3><Value value={output.text ?? "未提供"}/><p>{output.partial ? "提示：输出包含流式片段或部分输出。" : ""}</p>
          <h3>解析后的结构化结果</h3><Value value={output.structured ?? "未提供"}/>
          {output.tools ? <Disclosure title="工具调用"><Value value={output.tools}/></Disclosure> : null}
          {output.streams ? <Disclosure title="流式片段 / 事件"><Value value={output.streams}/></Disclosure> : null}
        </> : null}
        {tab === "draft" ? <>
          <div className="llm-call-history__focus-note"><strong>用于优化草稿节点 Prompt</strong><span>先比较 Agent 原始输出和下面这些 Prompt 字段，判断问题发生在创作还是节点物化。</span></div>
          {Object.keys(output.draftPrompts).length ? <>
            <h3>从 Agent 输出中识别出的草稿 Prompt</h3>
            <div className="llm-call-history__prompt-grid">{Object.entries(output.draftPrompts).map(([key, value]) => <section key={key}><h4>{key}</h4><Value value={value}/></section>)}</div>
          </> : <p className="llm-call-history__empty-panel">这次调用没有返回草稿 Prompt 字段。它可能只是流程路由、品牌提问或结构化决策；请回到“Agent 原始输出”确认。</p>}
          <h3>Workflow 当前实际保存的草稿 Prompt</h3>
          {workflowReadError ? <p className="llm-call-history__empty-panel">{workflowReadError}</p> : savedPromptRows.length ? <div className="llm-call-history__prompt-grid">{savedPromptRows.map((row) => <section key={row.key}><h4>{row.title}</h4><Value value={row.value}/></section>)}</div> : <p className="llm-call-history__empty-panel">当前 Workflow 没有已保存的草稿 Prompt。</p>}
          <Disclosure title="实际请求体（用于核对最终消息）"><Value value={request.provider_request ?? request.request_body ?? "未提供"}/></Disclosure>
        </> : null}
        {tab === "integrity" ? <><h3>状态与完整性</h3><Value value={{ status: selected.status ?? "未提供", outcome: selected.outcome === null ? "outcome=null：尚未记录到输出，不能判断为运行中" : "已记录", request_complete: selected.request?.complete ?? "未提供", outcome_complete: selected.outcome?.complete ?? "未提供", boundary: selected.outcome?.boundary ?? selected.request?.boundary ?? "未提供", truncated: outcome.capture_truncated ?? outcome.truncated ?? request.capture_truncated ?? request.truncated ?? "未提供", redacted_paths: { request: selected.request?.redacted_paths ?? "未提供", outcome: selected.outcome?.redacted_paths ?? "未提供" } }}/><h3>供应商用量、结束原因和错误</h3><Value value={integrity?.metadata.length ? integrity.metadata : "未提供"}/><p>incomplete 表示记录不完整，不等于正在生成。completed 仅表示模型调用完成，不代表结构化校验或 Workflow 成功。</p></> : null}
        {tab === "raw" ? <RawCallJson key={selected.call_id} request={selected.request} outcome={selected.outcome} /> : null}
      </div></>}</section>
    </div>
  </main>;
}
