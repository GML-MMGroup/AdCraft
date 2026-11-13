import type {
  CanvasNodeStatusV2,
  CanvasNodeV2,
} from "../../../types-v2.ts";
import { AgentCanvasNodeIcon } from "./AgentCanvasNodeIcon.tsx";
import { useTranslation } from "../../../i18n/useTranslation.ts";
import { canvasNodeDisplayName } from "./canvasNodeDisplayName.ts";

interface AgentCanvasNodeHeaderProps {
  node: CanvasNodeV2;
  status: CanvasNodeStatusV2;
  dimensions?: { width: number; height: number } | null;
  activityLabel?: string;
}

export function AgentCanvasNodeHeader({
  node,
  status,
  dimensions,
  activityLabel,
}: AgentCanvasNodeHeaderProps) {
  const t = useTranslation();
  const name = canvasNodeDisplayName(node, t);
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
      {activityLabel ? (
        <span className="agent-canvas-node__header-run-state">{activityLabel}</span>
      ) : showDimensions && dimensions ? (
        <span className="agent-canvas-node__header-dimensions">
          {dimensions.width} × {dimensions.height}
        </span>
      ) : null}
    </div>
  );
}
