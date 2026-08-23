import type {
  CanvasNodeStatusV2,
  CanvasNodeV2,
} from "../../../types-v2.ts";
import { AgentCanvasNodeIcon } from "./AgentCanvasNodeIcon.tsx";
import { creativeRoleDisplayName } from "./creativeRoleDisplayName.ts";

interface AgentCanvasNodeHeaderProps {
  node: CanvasNodeV2;
  status: CanvasNodeStatusV2;
  dimensions?: { width: number; height: number } | null;
}

export function AgentCanvasNodeHeader({
  node,
  status,
  dimensions,
}: AgentCanvasNodeHeaderProps) {
  const name = creativeRoleDisplayName(node.creative_role);
  const showDimensions = node.node_type === "image" || node.node_type === "video";

  return (
    <div className={`agent-canvas-node__header agent-canvas-node__header--${status}`}>
      <span
        className="agent-canvas-node__header-icon"
        role="img"
        aria-label={`${name} node type`}
      >
        <AgentCanvasNodeIcon nodeType={node.node_type} />
      </span>
      <span className="agent-canvas-node__header-name">{name}</span>
      {showDimensions && dimensions ? (
        <span className="agent-canvas-node__header-dimensions">
          {dimensions.width} × {dimensions.height}
        </span>
      ) : null}
    </div>
  );
}
