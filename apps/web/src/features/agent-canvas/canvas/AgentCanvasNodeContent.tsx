import type { CanvasNodeV2 } from "../../../types-v2.ts";
import { AgentCanvasNodeTypeIcon } from "./AgentCanvasNodeTypeIcon.tsx";

function nonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function agentCanvasNodeDisplayText(node: CanvasNodeV2): string | null {
  if (node.node_type === "text") {
    return nonEmptyString(node.structured_content.content)
      ?? nonEmptyString(node.structured_content.text);
  }
  if (node.node_type === "image" || node.node_type === "video") {
    return nonEmptyString(node.generation_prompt);
  }
  return null;
}

interface AgentCanvasNodeContentProps {
  node: CanvasNodeV2;
  iconLabel: string;
}

export function AgentCanvasNodeContent({
  node,
  iconLabel,
}: AgentCanvasNodeContentProps) {
  const copy = agentCanvasNodeDisplayText(node);
  if (copy) {
    return (
      <div className="agent-canvas-node__content">
        <p>{copy}</p>
      </div>
    );
  }

  return (
    <div className="agent-canvas-node__media-placeholder">
      <AgentCanvasNodeTypeIcon nodeType={node.node_type} label={iconLabel} />
    </div>
  );
}
