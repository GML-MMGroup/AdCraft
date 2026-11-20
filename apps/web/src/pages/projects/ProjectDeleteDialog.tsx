import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { CloseIcon, FolderIcon, TrashIcon } from "../../icons.tsx";
import { localeText, useLocale } from "../../i18n/locale.tsx";
import "./ProjectDeleteDialog.css";

export function ProjectDeleteDialog({ projects, busy, progress, cancelling, returnFocusTo, onClose, onConfirm, onCancel }: {
  projects: readonly { projectId: string; name: string }[];
  busy: boolean;
  progress: { processed: number; failed: number };
  cancelling: boolean;
  returnFocusTo: HTMLElement | null;
  onClose: () => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { locale } = useLocale();
  const labels = locale === "zh-CN" ? localeText.zh.trashPage : localeText.en.trashPage;
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const progressText = labels.deleteProcessed
    .replace("{completed}", String(progress.processed))
    .replace("{total}", String(projects.length));
  const finished = busy && progress.processed === projects.length;

  useEffect(() => {
    const previousFocus = returnFocusTo;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    cancelRef.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    };
  }, [returnFocusTo]);

  useEffect(() => {
    if (busy) dialogRef.current?.focus();
  }, [busy, cancelling]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        if (!busy) onClose();
      }
      if (event.key !== "Tab") return;
      const dialog = dialogRef.current;
      const buttons = dialog?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)");
      const first = buttons?.[0];
      const last = buttons?.[buttons.length - 1];
      if (!first || !last) {
        event.preventDefault();
        dialog?.focus();
      } else if (!dialog?.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", handleKeyDown, true);
    return () => document.removeEventListener("keydown", handleKeyDown, true);
  }, [busy, onClose]);

  return createPortal(
    <div className="trash-delete-backdrop" onPointerDown={(event) => {
      if (event.target === event.currentTarget && !busy) onClose();
    }}>
      <div
        ref={dialogRef}
        className="trash-delete-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        aria-busy={busy}
        tabIndex={-1}
      >
        <button className="trash-delete-dialog__close" type="button" aria-label={labels.close} disabled={busy} onClick={onClose}>
          <CloseIcon />
        </button>
        <header className="trash-delete-dialog__header">
          <span className="trash-delete-dialog__icon" aria-hidden="true"><TrashIcon /></span>
          <h2 id={titleId}>{projects.length === 1 ? labels.deleteTitle : labels.deleteManyTitle.replace("{count}", String(projects.length))}</h2>
          <p id={descriptionId}>{labels.deleteDescription}</p>
        </header>
        <ul className="trash-delete-dialog__projects" aria-label={labels.projectsToDelete}>
          {projects.map((project) => <li key={project.projectId}><FolderIcon /><span>{project.name}</span></li>)}
        </ul>
        <p className="trash-delete-dialog__preserved">{labels.deletePreserved}</p>
        {busy ? (
          <div className="trash-delete-dialog__progress" role="status" aria-live="polite" aria-atomic="true">
            <p className="trash-delete-dialog__progress-count">{progressText}</p>
            <progress value={progress.processed} max={projects.length} aria-label={labels.deleteProgress} aria-valuetext={progressText} />
            {progress.failed > 0 ? <p className="trash-delete-dialog__progress-failed">{labels.deleteFailedCount.replace("{count}", String(progress.failed))}</p> : null}
            <p className="trash-delete-dialog__progress-note">{cancelling ? labels.deleteCancellingNote : finished ? labels.deleteRefreshing : labels.deleteCancellationHint}</p>
          </div>
        ) : null}
        <footer className="trash-delete-dialog__actions">
          {!busy ? <button ref={cancelRef} className="trash-delete-dialog__cancel" type="button" onClick={onClose}>{labels.cancel}</button> : null}
          <button className="trash-delete-dialog__confirm" type="button" disabled={busy && (cancelling || finished)} onClick={busy ? onCancel : onConfirm}>
            {busy && (cancelling || finished) ? <span className="trash-delete-dialog__spinner" aria-hidden="true" /> : busy ? <CloseIcon /> : <TrashIcon />}
            {busy ? finished ? labels.deleteRefreshing : cancelling ? labels.deleteCancelling : labels.cancelDeletion : labels.deletePermanently}
          </button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
