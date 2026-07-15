import { useEffect, useRef, useState, type RefObject } from "react";
import { CloseIcon, DocumentIcon, HistoryIcon, SaveIcon } from "../../../../icons.tsx";
import { V2ScreenplaySceneEditor } from "./V2ScreenplaySceneEditor.tsx";
import { validateEditableScript } from "./screenplayModel.ts";
import { nextFocusableIndex, nextTabIndex, selectionGate, summarizeValidationIssues, versionSelectionFocusTarget, type ScreenplayProductOption, type ScreenplayVersionTarget } from "./screenplayUiHelpers.ts";
import { V2ScreenplayVersionHistory } from "./V2ScreenplayVersionHistory.tsx";
import type { V2ScreenplayController } from "./useV2ScreenplayController.ts";

type Operation =
  | { kind: "initial_load" }
  | { kind: "selected_refresh" }
  | { kind: "history_refresh" }
  | { kind: "confirm" }
  | { kind: "select"; target: ScreenplayVersionTarget };

type Props = {
  controller: V2ScreenplayController;
  productOptions?: readonly ScreenplayProductOption[];
  returnFocusRef?: RefObject<HTMLElement | null>;
  returnFocusElement?: HTMLElement | null;
};

const tabs = ["editor", "history"] as const;
type Tab = typeof tabs[number];
const focusableSelector = "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";

