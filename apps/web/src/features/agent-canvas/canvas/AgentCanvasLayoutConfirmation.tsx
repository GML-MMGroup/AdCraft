import { useEffect, useId, useRef, type RefObject } from "react";

export interface AgentCanvasLayoutConfirmationProps {
  status: "previewing" | "saving" | "save_error";
  error: string | null;
  onUndo: () => void;
  onKeep: () => void;
  dismissExemptRef?: RefObject<HTMLElement | null>;
}

export function AgentCanvasLayoutConfirmation({
  status,
  error,
  onUndo,
  onKeep,
  dismissExemptRef,
}: AgentCanvasLayoutConfirmationProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLParagraphElement>(null);
  const headingId = useId();
  const saving = status === "saving";

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      const dialog = dialogRef.current;
      const exempt = dismissExemptRef?.current;
      if (
        !saving
        && dialog
        && event.target instanceof Node
        && !dialog.contains(event.target)
        && !exempt?.contains(event.target)
      ) {
        onUndo();
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      if (!saving) onUndo();
    };

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [dismissExemptRef, onUndo, saving]);

  return (
    <div
      ref={dialogRef}
      className="agent-canvas-layout-confirmation"
      role="dialog"
      aria-labelledby={headingId}
      aria-busy={saving}
    >
      <p id={headingId} ref={headingRef} tabIndex={-1}>是否保留此次排布</p>
      {error ? <span className="agent-canvas-layout-confirmation__error" role="alert">{error}</span> : null}
      <div className="agent-canvas-layout-confirmation__actions">
        <button type="button" disabled={saving} onClick={onUndo}>撤销</button>
        <button type="button" disabled={saving} onClick={onKeep}>保留</button>
      </div>
    </div>
  );
}
