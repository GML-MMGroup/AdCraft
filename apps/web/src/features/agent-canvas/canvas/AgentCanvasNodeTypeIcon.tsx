import type { CanvasNodeTypeV2 } from "../../../types-v2.ts";
import { isAgentCanvasVisibleNodeType } from "../model/nodeDefaults.ts";

const NODE_TYPE_ICON_SOURCE = {
  text: "/imgs/text.webp",
  image: "/imgs/image.webp",
  video: "/imgs/video.webp",
  audio: "/imgs/audio.webp",
  editing: "/imgs/video.webp",
} as const;

interface AgentCanvasNodeTypeIconProps {
  nodeType: CanvasNodeTypeV2;
  label: string;
}

export function AgentCanvasNodeTypeIcon({
  nodeType,
  label,
}: AgentCanvasNodeTypeIconProps) {
  if (!isAgentCanvasVisibleNodeType(nodeType)) return null;

  return (
    <span
      className="agent-canvas-node__center-icon"
      role="img"
      aria-label={`${label} node type`}
    >
      <img
        src={NODE_TYPE_ICON_SOURCE[nodeType]}
        alt=""
        draggable={false}
      />
    </span>
  );
}
