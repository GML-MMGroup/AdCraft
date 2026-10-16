import type { GuidedAnswerBubbleV1 } from "./guidedAnswerPresentation.ts";
import { GuidedQuestionBubble } from "./GuidedQuestionBubble.tsx";

export function GuidedAnswerBubble({ answer }: { answer: GuidedAnswerBubbleV1 }) {
  return (
    <div className="agent-chat__guided-answer-pair" data-guided-answer-id={answer.bubble_id}>
      <GuidedQuestionBubble label={answer.label} />
      <article className="agent-chat__message agent-chat__message--user agent-chat__guided-answer-bubble" aria-label="Your guided answer">
        <div className="agent-chat__message-body">
          <strong className="agent-chat__guided-answer-value">{answer.value}</strong>
        </div>
      </article>
    </div>
  );
}
