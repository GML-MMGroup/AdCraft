import { useTranslation } from "../../i18n/useTranslation";
import { useMemo } from "react";
import { v2Api } from "../../api/v2Client";
import type { WorkflowNodeV2 } from "../../types-v2";
import { useCallHistory } from "./useCallHistory";
import { CallDetail } from "./CallDetail";
import { callTime, operationPresentation, stageLabel, statusLabel } from "./callPresentation";
import { useUiLocale } from "../../i18n/locale";

export function WorkflowCallHistory({ workflowId, projectName }: { workflowId: string; projectName?: string }) {
  const t = useTranslation();
  const { items, selected, loading, detailLoading, error, detailError, cooldown,
    canPrevious, canNext, refresh, previous, next, select } = useCallHistory(workflowId, 200);
  const locale = useUiLocale();
  const runNumbers = new Map([...new Set(items.flatMap(call => call.run_id ? [call.run_id] : []))].map((id, index) => [id, index + 1]));
  // Read once on demand for this page, even when switching calls or tabs rapidly.
  // This promise lives only in memory and is discarded when the page closes.
  const readWorkflowNodes = useMemo(() => {
    let read: Promise<WorkflowNodeV2[]> | undefined;
    return () => read ??= v2Api.workflow(workflowId).then(workflow => workflow.nodes);
  }, [workflowId]);
  return <section className="llm-call-history__workspace" aria-label={t("LLM call history")}>
    <header className="llm-call-history__header">
      <div><span className="llm-call-history__eyebrow">{t("CALL HISTORY / Read-only records")}</span><h1>{projectName || t("Workflow call history")}</h1><p className="llm-call-history__workflow-id">{workflowId}</p></div>
      <div className="llm-call-history__actions"><button type="button" onClick={() => void refresh()} disabled={loading || cooldown}>{loading ? t("Reading…") : t("Refresh records")}</button></div>
    </header>
    <div className="llm-call-history__layout">
      <section className="llm-call-history__list" aria-label={t("Call list")}>
        <div className="llm-call-history__list-head"><strong>{t("Call list")}</strong><span>{loading ? t("Reading…") : (locale.toLowerCase().startsWith("en") ? `${items.length} calls on this page` : `本页 ${items.length} 条`)}</span></div>
        <p className="llm-call-history__list-help">{t("Calls with the same group ID belong to one Agent operation. Retries and repairs remain separate.")}</p>
        {!loading && !error && !items.length ? <p className="llm-call-history__empty-panel">{t("No recorded calls.")}</p> : null}
        {error ? <p className="llm-call-history__error" role="alert">{error}</p> : null}
        <div className="llm-call-history__rows">{items.map(call => <button className={`llm-call-row${selected?.call_id === call.call_id ? " is-selected" : ""}`} key={call.call_id} type="button" disabled={detailLoading || loading} aria-pressed={selected?.call_id === call.call_id} onClick={() => void select(call.call_id)}>
          <span className="llm-call-row__top"><time dateTime={call.created_at ?? undefined}>{callTime(call.created_at, locale)}</time><span className={`llm-call-history__status llm-call-history__status--${call.status}`}>{statusLabel(call.status, locale)}</span></span>
          <strong>{operationPresentation(call.operation_name, locale).title}</strong>
          <span>{stageLabel(call.stage, locale)}<span className="llm-call-row__group">{call.run_id ? `${locale.toLowerCase().startsWith("en") ? "Group" : "本页第"} ${runNumbers.get(call.run_id)}${locale.toLowerCase().startsWith("en") ? "" : " 组"}` : t("Operation not provided")}</span></span>
        </button>)}</div>
        <nav className="llm-call-history__pagination" aria-label={t("Call list pagination")}><button type="button" disabled={!canPrevious || loading || cooldown} onClick={() => void previous()}>{t("Previous page")}</button><button type="button" disabled={!canNext || loading || cooldown} onClick={() => void next()}>{t("Next page")}</button></nav>
      </section>
      <section className="llm-call-history__detail" aria-label={t("Call details")} aria-busy={detailLoading}>
        {detailLoading ? <p role="status" className="llm-call-history__empty">{t("Reading this call…")}</p> : detailError ? <p className="llm-call-history__error" role="alert">{detailError}</p> : selected ? <CallDetail key={selected.call_id} call={selected} readWorkflowNodes={readWorkflowNodes}/> : <div className="llm-call-history__empty"><span className="llm-call-history__eyebrow">INPUT → MODEL → OUTPUT</span><h2>{t("Start with a call")}</h2><p>{locale.toLowerCase().startsWith("en") ? "Select a record on the left to see what the model received and returned. Expand parameters and raw records when investigating." : "选择左侧记录，先看模型收到什么、返回什么。需要排查时，再展开参数和原始记录。"}</p><small>{t("Details load only when clicked; refresh only updates logs.")}</small></div>}
      </section>
    </div>
  </section>;
}
