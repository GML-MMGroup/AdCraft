import type { CanvasTargetReference, ChatNodeReference, DynamicMediaItem, UploadedAsset, WorkflowNode } from "../types";
import {
  canvasTargetReferenceFromAsset,
  canvasTargetReferenceFromDynamicItem,
  canvasTargetReferenceFromNode,
  canvasTargetReferenceFromNodeMention,
  mergeCanvasTargetReferences,
  selectedCanvasTargetReference,
} from "./canvasTargets.ts";
import { isUserVisibleWorkflowNode } from "./visibility.ts";

export type NodeMentionOption = {
  node_id: string;
  node_type?: string;
  title: string;
  mention_text: string;
  target_type?: CanvasTargetReference["target_type"];
  item_id?: string | null;
  asset_id?: string | null;
  semantic_type?: string | null;
  target_reference?: CanvasTargetReference;
};

type CanvasTargetMentionOptions = {
  selectedNode?: WorkflowNode | null;
  dynamicItems?: DynamicMediaItem[];
  outputAssets?: UploadedAsset[];
};

export function filterNodeMentionOptions(nodes: WorkflowNode[], query = ""): NodeMentionOption[] {
  const normalizedQuery = normalizeNodeMentionLookup(query);
  return nodes
    .filter(isUserVisibleWorkflowNode)
    .map(nodeMentionOptionFromNode)
    .filter((option) => {
      if (!normalizedQuery) return true;
      return [option.node_id, option.node_type ?? "", option.title, option.mention_text]
        .some((value) => normalizeNodeMentionLookup(value).includes(normalizedQuery));
    });
}

export function nodeMentionOptionFromNode(node: WorkflowNode): NodeMentionOption {
  const nodeType = node.node_type ?? node.type ?? node.id;
  return {
    node_id: node.id,
    node_type: nodeType,
    title: node.title ?? node.id,
    mention_text: `@${node.id}`,
    target_type: "node",
    semantic_type: nodeType,
    target_reference: canvasTargetReferenceFromNode(node, { source: "mention" }),
  };
}

export function nodeReferenceFromOption(option: NodeMentionOption): ChatNodeReference {
  return {
    node_id: option.node_id,
    node_type: option.node_type,
    mention_text: option.mention_text,
    source: "mention",
  };
}

export function canvasTargetMentionOptions(nodes: WorkflowNode[], options: CanvasTargetMentionOptions = {}): NodeMentionOption[] {
  const result = filterNodeMentionOptions(nodes, "");
  const selectedNode = options.selectedNode && isUserVisibleWorkflowNode(options.selectedNode) ? options.selectedNode : null;
  if (selectedNode) {
    for (const item of options.dynamicItems ?? []) {
      if (!item.itemId) continue;
      result.push({
        node_id: selectedNode.id,
        node_type: selectedNode.node_type ?? selectedNode.type ?? selectedNode.id,
        title: item.displayName || item.itemId,
        mention_text: `@${selectedNode.id}/${item.itemId}`,
        target_type: "item",
        item_id: item.itemId,
        semantic_type: item.semanticType ?? item.itemType,
        target_reference: canvasTargetReferenceFromDynamicItem(selectedNode, item),
      });
      for (const asset of item.outputAssets ?? []) {
        if (!asset.asset_id) continue;
        result.push({
          node_id: selectedNode.id,
          node_type: selectedNode.node_type ?? selectedNode.type ?? selectedNode.id,
          title: asset.filename || asset.asset_id,
          mention_text: `@asset:${asset.asset_id}`,
          target_type: "asset",
          item_id: item.itemId,
          asset_id: asset.asset_id,
          semantic_type: asset.semantic_type ?? item.semanticType ?? item.itemType,
          target_reference: canvasTargetReferenceFromAsset(selectedNode, item, asset),
        });
      }
    }

    for (const asset of options.outputAssets ?? []) {
      if (!asset.asset_id) continue;
      result.push({
        node_id: selectedNode.id,
        node_type: selectedNode.node_type ?? selectedNode.type ?? selectedNode.id,
        title: asset.filename || asset.asset_id,
        mention_text: `@asset:${asset.asset_id}`,
        target_type: "asset",
        item_id: asset.entity_id ?? null,
        asset_id: asset.asset_id,
        semantic_type: asset.semantic_type ?? asset.asset_type,
        target_reference: canvasTargetReferenceFromAsset(selectedNode, null, asset),
      });
    }
  }
  return dedupeMentionOptions(result);
}

