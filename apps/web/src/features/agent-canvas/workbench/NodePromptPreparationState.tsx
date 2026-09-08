import { useEffect, useRef, useState } from "react";

import type { CanvasNodeV2 } from "../../../types-v2.ts";
import { promptPreparationForNode } from "../model/promptPreparation.ts";
import { useAgentCanvasPresentationStreams } from "../runtime/useAgentCanvasPresentationStreams.ts";

const PREPARATION_LABELS = {
  queued: "Preparing generation prompt",
  working: "Preparing generation prompt",
  failed: "Prompt preparation needs attention",
  superseded: "Prompt preparation was replaced",
  ready: "",
  not_applicable: "",
} as const;

export function NodePromptPreparationState({
  node,
  onRetryPromptPreparation,
  onWorkflowRefresh,
}: {
  node: CanvasNodeV2;
  onRetryPromptPreparation?: (nodeId: string) => Promise<void>;
  onWorkflowRefresh?: () => Promise<void> | void;
}) {
  const preparation = promptPreparationForNode(node);
  const presentationStreamId = preparation?.status === "queued" || preparation?.status === "working"
    ? preparation.presentation_stream_id
    : null;
  const presentationStreams = useAgentCanvasPresentationStreams(
    node.workflow_id,
    presentationStreamId ? [presentationStreamId] : [],
  );
  const handledTerminalEventRef = useRef<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  useEffect(() => {
    if (!presentationStreamId || !onWorkflowRefresh) return;
    const event = presentationStreams[presentationStreamId]?.last_event;
    if (!event || !["committed", "failed", "superseded"].includes(event.event_type)) return;
    const eventKey = `${event.stream_id}:${event.sequence_no}`;
    if (handledTerminalEventRef.current === eventKey) return;
    handledTerminalEventRef.current = eventKey;
    void onWorkflowRefresh();
  }, [onWorkflowRefresh, presentationStreamId, presentationStreams]);

  if (preparation?.status === "ready" || preparation?.status === "not_applicable") return null;

  const summary = node.summary_prompt?.trim() || "Preparing the detailed generation prompt.";
  const status = preparation?.status ?? "queued";
  const error = preparation?.error ?? null;
  const streamPreview = presentationStreamId
    ? presentationStreams[presentationStreamId]?.text.trim()
    : "";
  const canRetry = Boolean(
    status === "failed" && error?.retryable && onRetryPromptPreparation,
  );

  const retry = async () => {
    if (!onRetryPromptPreparation || retrying) return;
    setRetrying(true);
    setRetryError(null);
    try {
      await onRetryPromptPreparation(node.node_id);
      await onWorkflowRefresh?.();
    } catch (retryFailure) {
      setRetryError(
        retryFailure instanceof Error
          ? retryFailure.message
          : "Prompt preparation retry failed.",
      );
    } finally {
      setRetrying(false);
    }
  };

  return (
    <section
      className={`agent-node-workbench__prompt-preparation is-${status}`}
      role={status === "failed" ? "alert" : "status"}
      aria-label="Prompt preparation status"
    >
      <span>{PREPARATION_LABELS[status]}</span>
      <p>{streamPreview || summary}</p>
      {error ? (
        <small>
          {error.message}
          {error.retryable ? " Retryable." : ""}
        </small>
      ) : null}
      {retryError ? <small>{retryError}</small> : null}
      {canRetry ? (
        <div className="agent-node-workbench__prompt-preparation-action">
          <span>仅重新准备提示词</span>
          <button
            type="button"
            aria-label="Retry prompt preparation"
            disabled={retrying}
            onClick={() => void retry()}
          >
            {retrying ? "Preparing…" : "重新准备"}
          </button>
        </div>
      ) : null}
    </section>
  );
}
