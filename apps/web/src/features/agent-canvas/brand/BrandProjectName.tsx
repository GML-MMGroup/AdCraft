import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { CloseIcon, ConfirmIcon, EditIcon } from "../../../icons.tsx";
import { useTranslation } from "../../../i18n/useTranslation.ts";

export function BrandProjectName({ name, onRename }: {
  name: string;
  onRename?: (name: string) => Promise<boolean>;
}) {
  const t = useTranslation();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const submittingRef = useRef(false);
  const errorId = useId();

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  function closeEditor() {
    setEditing(false);
    requestAnimationFrame(() => triggerRef.current?.focus());
  }

  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    event.stopPropagation();
    if (event.nativeEvent.isComposing || event.keyCode === 229) {
      if (event.key === "Enter") event.preventDefault();
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      if (!submittingRef.current) closeEditor();
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = draft.trim();
    if (!onRename || !trimmed || submittingRef.current) return;
    if (trimmed === name) {
      closeEditor();
      return;
    }
    submittingRef.current = true;
    setSaving(true);
    setError(false);
    try {
      if (!await onRename(trimmed)) throw new Error("Rename was not accepted");
      closeEditor();
    } catch {
      setError(true);
      inputRef.current?.focus();
    } finally {
      submittingRef.current = false;
      setSaving(false);
    }
  }

  if (!editing) return (
    <h2 aria-label={name}>
      {onRename ? <button
        ref={triggerRef}
        type="button"
        className="brand-decision-panel__project-name"
        aria-label={t("Rename project")}
        title={t("Rename project")}
        onClick={() => { setDraft(name); setError(false); setEditing(true); }}
      >
        <span>{name}</span><EditIcon />
      </button> : name}
    </h2>
  );

  return (
    <form className="brand-decision-panel__rename" aria-label={t("Rename project")} aria-busy={saving}
      onSubmit={(event) => void submit(event)}
    >
      <div className="brand-decision-panel__rename-controls">
        <input ref={inputRef} type="text" value={draft} readOnly={saving} required autoComplete="off"
          aria-label={t("Project name")} aria-invalid={error || undefined} aria-describedby={error ? errorId : undefined}
          onKeyDown={handleKeyDown}
          onChange={(event) => { setDraft(event.target.value); setError(false); }}
        />
        <button type="submit" disabled={saving || !draft.trim()}
          onKeyDown={handleKeyDown}
          aria-label={t(saving ? "Renaming project" : "Confirm rename")} title={t("Save")}>
          <ConfirmIcon />
        </button>
        <button type="button" disabled={saving} onClick={closeEditor}
          onKeyDown={handleKeyDown}
          aria-label={t("Cancel rename")} title={t("Cancel")}><CloseIcon /></button>
      </div>
      {error ? <p id={errorId} className="brand-decision-panel__rename-error" role="alert">
        {t("Unable to rename this project. Try again.")}
      </p> : null}
    </form>
  );
}
