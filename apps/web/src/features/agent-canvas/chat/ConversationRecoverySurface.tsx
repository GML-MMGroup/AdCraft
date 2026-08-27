import { useEffect, useRef, useState } from "react";

import type { ConversationRecoveryView } from "./conversationRecovery.ts";

export interface ConversationRecoverySurfaceProps {
  recovery: ConversationRecoveryView;
  onAction?: () => void;
  onDismiss?: () => void;
}

const ACTION_LABELS: Record<ConversationRecoveryView["action"], string> = {
  retry: "Retry",
  refresh: "Refresh",
  review: "Review latest",
  none: "",
};

export function ConversationRecoverySurface({
  recovery,
  onAction,
  onDismiss,
}: ConversationRecoverySurfaceProps) {
  const recoveryRef = useRef<HTMLElement>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  useEffect(() => {
    setDetailOpen(false);
    recoveryRef.current?.focus();
  }, [recovery]);

  return (
    <section
      ref={recoveryRef}
      className={`agent-chat__recovery is-${recovery.scope}`}
      role="alert"
      tabIndex={-1}
      aria-label={recovery.title}
    >
      <div className="agent-chat__recovery-copy">
        <strong>{recovery.title}</strong>
        <p>{recovery.message}</p>
      </div>
      <div className="agent-chat__recovery-actions">
        {recovery.action !== "none" && onAction ? (
          <button type="button" onClick={onAction}>
            {ACTION_LABELS[recovery.action]}
          </button>
        ) : null}
        {onDismiss ? (
          <button type="button" className="is-secondary" onClick={onDismiss}>
            Dismiss
          </button>
        ) : null}
      </div>
      {recovery.technicalDetail ? (
        <details open={detailOpen}>
          <summary
            onClick={(event) => {
              event.preventDefault();
              setDetailOpen((current) => !current);
            }}
          >
            Technical details
          </summary>
          {detailOpen ? <code>{recovery.technicalDetail}</code> : null}
        </details>
      ) : null}
    </section>
  );
}
