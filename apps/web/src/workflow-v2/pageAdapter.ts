import { useMemo } from "react";
import { isWorkflowV2, normalizeWorkflowV2 } from "../api/v2Normalizers.ts";
import type { WorkflowEdge, WorkflowGraph, WorkflowNode } from "../types.ts";
import type { AssetVersionV2, WorkflowItemV2, WorkflowNodeV2, WorkflowSlotV2, WorkflowV2 } from "../types-v2.ts";
import { isWorkflowV2Graph } from "../workflowSchema.ts";

export { isV2WorkflowId } from "../api/v1WorkflowGuard.ts";
export { isWorkflowV2Graph, workflowSchemaVersionOfGraph } from "../workflowSchema.ts";

export type WorkflowV2PageModel = {
  isV2: boolean;
  workflow: WorkflowGraph | null;
  workflowV2: WorkflowV2 | null;
};

export function useWorkflowV2Model(workflow: unknown): WorkflowV2PageModel {
  return useMemo(() => {
    if (isWorkflowV2(workflow)) {
      const workflowV2 = normalizeWorkflowV2(workflow);
      return { isV2: true, workflow: workflowV2ToWorkflowGraph(workflowV2), workflowV2 };
    }
    if (isWorkflowGraph(workflow)) {
      if (isWorkflowV2Graph(workflow)) {
        return { isV2: true, workflow, workflowV2: null };
      }
      return { isV2: false, workflow, workflowV2: null };
    }
    return { isV2: false, workflow: null, workflowV2: null };
  }, [workflow]);
}

function isWorkflowGraph(value: unknown): value is WorkflowGraph {
  return Boolean(
    value &&
      typeof value === "object" &&
      "workflow_id" in value &&
      typeof value.workflow_id === "string" &&
      "nodes" in value &&
      Array.isArray(value.nodes) &&
      "edges" in value &&
      Array.isArray(value.edges),
  );
}

export function workflowV2ToWorkflowGraph(workflow: WorkflowV2): WorkflowGraph {
  const itemsByNodeId = groupBy(workflow.items, (item) => item.node_id);
  const slotsByItemId = groupBy(workflow.slots, (slot) => slot.item_id);
  const graphNodes = normalizeLegacyStoryboardUpstreamDefaultPositions(workflow.nodes);
  return {
    workflow_id: workflow.workflow_id,
    name: workflow.name,
    description: workflow.description,
    status: aggregateWorkflowStatus(workflow),
    metadata: {
      ...(workflow.metadata ?? {}),
      workflow_schema_version: 2,
      v2_prompt: workflow.prompt,
      v2_runtime: workflow.runtime,
    },
    nodes: graphNodes.map((node): WorkflowNode => {
      const items = itemsByNodeId.get(node.node_id) ?? [];
      const slots = items.flatMap((item) => slotsByItemId.get(item.item_id) ?? []);
      const assetVersions = assetVersionsForNode(workflow.asset_versions, node.node_id, items, slots);
      return {
        id: node.node_id,
        workflow_id: workflow.workflow_id,
        type: node.node_type,
        node_type: node.node_type,
        title: node.title,
        description: v2NodeDescription(items, slots),
        position: node.position,
        status: node.status,
        prompt: firstItemPrompt(items) ?? workflow.prompt,
        input_context: {
          v2_items: items,
          v2_slots: slots,
          v2_runtime: workflow.runtime,
        },
        output: {
          v2_item_count: items.length,
          v2_slot_count: slots.length,
          v2_completed_slot_count: slots.filter((slot) => slot.status === "completed" || slot.status === "skipped").length,
        },
        metadata: {
          ...(node.metadata ?? {}),
          workflow_schema_version: 2,
          v2_node: node,
          v2_items: items,
          v2_slots: slots,
          v2_asset_versions: assetVersions,
        },
      };
    }),
    edges: workflow.edges.map((edge): WorkflowEdge => ({
      id: edge.id,
      workflow_id: workflow.workflow_id,
      source: edge.source,
      target: edge.target,
      source_node_id: edge.source,
      target_node_id: edge.target,
      source_handle: edge.source_handle,
      target_handle: edge.target_handle,
      label: edge.edge_kind === "display_flow" ? "Display flow" : edge.edge_kind,
      required: false,
      mapping: [],
      updated_at: workflow.updated_at,
      created_at: workflow.created_at,
    })),
    created_at: workflow.created_at,
    updated_at: workflow.updated_at,
  };
}

