import { useEffect, useRef, useState, type RefObject } from "react";
import { CloseIcon, DocumentIcon, HistoryIcon, SaveIcon } from "../../../../icons.tsx";
import { V2ScreenplaySceneEditor } from "./V2ScreenplaySceneEditor.tsx";
import { V2ScreenplayVersionHistory } from "./V2ScreenplayVersionHistory.tsx";
import type { V2ScreenplayController } from "./useV2ScreenplayController.ts";

type Props = {
  controller: V2ScreenplayController;
  returnFocusRef?: RefObject<HTMLElement | null>;
  returnFocusElement?: HTMLElement | null;
};

export function V2ScreenplayDrawer({ controller, returnFocusRef, returnFocusElement }: Props) {
  const { state } = controller;
  const [tab, setTab] = useState<"editor" | "history">("editor");
  const headingRef = useRef<HTMLHeadingElement>(null);
  const wasOpenRef = useRef(false);

  useEffect(() => {
    if (state.isOpen) {
      wasOpenRef.current = true;
      headingRef.current?.focus();
      return;
    }
    if (wasOpenRef.current) {
      wasOpenRef.current = false;
      (returnFocusElement ?? returnFocusRef?.current)?.focus();
    }
  }, [returnFocusElement, returnFocusRef, state.isOpen]);

  useEffect(() => {
    if (!state.isOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      controller.close();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [controller, state.isOpen]);

  if (!state.isOpen) return null;
  const errorViolations = requestViolations(state.requestError?.details);
  const onCloseRequest = () => controller.close();

  return <div className="v2-screenplay-drawer-backdrop">
    <aside className="v2-screenplay-drawer" role="dialog" aria-modal="true" aria-labelledby="v2-screenplay-drawer-title">
      <header className="v2-screenplay-drawer__header">
        <div><p>Screenplay</p><h2 id="v2-screenplay-drawer-title" ref={headingRef} tabIndex={-1}>Edit script</h2></div>
        <button className="v2-screenplay-icon-button" type="button" aria-label="Close screenplay editor" title="Close screenplay editor" onClick={onCloseRequest}><CloseIcon /></button>
      </header>
      <div className="v2-screenplay-tabs" role="tablist" aria-label="Screenplay views">
        <button id="v2-screenplay-editor-tab" role="tab" type="button" aria-selected={tab === "editor"} aria-controls="v2-screenplay-editor-panel" onClick={() => setTab("editor")}><DocumentIcon /> Editor</button>
        <button id="v2-screenplay-history-tab" role="tab" type="button" aria-selected={tab === "history"} aria-controls="v2-screenplay-history-panel" onClick={() => setTab("history")}><HistoryIcon /> Version history</button>
      </div>
      {state.conflict ? <section className="v2-screenplay-conflict" role="alert"><strong>Latest script changed on the server.</strong><p>{state.conflict.message}</p><div><button className="v2-screenplay-secondary-action" type="button" onClick={() => controller.keepReviewingLocalDraft()}>Keep reviewing local draft</button><button className="v2-screenplay-danger-action" type="button" onClick={() => controller.discardLocalDraftAndReloadLatest()}>Reload and discard local draft</button></div></section> : null}
      <div className="v2-screenplay-drawer__body">
        {state.requestError ? <section className="v2-screenplay-request-error" role="alert"><strong>{state.requestError.message}</strong>{errorViolations.map((violation) => <p key={`${violation.field}:${violation.message}`}><b>{violation.field}</b>: {violation.message}</p>)}<button className="v2-screenplay-secondary-action" type="button" onClick={() => void controller.refreshSelected()}>Retry loading script</button></section> : null}
        {state.isLoading && !state.draft ? <p className="v2-screenplay-status">Loading screenplay...</p> : null}
        {tab === "editor" ? <div id="v2-screenplay-editor-panel" role="tabpanel" aria-labelledby="v2-screenplay-editor-tab">{state.draft ? <V2ScreenplaySceneEditor document={state.draft} validationErrors={state.validationErrors} onChange={controller.updateDraft} /> : !state.isLoading ? <p className="v2-screenplay-empty">No screenplay draft is available.</p> : null}</div> : <div id="v2-screenplay-history-panel" role="tabpanel" aria-labelledby="v2-screenplay-history-tab"><V2ScreenplayVersionHistory controller={controller} /></div>}
      </div>
      <footer className="v2-screenplay-drawer__footer">
        {state.validationErrors.length ? <span className="v2-screenplay-validation-summary">{state.validationErrors.length} field {state.validationErrors.length === 1 ? "needs" : "need"} attention.</span> : <span>{state.dirty ? "Unsaved changes" : "All changes saved"}</span>}
        <button className="v2-screenplay-confirm" type="button" disabled={!state.draft || state.isSaving || state.isSelecting || Boolean(state.conflict)} onClick={() => void controller.confirm()}><SaveIcon /> {state.isSaving ? "Confirming script..." : "Confirm script"}</button>
      </footer>
      {state.closeState === "confirmation_required" ? <div className="v2-screenplay-discard-confirmation" role="alertdialog" aria-modal="true" aria-labelledby="v2-screenplay-discard-title"><div><h3 id="v2-screenplay-discard-title">Discard unsaved screenplay changes?</h3><p>Your local draft has changes that have not been confirmed.</p><div><button className="v2-screenplay-secondary-action" type="button" onClick={() => controller.cancelClose()}>Keep editing</button><button className="v2-screenplay-danger-action" type="button" onClick={() => controller.discardDraftAndClose()}>Discard changes</button></div></div></div> : null}
    </aside>
  </div>;
}

function requestViolations(details: Record<string, unknown> | undefined): Array<{ field: string; message: string }> {
  const raw = details?.violations;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((entry) => {
    if (!entry || typeof entry !== "object") return [];
    const value = entry as Record<string, unknown>;
    return typeof value.message === "string" ? [{ field: typeof value.field === "string" ? value.field : "Screenplay", message: value.message }] : [];
  });
}
