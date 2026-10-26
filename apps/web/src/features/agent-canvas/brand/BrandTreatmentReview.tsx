import { useTranslation } from "../../../i18n/useTranslation";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { agentCanvasApi } from "../../../api/agentCanvasApi";
import type { BrandDecisionPanelV1, BrandTreatmentStepResultV1 } from "./brandDecisions";
import { TreatmentSections } from "./TreatmentSections";
import { TreatmentDocumentView } from "./TreatmentDocumentView";
import { TreatmentStepEditor } from "./TreatmentStepEditor";
import "./brand-treatment-review.css";

export function BrandTreatmentReview({ workflowId, responseLocale = "en-US", onClose, onConfirmed, onProductionRefresh }: {
  workflowId: string; responseLocale?: string; onClose: () => void; onConfirmed: () => void | Promise<void>; onProductionRefresh?: () => void | Promise<void>;
}) {
  const t = useTranslation(responseLocale);
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
    } catch { if (mounted.current) setError(t("Cannot load the final review. Reload and try again.")); }
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
      catch { if (mounted.current) setError(t("The treatment is locked, but refreshing the workspace failed. Close the review and refresh the page; do not submit again.")); }
    } catch (cause) {
      if (!mounted.current) return;
      const code = cause && typeof cause === "object" && "code" in cause ? String(cause.code) : "";
      if (["brand_context_stale","brand_treatment_review_required","brand_stage_action_mismatch","brand_treatment_incomplete"].includes(code)) {
        setNeedsRefresh(true);
        setError(t("The content changed, is incomplete, or the stage changed. Reload and review it before confirming."));
      } else {
        if (code === "requirement_revision_conflict") {
          try { await onProductionRefresh?.(); } catch { /* Keep the frozen review for a manual retry. */ }
        }
        setError(code === "requirement_revision_conflict"
          ? t("Production state changed. Refresh was attempted; restore the state and retry. The current review and digest were kept.")
          : t("Confirmation or production handoff is not complete. The current review is kept; restore the state and retry the same version."));
      }
    } finally { inFlight.current = false; if (mounted.current) setPending(false); }
  }
  return createPortal(<dialog ref={dialog} className="brand-treatment-review" aria-label={t("Final treatment review")}
    onCancel={event => { event.preventDefault(); if (!pending && !editing) onClose(); }}>
    <header><h2>{t("Final treatment review")}</h2><button type="button" disabled={pending || !!editing} onClick={onClose}>{t("Close")}</button></header>
    {error && <p role="alert">{error}</p>}
    <button type="button" disabled={pending || !!editing || locked} onClick={() => void refresh()}>{t("Reload review")}</button>
    {!panel ? <p>{pending ? t("Loading…") : t("Load the treatment before reviewing it.")}</p> : <>
      {!document && <p>{t("This history has no complete review document, so it cannot be locked.")}</p>}
      {document && <><p>{document.complete ? t("Treatment is complete") : t("Treatment is incomplete")}</p>
        {document.missing_sections.length > 0 && <p>{t("Missing content: {items}", { items: document.missing_sections.join("、") })}</p>}
        <TreatmentDocumentView document={document} responseLocale={responseLocale}/></>}
      <section><h3>{t("Eight creative steps")}</h3>{(document?.treatment_steps ?? panel.treatment_steps).map(step => <article key={step.step_key}>
        <h4>{step.selected_label}</h4>
        {editing?.step_key === step.step_key ? <TreatmentStepEditor step={editing} panel={panel} responseLocale={responseLocale}
          onCancel={() => setEditing(null)} onSaved={next => { setPanel(next); setNeedsRefresh(false); setEditing(null); }}/>
          : <><TreatmentSections detail={step.structured_detail}/>{!step.structured_detail && <p>{step.detail || t("This historical step has no complete detail. Edit it to fill in the missing content.")}</p>}
            {!panel.treatment_locked && !locked && <button type="button" disabled={pending || !!editing || needsRefresh} onClick={() => setEditing(step)}>{t("Edit this step")}</button>}</>}
      </article>)}</section>
      {panel.treatment_locked && <p>{t("Treatment is locked and read-only.")}</p>}
      <button type="button" disabled={!canConfirm || pending} onClick={() => void confirm()}>{pending ? t("Confirming…") : t("Confirm and lock treatment")}</button>
    </>}
  </dialog>, window.document.body);
}
