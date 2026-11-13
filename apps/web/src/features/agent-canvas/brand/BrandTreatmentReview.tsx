import { useTranslation } from "../../../i18n/useTranslation";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { agentCanvasApi } from "../../../api/agentCanvasApi";
import { ChevronRightIcon, CloseIcon, ConfirmIcon, DocumentIcon, EditIcon, SyncIcon } from "../../../icons.tsx";
import type { BrandDecisionPanelV1, BrandTreatmentStepResultV1 } from "./brandDecisions";
import { TreatmentSections } from "./TreatmentSections";
import { TreatmentDocumentView } from "./TreatmentDocumentView";
import { TreatmentStepEditor } from "./TreatmentStepEditor";
import { TREATMENT_STEP_LABELS } from "./treatmentStepLabels";
import "./brand-treatment-review.css";

const STEP_ORDER = ["hook", "story", "character", "scene", "visual", "camera", "editing", "sound"] as const;
const REVIEW_LOAD_TIMEOUT_MS = 15_000;
type ReviewSection = "overview" | "foundation" | "execution" | typeof STEP_ORDER[number];

export function BrandTreatmentReview({ workflowId, responseLocale = "en-US", onClose, onConfirmed, onProductionRefresh }: {
  workflowId: string; responseLocale?: string; onClose: () => void; onConfirmed: () => void | Promise<void>; onProductionRefresh?: () => void | Promise<void>;
}) {
  const t = useTranslation(responseLocale);
  const headingId = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const mounted = useRef(false);
  const inFlight = useRef(false);
  const loadController = useRef<AbortController | null>(null);
  const [panel, setPanel] = useState<BrandDecisionPanelV1 | null>(null);
  const [pendingAction, setPendingAction] = useState<"loading" | "confirming" | null>(null);
  const pending = pendingAction !== null;
  const confirming = pendingAction === "confirming";
  const [error, setError] = useState("");
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const [locked, setLocked] = useState(false);
  const [editing, setEditing] = useState<BrandTreatmentStepResultV1 | null>(null);
  const [activeSection, setActiveSection] = useState<ReviewSection>("overview");
  async function refresh() {
    if (inFlight.current) return;
    inFlight.current = true; setPendingAction("loading");
    const controller = new AbortController();
    loadController.current = controller;
    const timeout = window.setTimeout(() => {
      controller.abort(new DOMException("Review loading timed out.", "TimeoutError"));
    }, REVIEW_LOAD_TIMEOUT_MS);
    try {
      const next = await Promise.race([
        agentCanvasApi.brandDecisions(workflowId, { signal: controller.signal }),
        new Promise<never>((_, reject) => {
          controller.signal.addEventListener("abort", () => reject(controller.signal.reason), { once: true });
        }),
      ]);
      if (mounted.current && loadController.current === controller) {
        setPanel(next); setNeedsRefresh(false); setError(""); setEditing(null);
      }
    } catch {
      if (mounted.current && loadController.current === controller) {
        setNeedsRefresh(true);
        setError(controller.signal.reason?.name === "TimeoutError"
          ? t("Loading the final review timed out. Reload and try again.")
          : t("Cannot load the final review. Reload and try again."));
      }
    } finally {
      window.clearTimeout(timeout);
      if (loadController.current === controller) {
        loadController.current = null;
        inFlight.current = false;
        if (mounted.current) setPendingAction(null);
      }
    }
  }
  useEffect(() => {
    mounted.current = true;
    const element = dialog.current;
    const opener = window.document.activeElement;
    if (element && !element.open) element.showModal();
    void refresh();
    return () => {
      mounted.current = false;
      loadController.current?.abort();
      loadController.current = null;
      inFlight.current = false;
      element?.close();
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
    // This dialog is keyed by workflow; opening it always loads a fresh snapshot.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const document = panel?.treatment_document;
  const steps = document?.treatment_steps ?? panel?.treatment_steps ?? [];
  const orderedSteps = STEP_ORDER.flatMap(key => steps.filter(step => step.step_key === key));
  const activeStep = orderedSteps.find(step => step.step_key === activeSection);
  const isLocked = locked || Boolean(panel?.treatment_locked);
  const complete = document?.complete === true && document.missing_sections.length === 0;
  const campaignValues = document?.campaign_brief.values ?? [];
  const product = document?.brand_profile.values.find(value => value.slot_id === "brand_product_identity")?.value;
  const projectFacts = [product, ...["campaign_duration", "campaign_aspect_ratio"].map(key => campaignValues.find(value => value.slot_id === key)?.value)].filter(Boolean);
  function navigate(section: ReviewSection) {
    if (editing) return;
    setActiveSection(section);
    if (content.current) content.current.scrollTop = 0;
  }
  const canConfirm = document?.complete === true && document.missing_sections.length === 0
    && /^[a-f0-9]{64}$/.test(document.content_digest) && !panel?.treatment_locked && !needsRefresh && !editing && !locked;
  async function confirm() {
    if (!canConfirm || !document || inFlight.current) return;
    inFlight.current = true; setPendingAction("confirming"); setError("");
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
    } finally { inFlight.current = false; if (mounted.current) setPendingAction(null); }
  }
  return createPortal(
    <dialog ref={dialog} className="brand-treatment-review" aria-labelledby={headingId}
      onCancel={event => { event.preventDefault(); if (!confirming && !editing) onClose(); }}>
      <header className="treatment-review__header">
        <div className="treatment-review__identity">
          <span className="treatment-review__document-mark" aria-hidden="true"><DocumentIcon /></span>
          <div>
            <h2 id={headingId}>{t("Final treatment review")}</h2>
            <p>{projectFacts.length ? projectFacts.join(" · ") : t("Review the direction and details before production.")}</p>
          </div>
        </div>
        <div className="treatment-review__header-actions">
          {panel && <span className={`treatment-review__status${complete ? " is-complete" : ""}`}>
            {complete ? <ConfirmIcon /> : <span className="treatment-review__status-dot" />}
            {t(isLocked ? "Locked" : complete ? "Treatment is complete" : "Treatment is incomplete")}
          </span>}
          <button className="treatment-review__icon-button" type="button" aria-label={t("Reload review")} title={t("Reload review")}
            disabled={pending || !!editing || isLocked} onClick={() => void refresh()}><SyncIcon /></button>
          <button className="treatment-review__icon-button" type="button" aria-label={t("Close")} title={t("Close")}
            disabled={confirming || !!editing} onClick={onClose}><CloseIcon /></button>
        </div>
      </header>
      <div className="treatment-review__workspace">
        <nav className="treatment-review__navigation" aria-label={t("Review contents")}>
          <p className="treatment-review__nav-caption">{t("Review contents")}</p>
          <button type="button" className="treatment-review__nav-item" aria-current={activeSection === "overview" ? "page" : undefined}
            disabled={!!editing} onClick={() => navigate("overview")}><DocumentIcon /><span>{t("Treatment overview")}</span></button>
          <div className="treatment-review__nav-group-label"><span>{t("Eight creative steps")}</span><span>{orderedSteps.length} / 8</span></div>
          <div className="treatment-review__step-navigation">
            {STEP_ORDER.map((key, index) => {
              const step = orderedSteps.find(item => item.step_key === key);
              return <button type="button" key={key} className="treatment-review__nav-item treatment-review__nav-step"
                aria-current={activeSection === key ? "page" : undefined} disabled={!step || !!editing} onClick={() => navigate(key)}>
                <span className="treatment-review__step-number">{String(index + 1).padStart(2, "0")}</span>
                <span><strong>{t(TREATMENT_STEP_LABELS[key]!)}</strong><small>{step?.selected_label ?? t("Not provided")}</small></span>
              </button>;
            })}
          </div>
          <div className="treatment-review__nav-secondary">
            <button type="button" className="treatment-review__nav-item" aria-current={activeSection === "foundation" ? "page" : undefined}
              disabled={!document || !!editing} onClick={() => navigate("foundation")}><span>{t("Brand and campaign")}</span><ChevronRightIcon /></button>
            <button type="button" className="treatment-review__nav-item" aria-current={activeSection === "execution" ? "page" : undefined}
              disabled={!document || !!editing} onClick={() => navigate("execution")}><span>{t("Production notes")}</span><ChevronRightIcon /></button>
          </div>
        </nav>
        <div ref={content} className="treatment-review__content" aria-busy={pending}>
          {error && <div className="treatment-review__notice is-error" role="alert">{error}</div>}
          {!panel ? <div className="treatment-review__empty" role="status"><DocumentIcon /><p>{pending ? t("Loading…") : t("Load the treatment before reviewing it.")}</p></div> : <>
            {!document && <div className="treatment-review__notice">{t("This history has no complete review document, so it cannot be locked.")}</div>}
            {document && document.missing_sections.length > 0 && <div className="treatment-review__notice">{t("Missing content: {items}", { items: document.missing_sections.join("、") })}</div>}
            {activeSection === "overview" && <>
              {document && <TreatmentDocumentView document={document} view="overview" responseLocale={responseLocale} />}
              <section className="treatment-review__direction-map" aria-label={t("Eight creative steps")}>
                <div className="treatment-review__section-heading"><h3>{t("Eight creative steps")}</h3><span>{t("Select a step to review or edit")}</span></div>
                <div className="treatment-review__direction-grid">
                  {orderedSteps.map(step => <button type="button" key={step.step_key} className="treatment-review__direction" onClick={() => navigate(step.step_key)}>
                    <span className="treatment-review__direction-index">{String(STEP_ORDER.indexOf(step.step_key) + 1).padStart(2, "0")}</span>
                    <span><small>{t(TREATMENT_STEP_LABELS[step.step_key]!)}</small><strong>{step.selected_label}</strong></span>
                    <ChevronRightIcon />
                  </button>)}
                </div>
              </section>
            </>}
            {document && (activeSection === "foundation" || activeSection === "execution") &&
              <TreatmentDocumentView document={document} view={activeSection} responseLocale={responseLocale} />}
            {activeStep && <article className="treatment-review__step" aria-label={t(TREATMENT_STEP_LABELS[activeStep.step_key]!)}>
              <div className="treatment-review__chapter-line"><span>{String(STEP_ORDER.indexOf(activeStep.step_key) + 1).padStart(2, "0")} / 08</span><span>{t(TREATMENT_STEP_LABELS[activeStep.step_key]!)}</span></div>
              <div className="treatment-review__step-heading">
                <h3>{activeStep.selected_label}</h3>
                {!editing && !isLocked && <button type="button" className="treatment-review__secondary-button" disabled={pending || needsRefresh} onClick={() => setEditing(activeStep)}><EditIcon />{t("Edit this step")}</button>}
              </div>
              {editing ? <TreatmentStepEditor key={editing.step_key} step={editing} panel={panel} responseLocale={responseLocale}
                onCancel={() => setEditing(null)} onSaved={next => { setPanel(next); setNeedsRefresh(false); setEditing(null); }} />
                : <div className="treatment-review__step-copy"><TreatmentSections detail={activeStep.structured_detail} />
                  {!activeStep.structured_detail && <p>{activeStep.detail || t("This historical step has no complete detail. Edit it to fill in the missing content.")}</p>}
                </div>}
            </article>}
          </>}
        </div>
      </div>
      <footer className="treatment-review__footer">
        <p>{t(editing ? "Save or cancel your edits before confirming." : isLocked ? "Treatment is locked and read-only." : "Confirming locks this version and continues to production.")}</p>
        <div>
          <button type="button" className="treatment-review__secondary-button" disabled={confirming || !!editing} onClick={onClose}>{t("Review later")}</button>
          <button type="button" className="treatment-review__confirm" disabled={!canConfirm || pending} onClick={() => void confirm()}>
            {pendingAction === "confirming" ? t("Confirming…") : t("Confirm and lock treatment")}<ChevronRightIcon />
          </button>
        </div>
      </footer>
    </dialog>, window.document.body,
  );
}
