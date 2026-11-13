import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { CloseIcon } from "../../../icons.tsx";
import { useTranslation } from "../../../i18n/useTranslation.ts";
import "./brand-form-confirmation-toast.css";

const DISMISS_AFTER_MS = 3_000;

/** Mount with a new key for each confirmation so every notice gets three seconds. */
export function BrandFormConfirmationToast({ kind = "information" }: { kind?: "information" | "skills" }) {
  const t = useTranslation();
  const [visible, setVisible] = useState(true);
  const title = t(kind === "skills" ? "Skills confirmed" : "Information confirmed");
  const description = t(kind === "skills"
    ? "View your confirmed Skills in the left panel."
    : "View your confirmed information in the left panel.");

  useEffect(() => {
    const timer = window.setTimeout(() => setVisible(false), DISMISS_AFTER_MS);
    return () => window.clearTimeout(timer);
  }, []);

  if (!visible) return null;

  return createPortal(
    <aside className="brand-form-confirmation" role="status" aria-live="polite" aria-atomic="true"
      aria-label={title}>
      <span className="brand-form-confirmation__icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none">
          <path d="m6.5 12 3.5 3.5 7.5-7.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      <div className="brand-form-confirmation__copy">
        <strong>{title}</strong>
        <p>{description}</p>
      </div>
      <button type="button" className="brand-form-confirmation__close"
        aria-label={t("Dismiss confirmation")} title={t("Dismiss confirmation")}
        onClick={() => setVisible(false)}>
        <CloseIcon />
      </button>
      <div className="brand-form-confirmation__track" aria-hidden="true">
        <span className="brand-form-confirmation__progress" style={{ animationDuration: `${DISMISS_AFTER_MS}ms` }} />
      </div>
    </aside>,
    document.body,
  );
}
