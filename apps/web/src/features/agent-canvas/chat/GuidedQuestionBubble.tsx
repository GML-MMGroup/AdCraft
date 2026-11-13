import { AgentMessageAvatar } from "./AgentMessageAvatar.tsx";
import { useTranslation } from "../../../i18n/useTranslation.ts";
import { guidedInteractionCopy } from "./guidedInteractionCopy.ts";

export function GuidedQuestionBubble({ label }: { label: string }) {
  const t = useTranslation();
  return (
    <article
      className="agent-chat__message agent-chat__message--agent agent-chat__guided-question-bubble"
      aria-label={t("Agent question")}
    >
      <AgentMessageAvatar />
      <div className="agent-chat__message-body agent-chat__message-body--agent-bubble">
        <p>{guidedInteractionCopy(label, t)}</p>
      </div>
    </article>
  );
}