export function V2ScreenplayDrawer({ controller, productOptions = [], returnFocusRef, returnFocusElement }: Props) {
  const { state } = controller;
  const [tab, setTab] = useState<Tab>("editor");
  const [pendingVersion, setPendingVersion] = useState<ScreenplayVersionTarget | null>(null);
  const [lastFailedOperation, setLastFailedOperation] = useState<Operation | null>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const wasOpenRef = useRef(false);
  const dialogReturnFocusRef = useRef<HTMLElement | null>(null);
  const selectionTriggerRef = useRef<HTMLElement | null>(null);
  const wasSelectingRef = useRef(false);
  const requestedOperationRef = useRef<Operation | null>(null);

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
    if (!state.requestError) return;
    setLastFailedOperation(operationForRequest(state.requestError.operation, requestedOperationRef.current));
  }, [state.requestError]);

  useEffect(() => {
    const selectionFinished = wasSelectingRef.current && !state.isSelecting;
    wasSelectingRef.current = state.isSelecting;
    if (!selectionFinished) return;
    const trigger = selectionTriggerRef.current;
    selectionTriggerRef.current = null;
    const failed = state.requestError?.operation === "select";
    const triggerEnabled = trigger instanceof HTMLButtonElement && !trigger.disabled && document.contains(trigger);
    requestAnimationFrame(() => {
      if (versionSelectionFocusTarget({ failed, triggerEnabled }) === "trigger") trigger?.focus();
      else (tabRefs.current[1] ?? headingRef.current)?.focus();
    });
  }, [state.isSelecting, state.requestError]);

  useEffect(() => {
    if (!state.isOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || pendingVersion || state.closeState === "confirmation_required") return;
      event.preventDefault();
      dialogReturnFocusRef.current = activeElement();
      controller.close();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [controller, pendingVersion, state.closeState, state.isOpen]);

  useEffect(() => {
    const drawer = drawerRef.current;
    if (!state.isOpen || !drawer) return;
    const trapFocus = (event: KeyboardEvent) => trapTabFocus(drawer, event, headingRef.current);
    drawer.addEventListener("keydown", trapFocus);
    return () => drawer.removeEventListener("keydown", trapFocus);
  }, [state.isOpen]);

  if (!state.isOpen) return null;
  const draftMutationLocked = state.isSaving || state.isSelecting;
  const validationIssues = summarizeValidationIssues([...new Map([
    ...state.validationErrors,
    ...(state.draft ? validateEditableScript(state.draft) : []),
  ].map((issue) => [`${issue.path}:${issue.message}`, issue])).values()]);
  const errorOperation = lastFailedOperation ?? (state.requestError ? operationForRequest(state.requestError.operation) : null);
  const errorViolations = requestViolations(state.requestError?.details);

  const requestClose = () => {
    dialogReturnFocusRef.current = activeElement();
    controller.close();
  };

  const runOperation = (operation: Operation) => {
    requestedOperationRef.current = operation;
    setLastFailedOperation(null);
    if (operation.kind === "initial_load" || operation.kind === "selected_refresh") void controller.refreshSelected();
    if (operation.kind === "history_refresh") void controller.refreshHistory();
    if (operation.kind === "confirm") void controller.confirm();
    if (operation.kind === "select") {
      selectionTriggerRef.current ??= activeElement();
      void controller.selectVersion(operation.target.script_version_id);
    }
  };

  const requestVersionSelection = (target: ScreenplayVersionTarget, trigger: HTMLButtonElement) => {
    dialogReturnFocusRef.current = trigger;
    const decision = selectionGate(state.dirty, target);
    if (decision.action === "confirm_discard") {
      setPendingVersion(decision.target);
      return;
    }
    runOperation({ kind: "select", target: decision.target });
  };

  const finishDialog = (action: () => void) => {
    action();
    const target = dialogReturnFocusRef.current;
    dialogReturnFocusRef.current = null;
    requestAnimationFrame(() => target?.focus());
  };

  const onTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    const next = nextTabIndex(event.key, index, tabs.length);
    if (next === null) return;
    event.preventDefault();
    setTab(tabs[next]);
    tabRefs.current[next]?.focus();
  };

  return <div className="v2-screenplay-drawer-backdrop">
    <aside ref={drawerRef} className="v2-screenplay-drawer" role="dialog" aria-modal="true" aria-labelledby="v2-screenplay-drawer-title">
      <div className="v2-screenplay-drawer__top">
        <header className="v2-screenplay-drawer__header">
          <div><p>Screenplay</p><h2 id="v2-screenplay-drawer-title" ref={headingRef} tabIndex={-1}>Edit script</h2></div>
          <button className="v2-screenplay-icon-button" type="button" aria-label="Close screenplay editor" title="Close screenplay editor" onClick={requestClose}><CloseIcon /></button>
        </header>
        <div className="v2-screenplay-tabs" role="tablist" aria-label="Screenplay views">
          {tabs.map((item, index) => <button key={item} ref={(node) => { tabRefs.current[index] = node; }} id={`v2-screenplay-${item}-tab`} role="tab" type="button" tabIndex={tab === item ? 0 : -1} aria-selected={tab === item} aria-controls={`v2-screenplay-${item}-panel`} onKeyDown={(event) => onTabKeyDown(event, index)} onClick={() => setTab(item)}>{item === "editor" ? <DocumentIcon /> : <HistoryIcon />}{item === "editor" ? "Editor" : "Version history"}</button>)}
        </div>
      </div>
      <div className="v2-screenplay-drawer__body">
        {state.conflict ? <section className="v2-screenplay-conflict" role="alert"><strong>Latest script changed on the server.</strong><p>{state.conflict.message}</p><div><button className="v2-screenplay-secondary-action" type="button" onClick={() => controller.keepReviewingLocalDraft()}>Keep reviewing local draft</button><button className="v2-screenplay-danger-action" type="button" onClick={() => controller.discardLocalDraftAndReloadLatest()}>Reload and discard local draft</button></div></section> : null}
        {state.requestError ? <RequestErrorNotice error={state.requestError.message} violations={errorViolations} operation={errorOperation} onRetry={() => { if (errorOperation) runOperation(errorOperation); }} /> : null}
        {validationIssues.length ? <section className="v2-screenplay-validation-summary" aria-live="polite" role="status"><strong>Fix these fields before confirming:</strong><ul>{validationIssues.map((issue) => <li key={`${issue.path}:${issue.message}`}><code>{issue.path}</code>: {issue.message}</li>)}</ul></section> : null}
        {state.isLoading && !state.draft ? <p className="v2-screenplay-status">Loading screenplay...</p> : null}
        {tab === "editor" ? <div id="v2-screenplay-editor-panel" role="tabpanel" aria-labelledby="v2-screenplay-editor-tab">{state.draft ? <V2ScreenplaySceneEditor document={state.draft} disabled={draftMutationLocked} validationErrors={validationIssues} onChange={controller.updateDraft} productOptions={productOptions} /> : !state.isLoading ? <p className="v2-screenplay-empty">No screenplay draft is available.</p> : null}</div> : <div id="v2-screenplay-history-panel" role="tabpanel" aria-labelledby="v2-screenplay-history-tab"><V2ScreenplayVersionHistory controller={controller} pendingVersionId={pendingVersion?.script_version_id} onRequestSelect={requestVersionSelection} onRefreshHistory={() => runOperation({ kind: "history_refresh" })} /></div>}
      </div>
      <footer className="v2-screenplay-drawer__footer">
        <span>{state.dirty ? "Unsaved changes" : "All changes saved"}</span>
        <button className="v2-screenplay-confirm" type="button" disabled={!state.draft || validationIssues.length > 0 || state.isSaving || state.isSelecting || Boolean(state.conflict)} onClick={() => runOperation({ kind: "confirm" })}><SaveIcon /> {state.isSaving ? "Confirming script..." : "Confirm script"}</button>
      </footer>
      {state.closeState === "confirmation_required" ? <ConfirmationDialog title="Discard unsaved screenplay changes?" description="Your local draft has changes that have not been confirmed." confirmLabel="Discard changes" onCancel={() => finishDialog(() => controller.cancelClose())} onConfirm={() => finishDialog(() => controller.discardDraftAndClose())} /> : null}
      {pendingVersion ? <ConfirmationDialog title={`Use ${pendingVersion.script_title}?`} description="Your unsaved changes will be discarded and this saved script version will become selected." confirmLabel="Use this script version" onCancel={() => finishDialog(() => setPendingVersion(null))} onConfirm={() => { const target = pendingVersion; selectionTriggerRef.current = dialogReturnFocusRef.current; dialogReturnFocusRef.current = null; setPendingVersion(null); runOperation({ kind: "select", target }); }} /> : null}
    </aside>
  </div>;
}

