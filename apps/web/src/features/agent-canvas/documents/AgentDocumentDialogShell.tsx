import { useEffect } from "react";
import type { ReactNode, RefObject } from "react";
import { createPortal } from "react-dom";

import { CloseIcon } from "../../../icons.tsx";

export function AgentDocumentDialogShell({
  ariaLabel,
  title,
  subtitle,
  returnFocusRef,
  onClose,
  children,
}: {
  ariaLabel: string;
  title: string;
  subtitle: string;
  returnFocusRef?: RefObject<HTMLButtonElement | null>;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    const returnFocusTarget = returnFocusRef?.current;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };

    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", closeOnEscape);
      returnFocusTarget?.focus();
    };
  }, [onClose, returnFocusRef]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <div className="agent-document-browser__overlay">
      <button
        type="button"
        className="agent-document-browser__backdrop"
        aria-label={`Dismiss ${ariaLabel}`}
        tabIndex={-1}
        onClick={onClose}
      />
      <section
        className="agent-document-browser__panel"
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
      >
        <header>
          <div>
            <strong>{title}</strong>
            <small>{subtitle}</small>
          </div>
          <button
            type="button"
            aria-label={`Close ${ariaLabel}`}
            autoFocus
            onClick={onClose}
          >
            <CloseIcon />
          </button>
        </header>
        {children}
      </section>
    </div>,
    document.body,
  );
}
