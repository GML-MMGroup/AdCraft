import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent, type PointerEvent } from "react";
import { createPortal } from "react-dom";
import { CloseIcon, ConfirmIcon } from "../../icons.tsx";
import type { ProjectListItem } from "./ProjectList.tsx";

type ProjectRenameDialogProps = {
  project: ProjectListItem;
  onClose: () => void;
  onRename: (projectId: string, name: string) => Promise<boolean>;
};

export function ProjectRenameDialog({ project, onClose, onRename }: ProjectRenameDialogProps) {
  const [draft, setDraft] = useState(project.name);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const inputId = useId();
  const trimmedDraft = draft.trim();
  const canSubmit = Boolean(trimmedDraft) && trimmedDraft !== project.name && !isSubmitting;

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    inputRef.current?.focus();
    inputRef.current?.select();

    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  async function submitRename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    setIsSubmitting(true);
    setError(null);
    inputRef.current?.focus();

    try {
      const renamed = await onRename(project.projectId, trimmedDraft);
      if (!renamed) throw new Error("Rename was not accepted");
      onClose();
    } catch {
      setError("Unable to rename this project. Try again.");
      setIsSubmitting(false);
      inputRef.current?.focus();
    }
  }

  function closeDialog() {
    if (!isSubmitting) onClose();
  }

  function handleBackdropPointerDown(event: PointerEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget) closeDialog();
  }

  function handleDialogKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeDialog();
      return;
    }
    if (event.key !== "Tab") return;

    const focusable = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(
        "input:not(:disabled), button:not(:disabled)",
      ) ?? [],
    );
    const first = focusable[0];
    const last = focusable.at(-1);
    if (!first || !last) return;

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return createPortal(
    <div className="project-rename-backdrop" onPointerDown={handleBackdropPointerDown}>
      <div
        className="project-rename-dialog"
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-busy={isSubmitting}
      >
        <header className="project-rename-dialog__header">
          <h2 id={titleId}>Rename project</h2>
        </header>
        <form className="project-rename-form" onSubmit={submitRename}>
          <label htmlFor={inputId}>Project name</label>
          <input
            id={inputId}
            ref={inputRef}
            type="text"
            value={draft}
            readOnly={isSubmitting}
            autoComplete="off"
            onKeyDown={handleDialogKeyDown}
            onChange={(event) => {
              setDraft(event.target.value);
              if (error) setError(null);
            }}
          />
          {error ? <p className="project-rename-error" role="alert">{error}</p> : null}
          <div className="project-rename-actions">
            <button
              className="project-rename-action project-rename-action--cancel"
              type="button"
              aria-label="Cancel rename"
              title="Cancel"
              disabled={isSubmitting}
              onKeyDown={handleDialogKeyDown}
              onClick={closeDialog}
            >
              <CloseIcon />
            </button>
            <button
              className="project-rename-action project-rename-action--confirm"
              type="submit"
              aria-label={isSubmitting ? "Renaming project" : "Confirm rename"}
              title={isSubmitting ? "Renaming project" : "Rename"}
              disabled={!canSubmit}
              onKeyDown={handleDialogKeyDown}
            >
              {isSubmitting ? <span className="project-rename-spinner" aria-hidden="true" /> : <ConfirmIcon />}
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body,
  );
}
