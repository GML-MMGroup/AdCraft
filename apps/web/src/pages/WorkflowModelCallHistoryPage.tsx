import { useMemo } from "react";
import { useParams } from "react-router-dom";
import { v2Api } from "../api/v2Client";
import type { WorkflowNodeV2 } from "../types-v2";
import { useCallHistory } from "../features/model-call-history/useCallHistory";
import { CallDetail } from "../features/model-call-history/CallDetail";
import { callTime, operationPresentation, stageLabel, statusLabel } from "../features/model-call-history/callPresentation";
import "./workflow-model-call-history.css";

export function WorkflowModelCallHistoryPage() {
  const { workflowId = "" } = useParams<{ workflowId: string }>();
  return <WorkflowCallHistory key={workflowId} workflowId={workflowId}/>;
}

function WorkflowCallHistory({ workflowId }: { workflowId: string }) {
  const { items, selected, loading, detailLoading, error, detailError, cooldown,
    canPrevious, canNext, refresh, previous, next, select } = useCallHistory(workflowId);
  const runNumbers = new Map([...new Set(items.flatMap(call => call.run_id ? [call.run_id] : []))].map((id, index) => [id, index + 1]));
  // Read once on demand for this page, even when switching calls or tabs rapidly.
  // This promise lives only in memory and is discarded when the page closes.
  const readWorkflowNodes = useMemo(() => {
    let read: Promise<WorkflowNodeV2[]> | undefined;
    return () => read ??= v2Api.workflow(workflowId).then(workflow => workflow.nodes);
  }, [workflowId]);
  return <main className="llm-call-history" aria-label="LLM 调用记录">
    <header className="llm-call-history__header">
      <div><span className="llm-call-history__eyebrow">CALL HISTORY / 只读记录</span><h1>模型调用记录</h1><p>查看每次调用的输入、回复和问题原因。</p></div>
      <div className="llm-call-history__actions"><button type="button" onClick={() => void refresh()} disabled={loading || cooldown}>{loading ? "读取中…" : "刷新记录"}</button><button type="button" onClick={() => window.close()}>关闭日志页</button></div>
    </header>
    <div className="llm-call-history__layout">
      <section className="llm-call-history__list" aria-label="调用列表">
        <div className="llm-call-history__list-head"><strong>调用列表</strong><span>{loading ? "读取中…" : `本页 ${items.length} 条`}</span></div>
        <p className="llm-call-history__list-help">本页组号相同，表示同一次 Agent 操作。重试与修复分别保留。</p>
        {!loading && !error && !items.length ? <p className="llm-call-history__empty-panel">暂无已记录的调用。</p> : null}
        {error ? <p className="llm-call-history__error" role="alert">{error}</p> : null}
        <div className="llm-call-history__rows">{items.map(call => <button className={`llm-call-row${selected?.call_id === call.call_id ? " is-selected" : ""}`} key={call.call_id} type="button" disabled={detailLoading || loading} aria-pressed={selected?.call_id === call.call_id} onClick={() => void select(call.call_id)}>
          <span className="llm-call-row__top"><time dateTime={call.created_at ?? undefined}>{callTime(call.created_at)}</time><span className={`llm-call-history__status llm-call-history__status--${call.status}`}>{statusLabel(call.status)}</span></span>
          <strong>{operationPresentation(call.operation_name).title}</strong>
          <span>{stageLabel(call.stage)}<span className="llm-call-row__group">{call.run_id ? `本页第 ${runNumbers.get(call.run_id)} 组` : "未提供关联操作"}</span></span>
        </button>)}</div>
        <nav className="llm-call-history__pagination" aria-label="调用列表分页"><button type="button" disabled={!canPrevious || loading || cooldown} onClick={() => void previous()}>上一页</button><button type="button" disabled={!canNext || loading || cooldown} onClick={() => void next()}>下一页</button></nav>
      </section>
      <section className="llm-call-history__detail" aria-label="调用详情" aria-busy={detailLoading}>
        {detailLoading ? <p role="status" className="llm-call-history__empty">正在读取这次调用…</p> : detailError ? <p className="llm-call-history__error" role="alert">{detailError}</p> : selected ? <CallDetail key={selected.call_id} call={selected} readWorkflowNodes={readWorkflowNodes}/> : <div className="llm-call-history__empty"><span className="llm-call-history__eyebrow">INPUT → MODEL → OUTPUT</span><h2>从一次调用开始看</h2><p>选择左侧记录，先看模型收到什么、返回什么。<br/>需要排查时，再展开参数和原始记录。</p><small>点击才读取详情，刷新只更新日志。</small></div>}
      </section>
    </div>
  </main>;
}
