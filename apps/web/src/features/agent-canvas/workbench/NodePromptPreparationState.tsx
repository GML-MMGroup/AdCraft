import { useEffect, useRef } from "react";

import { useTranslation } from "../../../i18n/useTranslation";
import type { CanvasNodeV2 } from "../../../types-v2.ts";
import { failureUserAction } from "../chat/actionableFailure.ts";
import { promptPreparationForNode } from "../model/promptPreparation.ts";
import { useAgentCanvasPresentationStreams } from "../runtime/useAgentCanvasPresentationStreams.ts";
import { AgentThinkingBlock } from "../chat/AgentThinkingBlock.tsx";
import { useTypewriterText } from "../chat/useTypewriterText.ts";

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
  onRevise,
  hideActiveStatus = false,
}: {
  node: CanvasNodeV2;
  onWorkflowRefresh?: () => Promise<void> | void;
  onRevise?: () => void;
  hideActiveStatus?: boolean;
}) {
  const t = useTranslation();
  const preparation = promptPreparationForNode(node);
  const presentationStreamId = preparation?.status === "queued" || preparation?.status === "working"
    ? preparation.presentation_stream_id
    : null;
  const presentationStreams = useAgentCanvasPresentationStreams(
    node.workflow_id,
    presentationStreamId ? [presentationStreamId] : [],
  );
  const streamView = presentationStreamId ? presentationStreams[presentationStreamId] : null;
  const streamPreview = streamView?.text.trim() ?? "";
  const typedPreview = useTypewriterText(streamPreview, {
    animate: preparation?.status === "queued" || preparation?.status === "working",
  });
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
  if (hideActiveStatus && (preparation.status === "queued" || preparation.status === "working")) return null;
  if (preparation?.status === "ready" || preparation?.status === "not_applicable") return null;

  const summary = preparation.status === "waiting_user"
      ? t("Enter a prompt to continue.")
    : node.summary_prompt?.trim() || t("Preparing the detailed generation prompt.");
  const status = preparation?.status ?? "queued";
  const error = preparation?.error ?? null;
  const userAction = failureUserAction(error?.actionable_failure);
  const activePreparation = status === "queued" || status === "working";

  return (
    <section
      className={`agent-node-workbench__prompt-preparation is-${status}`}
      role={status === "failed" ? "alert" : "status"}
      aria-label={t("Prompt preparation status")}
    >
      <span>{t(PREPARATION_LABELS[status])}</span>
      {activePreparation && streamView?.reasoning_text ? (
        <AgentThinkingBlock
          reasoningText={streamView.reasoning_text}
          phase="thinking"
          durationSeconds={null}
        />
      ) : null}
      <p>{typedPreview || summary}{activePreparation && typedPreview ? <span className="agent-node-workbench__prompt-caret" aria-hidden="true">▍</span> : null}</p>
      {error ? (
        <small>{error.message}</small>
      ) : null}
      {status === "failed" && userAction === "revise" && onRevise ? (
        <button type="button" onClick={onRevise}>
          {t("Revise generation prompt")}
        </button>
      ) : null}
    </section>
  );
}
