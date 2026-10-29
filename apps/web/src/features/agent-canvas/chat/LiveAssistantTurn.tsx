import type { ChatMessageV2 } from "../../../types-v2.ts";
import { useTranslation } from "../../../i18n/useTranslation";
import type { PresentationStreamView } from "../runtime/useAgentCanvasPresentationStreams.ts";
import { AgentThinkingBlock } from "./AgentThinkingBlock.tsx";
import { NaturalMessage } from "./NaturalMessage.tsx";
import { projectNaturalMessagePresentation } from "./naturalMessagePresentation.ts";
import { useTypewriterText } from "./useTypewriterText.ts";

export function LiveAssistantTurn({ view }: { view: PresentationStreamView }) {
  const t = useTranslation();
  const answer = useTypewriterText(view.text, { animate: true });
  const open = ["connecting", "open", "reconnecting"].includes(view.status);
  const phase = view.answer_started_at !== null || ["completed", "failed", "superseded"].includes(view.status)
    ? "done"
    : "thinking";
  const durationSeconds = view.reasoning_started_at !== null
    ? ((view.answer_started_at ?? view.terminal_at_ms ?? null) === null
      ? null
      : Math.max(0, ((view.answer_started_at ?? view.terminal_at_ms!) - view.reasoning_started_at) / 1_000))
    : null;
  const message: ChatMessageV2 = {
    item_type: "message",
    message_kind: "conversation",
    message_id: `live:${view.stream_id}`,
    conversation_id: "live",
    speaker: "adcraft_video_agent",
    text: answer,
    linked_node_ids: [],
    script_node_id: null,
    proposal_id: null,
    capability_id: null,
    sequence: Number.MAX_SAFE_INTEGER,
    created_at: new Date().toISOString(),
  };
  return (
    <div className="agent-chat__live-turn" aria-busy={open} aria-live="off">
      <span className="sr-only" role="status" aria-live="polite">
        {view.answer_started_at !== null
          ? t("Writing response")
          : view.reasoning_started_at !== null
            ? t("Thinking…")
            : ""}
      </span>
      {view.reasoning_text ? (
        <AgentThinkingBlock reasoningText={view.reasoning_text} phase={phase} durationSeconds={durationSeconds} />
      ) : null}
      {answer ? (
        <NaturalMessage
          message={message}
          presentation={projectNaturalMessagePresentation([message]).get(message.message_id) ?? {
            messageId: message.message_id,
            showAgentIdentity: true,
            startsSpeakerRun: true,
          }}
        />
      ) : view.reasoning_text && view.generation_id?.startsWith("brand-gen:") ? (
        <span className="agent-chat__live-working-label">{t("Working")}</span>
      ) : null}
    </div>
  );
}
