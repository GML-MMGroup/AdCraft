import type {
  AssetReferenceSuggestion,
  CanvasTargetIntentScope,
  CanvasTargetReference,
  CanvasTargetReferenceSource,
  ChatNodeReference,
  DynamicMediaItem,
  UploadedAsset,
  WorkflowNode,
} from "../types";

type NodeLike = Pick<WorkflowNode, "id" | "node_type" | "type"> & { title?: string | null };
type ItemLike = Pick<DynamicMediaItem, "itemId" | "itemType" | "semanticType">;
type AssetLike = Pick<UploadedAsset, "asset_id" | "semantic_type" | "entity_id" | "asset_type">;

export function canvasTargetReferenceFromNodeMention(reference: ChatNodeReference): CanvasTargetReference {
  return {
    target_type: "node",
    node_id: reference.node_id,
    semantic_type: reference.node_type ?? reference.node_id,
    intent_scope: "single",
    mention_text: reference.mention_text,
    source: "mention",
  };
}

export function canvasTargetReferenceFromNode(
  node: NodeLike,
  options: { source?: CanvasTargetReferenceSource; mentionText?: string | null } = {},
): CanvasTargetReference {
  return {
    target_type: "node",
    node_id: node.id,
    semantic_type: workflowNodeType(node),
    intent_scope: "single",
    mention_text: options.mentionText ?? `@${node.id}`,
    source: options.source ?? "selected_node",
  };
}

export function canvasTargetReferenceFromDynamicItem(
  node: NodeLike,
  item: ItemLike,
  options: { source?: CanvasTargetReferenceSource; mentionText?: string | null } = {},
): CanvasTargetReference {
  return {
    target_type: "item",
    node_id: node.id,
    item_id: item.itemId,
    semantic_type: item.semanticType ?? item.itemType,
    intent_scope: "single",
    mention_text: options.mentionText ?? `@${node.id}/${item.itemId}`,
    source: options.source ?? "mention",
  };
}

export function canvasTargetReferenceFromAsset(
  node: NodeLike | null | undefined,
  item: ItemLike | null | undefined,
  asset: AssetLike,
  options: { source?: CanvasTargetReferenceSource; mentionText?: string | null } = {},
): CanvasTargetReference {
  return {
    target_type: "asset",
    node_id: node?.id ?? null,
    item_id: item?.itemId ?? asset.entity_id ?? null,
    asset_id: asset.asset_id,
    semantic_type: asset.semantic_type ?? item?.semanticType ?? item?.itemType ?? asset.asset_type,
    intent_scope: "single",
    mention_text: options.mentionText ?? `@asset:${asset.asset_id}`,
    source: options.source ?? "mention",
  };
}

export function canvasTargetReferenceFromAssetSuggestion(
  suggestion: AssetReferenceSuggestion,
  options: { nodeId?: string | null; mentionText?: string | null } = {},
): CanvasTargetReference | null {
  if (!suggestion.asset_id) return null;
  return {
    target_type: "asset",
    node_id: options.nodeId ?? null,
    asset_id: suggestion.asset_id,
    semantic_type: suggestion.semantic_type ?? suggestion.asset_type ?? null,
    intent_scope: "single",
    mention_text: options.mentionText ?? suggestion.mention_text ?? `@asset:${suggestion.asset_id}`,
    source: "mention",
  };
}

export function selectedCanvasTargetReference(options: {
  nodeId?: string | null;
  nodeType?: string | null;
  itemId?: string | null;
  assetId?: string | null;
  semanticType?: string | null;
}): CanvasTargetReference | null {
  if (options.assetId) {
    return {
      target_type: "asset",
      node_id: options.nodeId ?? null,
      item_id: options.itemId ?? null,
      asset_id: options.assetId,
      semantic_type: options.semanticType ?? null,
      intent_scope: "single",
      source: "selected_asset",
    };
  }
  if (options.nodeId && options.itemId) {
    return {
      target_type: "item",
      node_id: options.nodeId,
      item_id: options.itemId,
      semantic_type: options.semanticType ?? null,
      intent_scope: "single",
      source: "selected_item",
    };
  }
  if (options.nodeId) {
    return {
      target_type: "node",
      node_id: options.nodeId,
      semantic_type: options.nodeType ?? options.semanticType ?? options.nodeId,
      intent_scope: "single",
      source: "selected_node",
    };
  }
  return null;
}

export function mergeCanvasTargetReferences(...groups: Array<CanvasTargetReference[] | undefined | null>) {
  const result: CanvasTargetReference[] = [];
  const seen = new Set<string>();
  for (const group of groups) {
    for (const reference of group ?? []) {
      const key = canvasTargetReferenceKey(reference);
      if (seen.has(key)) continue;
      seen.add(key);
      result.push(reference);
    }
  }
  return result;
}

export function syncCanvasTargetReferencesWithText(text: string, references: CanvasTargetReference[]) {
  const mentionCounts = new Map<string, number>();
  for (const reference of references) {
    const mention = reference.mention_text?.trim();
    if (!mention || mentionCounts.has(mention)) continue;
    mentionCounts.set(mention, countMentionOccurrences(text, mention));
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

export function targetReferenceIntentScopeFromPrompt(prompt: string): CanvasTargetIntentScope {
  const normalized = prompt.toLowerCase();
  if (/(从这里往后|从.+往后|往后跑|downstream|from here|from this|after this)/i.test(normalized)) return "downstream";
  if (/(全部|所有|每个|all\b|every\b|entire\b)/i.test(normalized)) return "all_in_node";
  return "single";
}

export function applyCanvasTargetIntentScope(references: CanvasTargetReference[], prompt: string) {
  const scope = targetReferenceIntentScopeFromPrompt(prompt);
  return references.map((reference) => ({
    ...reference,
    intent_scope: scope === "single" ? reference.intent_scope ?? "single" : scope,
  }));
}

export function canvasTargetReferenceKey(reference: CanvasTargetReference) {
  return [
    reference.target_type,
    reference.node_id ?? "",
    reference.item_id ?? "",
    reference.asset_id ?? "",
    reference.semantic_type ?? "",
    reference.mention_text ?? "",
    reference.source ?? "",
  ].join(":");
}

function workflowNodeType(node: Pick<WorkflowNode, "id" | "node_type" | "type">) {
  return node.node_type ?? node.type ?? node.id;
}

function countMentionOccurrences(text: string, mention: string) {
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
