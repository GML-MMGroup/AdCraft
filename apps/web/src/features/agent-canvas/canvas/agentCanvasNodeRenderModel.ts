import type { NodeProps } from "@xyflow/react";

import type {
  NodeRuntimeV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import type { AgentCanvasFlowNode } from "./AgentCanvasNode.tsx";

type AgentCanvasNodeRendererProps = NodeProps<AgentCanvasFlowNode>;

export function sameAgentCanvasAssetPresentation(
  previous: ProjectAssetSummaryV2 | null | undefined,
  next: ProjectAssetSummaryV2 | null | undefined,
): boolean {
  if (previous === next) return true;
  if (!previous || !next) return false;
  return previous.asset_id === next.asset_id
    && previous.version_id === next.version_id
    && previous.status === next.status
    && previous.checksum === next.checksum
    && previous.display_name === next.display_name
    && previous.media_url === next.media_url
    && previous.preview_url === next.preview_url
    && previous.width === next.width
    && previous.height === next.height
    && previous.duration_seconds === next.duration_seconds;
}

export function sameAgentCanvasRuntimeCardPresentation(
  previous: NodeRuntimeV2 | null | undefined,
  next: NodeRuntimeV2 | null | undefined,
): boolean {
  if (previous === next) return true;
  if (!previous || !next) return false;
  return previous.visible_status === next.visible_status
    && previous.waiting_reason === next.waiting_reason
    && previous.blocked_by_node_ids.length === next.blocked_by_node_ids.length
    && previous.blocked_by_node_ids.every((nodeId, index) => nodeId === next.blocked_by_node_ids[index])
    && previous.error?.code === next.error?.code
    && previous.error?.message === next.error?.message;
}

export function areAgentCanvasNodePropsEqual(
  previous: AgentCanvasNodeRendererProps,
  next: AgentCanvasNodeRendererProps,
): boolean {
  const previousData = previous.data;
  const nextData = next.data;
  const sameNode = previousData.node === nextData.node || (
    previousData.node.node_id === nextData.node.node_id
    && previousData.node.workflow_id === nextData.node.workflow_id
    && previousData.node.revision === nextData.node.revision
    && previousData.node.status === nextData.node.status
    && previousData.node.output_asset_id === nextData.node.output_asset_id
    && previousData.node.prompt_preparation?.occurrence_id === nextData.node.prompt_preparation?.occurrence_id
    && previousData.node.prompt_preparation?.character_phase === nextData.node.prompt_preparation?.character_phase
    && previousData.node.prompt_preparation?.role_variant === nextData.node.prompt_preparation?.role_variant
  );
  const sameWorkbench = previousData.workbenchActive === nextData.workbenchActive
    && (!nextData.workbenchActive
      || previousData.renderWorkbench === nextData.renderWorkbench);
  const sameRuntime = nextData.workbenchActive
    ? previousData.runtime === nextData.runtime
    : sameAgentCanvasRuntimeCardPresentation(previousData.runtime, nextData.runtime);

  return previous.id === next.id
    && previous.selected === next.selected
    && previous.isConnectable === next.isConnectable
    && sameNode
    && sameAgentCanvasAssetPresentation(previousData.asset, nextData.asset)
    && sameRuntime
    && sameWorkbench
    && previousData.onOpenVideoPreview === nextData.onOpenVideoPreview
    && previousData.onOpenEditing === nextData.onOpenEditing
    && previousData.showInputHandle === nextData.showInputHandle
    && previousData.showOutputHandle === nextData.showOutputHandle;
}
