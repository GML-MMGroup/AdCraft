export const AGENT_CHAT_MAX_WIDTH = 720;
export const AGENT_CHAT_MIN_CANVAS_WIDTH = 320;

export type AgentChatResizeBounds = {
  minWidth: number;
  maxWidth: number;
};

export function getAgentChatResizeBounds(
  minWidth: number,
  viewportWidth: number,
): AgentChatResizeBounds {
  const normalizedMinWidth = Math.max(0, minWidth);
  const availableWidth = Math.max(0, viewportWidth - AGENT_CHAT_MIN_CANVAS_WIDTH);
  return {
    minWidth: normalizedMinWidth,
    maxWidth: Math.max(normalizedMinWidth, Math.min(AGENT_CHAT_MAX_WIDTH, availableWidth)),
  };
}

export function resizeAgentChatWidth({
  startX,
  startWidth,
  pointerX,
  bounds,
}: {
  startX: number;
  startWidth: number;
  pointerX: number;
  bounds: AgentChatResizeBounds;
}): number {
  const nextWidth = startWidth + startX - pointerX;
  return Math.min(bounds.maxWidth, Math.max(bounds.minWidth, nextWidth));
}