export function canvasTargetReferenceFromOption(option: NodeMentionOption): CanvasTargetReference {
  if (option.target_reference) return option.target_reference;
  return {
    target_type: option.target_type ?? "node",
    node_id: option.node_id,
    item_id: option.item_id ?? undefined,
    asset_id: option.asset_id ?? undefined,
    semantic_type: option.semantic_type ?? option.node_type ?? option.node_id,
    intent_scope: "single",
    mention_text: option.mention_text,
    source: "mention",
  };
}

export function mergeNodeReferences(...groups: Array<ChatNodeReference[] | undefined | null>) {
  const result: ChatNodeReference[] = [];
  const seen = new Set<string>();
  for (const group of groups) {
    for (const reference of group ?? []) {
      const key = nodeReferenceKey(reference);
      if (seen.has(key)) continue;
      seen.add(key);
      result.push(reference);
    }
  }
  return result;
}

export function syncNodeMentionReferencesWithText(text: string, references: ChatNodeReference[]) {
  const mentionCounts = new Map<string, number>();
  for (const reference of references) {
    const mention = reference.mention_text?.trim();
    if (!mention || mentionCounts.has(mention)) continue;
    mentionCounts.set(mention, countNodeMentionOccurrences(text, mention));
  }

  return references.filter((reference) => {
    const mention = reference.mention_text?.trim();
    if (!mention) return true;
    const remaining = mentionCounts.get(mention) ?? 0;
    if (remaining <= 0) return false;
    mentionCounts.set(mention, remaining - 1);
    return true;
  });
}

export function buildNodeMentionRequestContext(
  references: ChatNodeReference[] = [],
  options: {
    workflowId?: string | null;
    selectedNodeId?: string | null;
    selectedNodeType?: string | null;
    selectedItemId?: string | null;
    selectedAssetId?: string | null;
    selectedSemanticType?: string | null;
    targetReferences?: CanvasTargetReference[];
  } = {},
) {
  const mentionedNodeIds = references.map((reference) => reference.node_id).filter(Boolean);
  const mentionTargets = references.map(canvasTargetReferenceFromNodeMention);
  const explicitTargets = mergeCanvasTargetReferences(options.targetReferences, mentionTargets);
  const selectedTarget = !explicitTargets.length
    ? selectedCanvasTargetReference({
        nodeId: options.selectedNodeId,
        nodeType: options.selectedNodeType,
        itemId: options.selectedItemId,
        assetId: options.selectedAssetId,
        semanticType: options.selectedSemanticType,
      })
    : null;
  const targetReferences = mergeCanvasTargetReferences(explicitTargets, selectedTarget ? [selectedTarget] : []);
  const primaryTarget = targetReferences[0];
  const selectedNodeId = primaryTarget?.node_id ?? mentionedNodeIds[0] ?? options.selectedNodeId ?? null;
  return {
    node_references: references,
    target_references: targetReferences,
    context: {
      workflow_id: options.workflowId ?? null,
      selected_node_id: selectedNodeId,
      focus_node_id: options.selectedNodeId ?? null,
      selected_item_id: primaryTarget?.item_id ?? options.selectedItemId ?? null,
      selected_asset_id: primaryTarget?.asset_id ?? options.selectedAssetId ?? null,
      mentioned_node_ids: mentionedNodeIds,
    },
  };
}

