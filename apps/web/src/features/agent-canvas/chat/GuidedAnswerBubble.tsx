import type { GuidedAnswerBubbleV1 } from "./guidedAnswerPresentation.ts";

export function GuidedAnswerBubble({ answer }: { answer: GuidedAnswerBubbleV1 }) {
  return (
    <div className="agent-chat__guided-answer-pair" data-guided-answer-id={answer.bubble_id}>
      <article
        className="agent-chat__message agent-chat__message--agent agent-chat__guided-question-bubble"
        aria-label="Agent question"
      >
        <strong className="agent-chat__message-identity">AdCraft Video Agent</strong>
        <div className="agent-chat__message-body agent-chat__message-body--agent-bubble">
          <p>{answer.label}</p>
        </div>
      </article>
      <article className="agent-chat__message agent-chat__message--user agent-chat__guided-answer-bubble" aria-label="Your guided answer">
        <div className="agent-chat__message-body">
          <strong className="agent-chat__guided-answer-value">{answer.value}</strong>
        </div>
      </article>
    </div>
  );
}
