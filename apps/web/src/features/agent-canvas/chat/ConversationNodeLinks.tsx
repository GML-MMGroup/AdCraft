import type { CanvasNodeV2 } from "../../../types-v2.ts";
import type { ConversationCanvasLocation } from "./conversationCanvasLinks.ts";

type ConversationNodeLinksVariant = "result" | "related" | "receipt";

export function ConversationNodeLinks({
  location,
  nodes,
  variant,
  onViewNodes,
}: {
  location: ConversationCanvasLocation;
  nodes: CanvasNodeV2[];
  variant: ConversationNodeLinksVariant;
  onViewNodes: (nodeIds: string[]) => void;
}) {
  const nodesById = new Map(nodes.map((node) => [node.node_id, node]));
  const navigableNodeIds = location.navigableNodeIds.filter((nodeId) => nodesById.has(nodeId));
  if (variant === "related") {
    const names = navigableNodeIds.map((nodeId) => nodesById.get(nodeId)?.title?.trim()).filter(Boolean);
    if (!names.length) return null;
    return (
      <button
        type="button"
        className="agent-chat__node-links agent-chat__node-links--related"
        aria-label="View related nodes on canvas"
        onClick={() => onViewNodes(navigableNodeIds)}
      >
        {`Related · ${names.join(" · ")}`}
      </button>
    );
  }

  const isReceipt = variant === "receipt";
  if (!navigableNodeIds.length) return null;
  return (
    <div className={`agent-chat__node-links agent-chat__node-links--${variant}`}>
      <button
        type="button"
        aria-label={isReceipt ? "View canvas changes" : "View result nodes on canvas"}
        onClick={() => onViewNodes(navigableNodeIds)}
      >
        {isReceipt ? "View changes" : "View on canvas"}
      </button>
    </div>
  );
}
