import type { GuidedAnswerBubbleV1 } from "./guidedAnswerPresentation.ts";

export function GuidedAnswerBubble({ answer }: { answer: GuidedAnswerBubbleV1 }) {
  return (
    <article className="agent-chat__message agent-chat__message--user agent-chat__guided-answer-bubble" aria-label="Your guided answer">
      <div className="agent-chat__message-body">
        <span className="agent-chat__guided-answer-label">{answer.label}</span>
        <strong className="agent-chat__guided-answer-value">{answer.value}</strong>
      </div>
    </article>
  );
}
