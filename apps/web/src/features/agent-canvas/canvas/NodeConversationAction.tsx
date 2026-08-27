export function NodeConversationAction({
  nodeId,
  onShowInConversation,
}: {
  nodeId: string;
  onShowInConversation: (nodeId: string) => void;
}) {
  return (
    <button
      type="button"
      className="agent-canvas-node__conversation-action nodrag nopan"
      onPointerDown={(event) => event.stopPropagation()}
      onDoubleClick={(event) => event.stopPropagation()}
      onClick={(event) => {
        event.stopPropagation();
        onShowInConversation(nodeId);
      }}
    >
      Show in conversation
    </button>
  );
}
