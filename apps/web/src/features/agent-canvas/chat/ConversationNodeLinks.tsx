import type { CanvasNodeV2 } from "../../../types-v2.ts";
import type { ConversationCanvasLocation } from "./conversationCanvasLinks.ts";

type ConversationNodeLinksVariant = "result" | "related" | "receipt";

function countLabel(count: number, noun: string): string | null {
  if (!count) return null;
  return `${count} ${count === 1 ? "node" : "nodes"} ${noun}`;
}

function resultSummary(location: ConversationCanvasLocation): string {
  return [
    countLabel(location.createdNodeIds.length, "created"),
    countLabel(location.updatedNodeIds.length, "updated"),
    countLabel(location.deletedNodeIds.length, "deleted"),
  ].filter(Boolean).join(" · ");
}

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

  const summary = resultSummary(location);
  if (!summary) return null;
  const isReceipt = variant === "receipt";
  return (
    <div className={`agent-chat__node-links agent-chat__node-links--${variant}`}>
      <span>{summary}</span>
      {navigableNodeIds.length ? (
        <button
          type="button"
          aria-label={isReceipt ? "View canvas changes" : "View result nodes on canvas"}
          onClick={() => onViewNodes(navigableNodeIds)}
        >
          {isReceipt ? "View changes" : "View on canvas"}
        </button>
      ) : null}
    </div>
  );
}
