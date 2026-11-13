// Keep the small avatar with the component so it needs no separate image request.
import agentAvatarUrl from "../../../assets/brand/adcraft-agent-avatar.webp?inline";

export function AgentMessageAvatar() {
  return (
    <div className="agent-chat__message-avatar">
      <img src={agentAvatarUrl} alt="AdCraft" width="30" height="30" draggable={false} />
    </div>
  );
}
