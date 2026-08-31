import { useEffect, useRef } from "react";

import type { CanvasNodeV2 } from "../../../types-v2.ts";
import { promptPreparationForNode } from "../model/promptPreparation.ts";
import { useAgentCanvasPresentationStreams } from "../runtime/useAgentCanvasPresentationStreams.ts";

const PREPARATION_LABELS = {
  queued: "Preparing generation prompt",
  working: "Preparing generation prompt",
  waiting_user: "Prompt input needed",
  failed: "Prompt preparation needs attention",
  superseded: "Prompt preparation was replaced",
  ready: "",
  not_applicable: "",
} as const;

export function NodePromptPreparationState({
  node,
  onWorkflowRefresh,
}: {
  node: CanvasNodeV2;
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

  useEffect(() => {
    if (!presentationStreamId || !onWorkflowRefresh) return;
    const event = presentationStreams[presentationStreamId]?.last_event;
    if (!event || !["committed", "failed", "superseded"].includes(event.event_type)) return;
    const eventKey = `${event.stream_id}:${event.sequence_no}`;
    if (handledTerminalEventRef.current === eventKey) return;
    handledTerminalEventRef.current = eventKey;
    void onWorkflowRefresh();
  }, [onWorkflowRefresh, presentationStreamId, presentationStreams]);

  if (!preparation) return null;
  if (preparation?.status === "ready" || preparation?.status === "not_applicable") return null;

  const summary = preparation.status === "waiting_user"
    ? "Enter a prompt to continue."
    : node.summary_prompt?.trim() || "Preparing the detailed generation prompt.";
  const status = preparation?.status ?? "queued";
  const error = preparation?.error ?? null;
  const streamPreview = presentationStreamId
    ? presentationStreams[presentationStreamId]?.text.trim()
    : "";

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
    </section>
  );
}