const LEGACY_STORYBOARD_UPSTREAM_DEFAULT_POSITIONS = {
  product: { x: 320, y: -180 },
  character: { x: 320, y: 0 },
  scene: { x: 320, y: 180 },
} as const;

function normalizeLegacyStoryboardUpstreamDefaultPositions(nodes: WorkflowNodeV2[]): WorkflowNodeV2[] {
  const byId = new Map(nodes.map((node) => [node.node_id, node]));
  const product = byId.get("product-generation");
  const character = byId.get("character-generation");
  const scene = byId.get("scene-generation");
  if (
    !samePosition(product?.position, LEGACY_STORYBOARD_UPSTREAM_DEFAULT_POSITIONS.product) ||
    !samePosition(character?.position, LEGACY_STORYBOARD_UPSTREAM_DEFAULT_POSITIONS.character) ||
    !samePosition(scene?.position, LEGACY_STORYBOARD_UPSTREAM_DEFAULT_POSITIONS.scene)
  ) {
    return nodes;
  }

  return nodes.map((node) => {
    if (node.node_id === "character-generation") return { ...node, position: { ...LEGACY_STORYBOARD_UPSTREAM_DEFAULT_POSITIONS.product } };
    if (node.node_id === "scene-generation") return { ...node, position: { ...LEGACY_STORYBOARD_UPSTREAM_DEFAULT_POSITIONS.character } };
    if (node.node_id === "product-generation") return { ...node, position: { ...LEGACY_STORYBOARD_UPSTREAM_DEFAULT_POSITIONS.scene } };
    return node;
  });
}

function samePosition(left: { x: number; y: number } | undefined, right: { x: number; y: number }) {
  return left?.x === right.x && left.y === right.y;
}

function assetVersionsForNode(
  assetVersions: AssetVersionV2[],
  nodeId: string,
  items: WorkflowItemV2[],
  slots: WorkflowSlotV2[],
) {
  const itemIds = new Set(items.map((item) => item.item_id));
  const slotIds = new Set(slots.map((slot) => slot.slot_id));
  const referenceIds = new Set<string>();
  for (const slot of slots) {
    for (const id of slot.explicit_reference_ids ?? []) referenceIds.add(id);
    for (const id of slot.media_prompt_asset_ids ?? []) referenceIds.add(id);
  }
  return assetVersions.filter((asset) =>
    asset.node_id === nodeId ||
    Boolean(asset.item_id && itemIds.has(asset.item_id)) ||
    Boolean(asset.slot_id && slotIds.has(asset.slot_id)) ||
    referenceIds.has(asset.asset_id) ||
    referenceIds.has(asset.version_id),
  );
}

function groupBy<T>(items: T[], key: (item: T) => string) {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const value = key(item);
    groups.set(value, [...(groups.get(value) ?? []), item]);
  }
  return groups;
}

function firstItemPrompt(items: WorkflowItemV2[]) {
  return items.find((item) => item.item_prompt)?.item_prompt;
}

function v2NodeDescription(items: WorkflowItemV2[], slots: WorkflowSlotV2[]) {
  if (!items.length) return "V2 region waiting for backend-created items";
  const completed = slots.filter((slot) => slot.status === "completed" || slot.status === "skipped").length;
  return `${items.length} item${items.length === 1 ? "" : "s"} · ${completed}/${slots.length} slots`;
}

function aggregateWorkflowStatus(workflow: WorkflowV2) {
  if (workflow.runtime?.running_node_ids.length || workflow.runtime?.running_item_ids.length || workflow.runtime?.running_slot_ids.length) return "running";
  if (workflow.runtime?.waiting_node_ids.length || workflow.runtime?.waiting_item_ids.length || workflow.runtime?.waiting_slot_ids.length) return "waiting";
  if (workflow.runtime?.failed_slot_ids.length) return "partial_failed";
  if (workflow.nodes.every((node) => node.status === "completed")) return "completed";
  return "ready";
}
