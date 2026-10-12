export function GuidedQuestionBubble({ label }: { label: string }) {
  return (
    <article
      className="agent-chat__message agent-chat__message--agent agent-chat__guided-question-bubble"
      aria-label="Agent question"
    >
      <strong className="agent-chat__message-identity">AdCraft Video Agent</strong>
      <div className="agent-chat__message-body agent-chat__message-body--agent-bubble">
        <p>{label}</p>
      </div>
    </article>
  );
}
