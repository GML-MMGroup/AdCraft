import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { agentCanvasApi } from "../../../api/agentCanvasApi";
import type { BrandDecisionPanelV1, BrandTreatmentStepResultV1 } from "./brandDecisions";
import { TreatmentSections } from "./TreatmentSections";
import { TreatmentDocumentView } from "./TreatmentDocumentView";
import { TreatmentStepEditor } from "./TreatmentStepEditor";
import "./brand-treatment-review.css";

export function BrandTreatmentReview({ workflowId, onClose, onConfirmed, onProductionRefresh }: {
  workflowId: string; onClose: () => void; onConfirmed: () => void | Promise<void>; onProductionRefresh?: () => void | Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const mounted = useRef(false);
  const inFlight = useRef(false);
  const [panel, setPanel] = useState<BrandDecisionPanelV1 | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const [locked, setLocked] = useState(false);
  const [editing, setEditing] = useState<BrandTreatmentStepResultV1 | null>(null);
  async function refresh() {
    if (inFlight.current) return;
    inFlight.current = true; setPending(true);
    try {
      const next = await agentCanvasApi.brandDecisions(workflowId);
      if (mounted.current) { setPanel(next); setNeedsRefresh(false); setError(""); setEditing(null); }
    } catch { if (mounted.current) setError("无法加载最终审阅，请重新加载。"); }
    finally { inFlight.current = false; if (mounted.current) setPending(false); }
  }
  useEffect(() => {
    mounted.current = true;
    dialog.current?.showModal();
    void refresh();
    return () => { mounted.current = false; };
    // This dialog is keyed by workflow; opening it always loads a fresh snapshot.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const document = panel?.treatment_document;
  const canConfirm = document?.complete === true && document.missing_sections.length === 0
    && /^[a-f0-9]{64}$/.test(document.content_digest) && !panel?.treatment_locked && !needsRefresh && !editing && !locked;
  async function confirm() {
    if (!canConfirm || !document || inFlight.current) return;
    inFlight.current = true; setPending(true); setError("");
    try {
      await agentCanvasApi.brandLockTreatment(workflowId, document.content_digest);
      if (!mounted.current) return;
      setLocked(true);
      try { await onConfirmed(); onClose(); }
      catch { if (mounted.current) setError("方案已锁定，刷新工作区失败。请关闭审阅后刷新页面，不要重新提交方案。"); }
    } catch (cause) {
      if (!mounted.current) return;
      const code = cause && typeof cause === "object" && "code" in cause ? String(cause.code) : "";
      if (["brand_context_stale","brand_treatment_review_required","brand_stage_action_mismatch","brand_treatment_incomplete"].includes(code)) {
        setNeedsRefresh(true);
        setError("内容已改变、未完整或阶段已变化。请重新加载并审阅后再确认。");
      } else {
        if (code === "requirement_revision_conflict") {
          try { await onProductionRefresh?.(); } catch { /* Keep the frozen review for a manual retry. */ }
        }
        setError(code === "requirement_revision_conflict"
          ? "生产状态版本冲突，已尝试刷新。请恢复后重试；当前审阅及 digest 已保留。"
          : "确认或生产交接暂未完成。当前审阅已保留，可恢复后重试相同版本。");
      }
    } finally { inFlight.current = false; if (mounted.current) setPending(false); }
  }
  return createPortal(<dialog ref={dialog} className="brand-treatment-review" aria-label="最终创意方案审阅"
    onCancel={event => { event.preventDefault(); if (!pending && !editing) onClose(); }}>
    <header><h2>最终创意方案审阅</h2><button type="button" disabled={pending || !!editing} onClick={onClose}>关闭</button></header>
    {error && <p role="alert">{error}</p>}
    <button type="button" disabled={pending || !!editing || locked} onClick={() => void refresh()}>重新加载审阅</button>
    {!panel ? <p>{pending ? "正在加载…" : "请加载方案后审阅。"}</p> : <>
      {!document && <p>此历史记录没有完整审阅文档，不能执行新的锁定。</p>}
      {document && <><p>{document.complete ? "方案内容完整" : "方案尚不完整"}</p>
        {document.missing_sections.length > 0 && <p>缺失内容：{document.missing_sections.join("、")}</p>}
        <TreatmentDocumentView document={document}/></>}
      <section><h3>八项创意步骤</h3>{(document?.treatment_steps ?? panel.treatment_steps).map(step => <article key={step.step_key}>
        <h4>{step.selected_label}</h4>
        {editing?.step_key === step.step_key ? <TreatmentStepEditor step={editing} panel={panel}
          onCancel={() => setEditing(null)} onSaved={next => { setPanel(next); setNeedsRefresh(false); setEditing(null); }}/>
          : <><TreatmentSections detail={step.structured_detail}/>{!step.structured_detail && <p>{step.detail || "历史步骤没有完整段落，请显式编辑补齐。"}</p>}
            {!panel.treatment_locked && !locked && <button type="button" disabled={pending || !!editing || needsRefresh} onClick={() => setEditing(step)}>编辑此步骤</button>}</>}
      </article>)}</section>
      {panel.treatment_locked && <p>此方案已锁定，内容只读。</p>}
      <button type="button" disabled={!canConfirm || pending} onClick={() => void confirm()}>{pending ? "正在确认…" : "确认并锁定创意方案"}</button>
    </>}
  </dialog>, window.document.body);
}