function ConfirmationDialog({ title, description, confirmLabel, onCancel, onConfirm }: { title: string; description: string; confirmLabel: string; onCancel: () => void; onConfirm: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { cancelRef.current?.focus(); }, []);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
      const trapFocus = (event: KeyboardEvent) => {
        if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); onCancel(); return; }
        if (event.key === "Tab") event.stopPropagation();
        trapTabFocus(dialog, event, dialog);
      };
    dialog.addEventListener("keydown", trapFocus);
    return () => dialog.removeEventListener("keydown", trapFocus);
  }, [onCancel]);
  return <div className="v2-screenplay-discard-confirmation" role="presentation"><dialog ref={dialogRef} open role="alertdialog" aria-modal="true" aria-labelledby="v2-screenplay-confirmation-title" tabIndex={-1}><h3 id="v2-screenplay-confirmation-title">{title}</h3><p>{description}</p><div><button ref={cancelRef} className="v2-screenplay-secondary-action" type="button" onClick={onCancel}>Cancel</button><button className="v2-screenplay-danger-action" type="button" onClick={onConfirm}>{confirmLabel}</button></div></dialog></div>;
}

function RequestErrorNotice({ error, violations, operation, onRetry }: { error: string; violations: Array<{ field: string; message: string }>; operation: Operation | null; onRetry: () => void }) {
  return <section className="v2-screenplay-request-error" role="alert"><strong>{operationLabel(operation)}</strong><p>{error}</p>{violations.map((violation) => <p key={`${violation.field}:${violation.message}`}><b>{violation.field}</b>: {violation.message}</p>)}{operation ? <button className="v2-screenplay-secondary-action" type="button" onClick={onRetry}>{retryLabel(operation)}</button> : null}</section>;
}

function operationForRequest(operation: "open" | "confirm" | "select" | "refresh_selected" | "refresh_history", requested?: Operation | null): Operation { if (operation === "select" && requested?.kind === "select") return requested; return operation === "open" ? { kind: "initial_load" } : operation === "confirm" ? { kind: "confirm" } : operation === "select" ? { kind: "select", target: { script_version_id: "", script_title: "script version" } } : operation === "refresh_history" ? { kind: "history_refresh" } : { kind: "selected_refresh" }; }
function operationLabel(operation: Operation | null): string { return operation?.kind === "confirm" ? "Unable to confirm screenplay." : operation?.kind === "select" ? "Unable to select script version." : operation?.kind === "history_refresh" ? "Unable to refresh version history." : operation?.kind === "selected_refresh" ? "Unable to refresh selected screenplay." : "Unable to load screenplay."; }
function retryLabel(operation: Operation): string { return operation.kind === "confirm" ? "Retry confirmation" : operation.kind === "select" ? "Retry version selection" : operation.kind === "history_refresh" ? "Retry version history" : operation.kind === "selected_refresh" ? "Retry selected screenplay refresh" : "Retry loading screenplay"; }
function activeElement(): HTMLElement | null { return document.activeElement instanceof HTMLElement ? document.activeElement : null; }
function focusableElements(container: HTMLElement): HTMLElement[] { return [...container.querySelectorAll<HTMLElement>(focusableSelector)].filter((element) => element.closest("fieldset:disabled") === null); }
function trapTabFocus(container: HTMLElement, event: KeyboardEvent, fallback: HTMLElement | null): void {
  if (event.key !== "Tab" || event.defaultPrevented) return;
  event.preventDefault();
  const focusable = focusableElements(container);
  if (!focusable.length) { fallback?.focus(); return; }
  const current = focusable.indexOf(document.activeElement as HTMLElement);
  const next = current < 0
    ? event.shiftKey ? focusable.length - 1 : 0
    : nextFocusableIndex(current, focusable.length, event.shiftKey);
  focusable[next]?.focus();
}
function requestViolations(details: Record<string, unknown> | undefined): Array<{ field: string; message: string }> { const raw = details?.violations; if (!Array.isArray(raw)) return []; return raw.flatMap((entry) => { if (!entry || typeof entry !== "object") return []; const value = entry as Record<string, unknown>; return typeof value.message === "string" ? [{ field: typeof value.field === "string" ? value.field : "Screenplay", message: value.message }] : []; }); }