export function nodeMentionErrorMessage(code?: string | null, fallback?: string | null) {
  if (fallback?.trim()) return fallback.trim();
  if (code === "node_reference_not_found") return "The mentioned node no longer exists.";
  if (code === "node_reference_ambiguous") return "Choose a specific node from the @ menu.";
  if (code === "node_reference_hidden") return "This node cannot be edited directly from chat.";
  if (code === "unsupported_chat_canvas_action") return "This chat action is not supported for the current canvas target.";
  if (code === "node_prompt_update_unsupported") return "This request cannot directly update the node prompt.";
  if (code === "node_prompt_missing") return "The target node has no editable prompt.";
  if (code === "node_prompt_revision_failed" || code === "prompt_revision_failed") return "Prompt revision failed. The old prompt was kept.";
  if (code === "item_prompt_empty" || code === "item_prompt_missing") return "Item prompt cannot be empty.";
  if (code === "item_prompt_update_failed") return "Item prompt update failed. The old prompt was kept.";
  if (code === "node_item_prompt_unsupported") return "This node does not support item-level prompt editing.";
  if (code === "node_locked") return "This node is locked and cannot be edited right now.";
  if (code === "execution_already_running") return "This workflow already has a running task.";
  if (code === "execution_start_failed") return "Prompt updated, but execution could not be started.";
  if (code === "target_reference_not_found") return "The selected target no longer exists.";
  if (code === "target_reference_ambiguous") return "Choose a more specific node, item, or asset from the @ menu.";
  if (code === "target_reference_conflict") return "The selected target references conflict. Choose the target again.";
  if (code === "target_reference_hidden") return "This target cannot be edited directly from chat.";
  if (code === "target_node_not_found") return "The selected node no longer exists.";
  if (code === "target_item_not_found") return "The selected item no longer exists or was refreshed.";
  if (code === "target_asset_not_found") return "The selected asset no longer exists or was archived.";
  if (code === "target_owner_mismatch") return "The selected asset does not belong to the selected item or node.";
  if (code === "item_revision_start_failed") return "Item regeneration could not be started. The old preview was kept.";
  if (code === "semantic_type_mismatch") return "The selected item does not match the requested media type.";
  if (code === "unsupported_target_type") return "This target type is not supported yet.";
  if (code === "unsupported_target_scope") return "This target does not support the requested scope.";
  if (code === "unsupported_target_action") return "This target action is not available yet.";
  if (code === "specialist_not_supported") return "No specialist is available for this target yet.";
  if (code === "specialist_output_invalid") return "The specialist result could not be applied. The canvas was kept unchanged.";
  if (code === "specialist_real_mode_unavailable") return "Real specialist execution is not configured. Existing previews were kept.";
  if (code === "specialist_execution_failed") return "Specialist execution failed. Existing prompts and previews were kept.";
  return "Agent conversation failed.";
}

function nodeReferenceKey(reference: ChatNodeReference) {
  return [
    reference.node_id,
    reference.node_type ?? "",
    reference.mention_text ?? "",
    reference.source,
  ].join(":");
}

function normalizeNodeMentionLookup(value: string) {
  return value.toLowerCase().replace(/^@/, "").replace(/[^a-z0-9\u4e00-\u9fa5]+/g, "");
}

function dedupeMentionOptions(options: NodeMentionOption[]) {
  const seen = new Set<string>();
  return options.filter((option) => {
    const key = [
      option.target_type ?? "node",
      option.node_id,
      option.item_id ?? "",
      option.asset_id ?? "",
      option.mention_text,
    ].join(":");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function countNodeMentionOccurrences(text: string, mention: string) {
  let count = 0;
  let index = 0;
  while (index < text.length) {
    const nextIndex = text.indexOf(mention, index);
    if (nextIndex < 0) break;
    count += 1;
    index = nextIndex + mention.length;
  }
  return count;
}
