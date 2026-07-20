import type {
  AssetLibraryEntitySummary,
  AssetLibraryReference,
  AssetReferenceSuggestion,
  AssetReferenceSuggestCategory,
  AssetUploadOptions,
  UploadedAsset,
} from "../types";

export const ASSET_MENTION_CATEGORIES: Array<{ key: AssetReferenceSuggestCategory; label: string; types?: string[] }> = [
  { key: "all", label: "All" },
  { key: "character", label: "Characters", types: ["character"] },
  { key: "scene", label: "Scenes", types: ["scene"] },
  { key: "style_reference", label: "Style", types: ["style_reference"] },
  { key: "bgm", label: "BGM", types: ["bgm", "audio"] },
  { key: "video", label: "Video", types: ["video", "video_clip"] },
  { key: "storyboard", label: "Storyboard", types: ["storyboard", "storyboard_shot"] },
  { key: "canvas", label: "Current canvas", types: ["canvas"] },
];

export type ReferenceScope = "global_prompt" | "node_workbench" | "item_revision";

export type AssetReferenceTargetContext = {
  referenceScope?: ReferenceScope;
  nodeId?: string | null;
  nodeType?: string | null;
  itemId?: string | null;
  semanticType?: string | null;
  referenceMode?: AssetLibraryReference["reference_mode"];
};

export const PROMPT_TO_WORKFLOW_PRODUCT_NODE_ID = "product-generation";
export const PROMPT_TO_WORKFLOW_PRODUCT_ITEM_ID = "product-1";

export const PROMPT_TO_WORKFLOW_PRODUCT_UPLOAD_OPTIONS: AssetUploadOptions = {
  asset_role: "product",
  entity_type: "product",
  semantic_type: "product_reference",
  use_as_prompt: true,
};

export function assetReferenceKey(reference: AssetLibraryReference) {
  return [
    reference.reference_source ?? "asset_library",
    reference.entity_id ?? "",
    reference.asset_id ?? "",
    reference.target_node_id ?? "",
    reference.target_entity_id ?? "",
    reference.target_item_id ?? "",
    reference.target_slot_id ?? "",
    reference.reference_kind ?? "",
  ].join(":");
}

export function mergeAssetReferences(...groups: Array<AssetLibraryReference[] | undefined | null>) {
  const result: AssetLibraryReference[] = [];
  const seen = new Set<string>();
  for (const group of groups) {
    for (const reference of group ?? []) {
      const key = assetReferenceKey(reference);
      if (seen.has(key)) continue;
      seen.add(key);
      result.push(reference);
    }
  }
  return result;
}

export function assetReferenceFromSuggestion(
  suggestion: AssetReferenceSuggestion,
  options: AssetReferenceTargetContext = {},
): AssetLibraryReference {
  const mentionText = suggestion.mention_text?.trim() || `@${suggestion.display_name}`;
  const referenceScope = options.referenceScope ?? "global_prompt";
  const targetPatch =
    referenceScope === "node_workbench" && options.nodeId
      ? {
        target_node_id: options.nodeId,
        target_node_type: options.nodeType ?? null,
        target_node_ids: [options.nodeId],
      }
      : referenceScope === "item_revision" && options.nodeId
        ? {
            target_node_id: options.nodeId,
            target_node_type: options.nodeType ?? null,
            target_node_ids: [options.nodeId],
            target_entity_id: options.itemId ?? null,
            item_id: options.itemId ?? null,
          }
        : {};
  const reference: AssetLibraryReference = {
    reference_source: suggestion.reference_source,
    entity_id: suggestion.reference_source === "asset_library" ? suggestion.entity_id ?? null : null,
    asset_id: suggestion.reference_source === "canvas_asset"
      ? suggestion.asset_id ?? null
      : assetLibraryReferenceAssetId(suggestion.asset_id),
    mention_text: mentionText.startsWith("@") ? mentionText : `@${mentionText}`,
    display_name: suggestion.display_name,
    role: suggestion.role ?? defaultAssetReferenceRole(suggestion),
    use_as_prompt: true,
    ...targetPatch,
  };
  if (options.referenceMode) {
    reference.reference_mode = options.referenceMode;
  }
  return reference;
}

export function sanitizeGlobalAssetReferences(references: AssetLibraryReference[], selectedAssets: UploadedAsset[] = []): AssetLibraryReference[] {
  return references.map((reference) => {
    const {
      target_node_id: _targetNodeId,
      target_node_ids: _targetNodeIds,
      target_node_type: _targetNodeType,
      target_entity_id: _targetEntityId,
      target_item_id: _targetItemId,
      target_slot_id: _targetSlotId,
      item_id: _itemId,
      reference_mode: _referenceMode,
      ...globalReference
    } = reference;
    return sanitizeAssetLibraryReferenceAssetId(globalReference, selectedAssets);
  });
}

export function buildV2PromptPlanAssetReferences(
  references: AssetLibraryReference[],
  selectedAssets: UploadedAsset[] = [],
): AssetLibraryReference[] {
  return references.map((reference) => {
    const normalizedReference = sanitizeAssetLibraryReferenceAssetId(reference, selectedAssets);
    if (!isProductReference(normalizedReference)) {
      return sanitizeGlobalAssetReferences([normalizedReference], selectedAssets)[0];
    }

    const explicitTarget = hasExplicitReferenceTarget(normalizedReference);
    return {
      ...normalizedReference,
      role: "product_reference",
      reference_kind: "product_reference",
      use_as_prompt: normalizedReference.use_as_prompt ?? true,
      ...(explicitTarget
        ? {}
        : {
            target_node_id: PROMPT_TO_WORKFLOW_PRODUCT_NODE_ID,
            target_item_id: PROMPT_TO_WORKFLOW_PRODUCT_ITEM_ID,
          }),
    };
  });
}

export function selectedAssetsForV2PromptPlan(
  selectedAssets: UploadedAsset[],
  planReferences: AssetLibraryReference[],
): UploadedAsset[] {
  const productReferences = planReferences.filter((reference) =>
    isProductReference(reference) &&
    reference.target_node_id === PROMPT_TO_WORKFLOW_PRODUCT_NODE_ID &&
    reference.target_item_id === PROMPT_TO_WORKFLOW_PRODUCT_ITEM_ID,
  );
  if (!productReferences.length) return selectedAssets;
  return selectedAssets.filter((asset) => !productReferences.some((reference) => uploadedAssetMatchesReference(asset, reference)));
}

export function assetReferenceFromLibraryEntity(
  entity: AssetLibraryEntitySummary,
  patch: Partial<AssetLibraryReference> = {},
): AssetLibraryReference {
  return {
    reference_source: "asset_library",
    entity_id: entity.entity_id,
    asset_id: null,
    mention_text: `@${entity.display_name}`,
    display_name: entity.display_name,
    role: defaultAssetReferenceRole(entity),
    use_as_prompt: true,
    ...patch,
  };
}

function sanitizeAssetLibraryReferenceAssetId(reference: AssetLibraryReference, selectedAssets: UploadedAsset[]) {
  if (reference.reference_source !== "asset_library") return reference;
  const assetId = reference.asset_id?.trim();
  if (!assetId) return { ...reference, asset_id: reference.asset_id ?? null };
  if (!isFrontendUploadAssetId(assetId)) {
    return { ...reference, asset_id: assetLibraryReferenceAssetId(assetId) };
  }
  return {
    ...reference,
    asset_id: libraryAssetIdForUploadedAsset(assetId, reference.entity_id, selectedAssets),
  };
}

function libraryAssetIdForUploadedAsset(uploadAssetId: string, entityId: string | null | undefined, selectedAssets: UploadedAsset[]) {
  const matchingAsset = selectedAssets.find((asset) =>
    asset.asset_id === uploadAssetId ||
    Boolean(entityId && uploadedAssetEntityId(asset) === entityId),
  );
  return firstLibraryAssetId(matchingAsset) ?? null;
}

function firstLibraryAssetId(asset: UploadedAsset | undefined) {
  if (!asset) return null;
  for (const id of asset.library_asset_ids ?? []) {
    const safeId = assetLibraryReferenceAssetId(id);
    if (safeId) return safeId;
  }
  for (const libraryAsset of asset.library_assets ?? []) {
    const safeId = assetLibraryReferenceAssetId(libraryAsset.asset_id);
    if (safeId) return safeId;
  }
  for (const libraryAsset of asset.library_entity?.assets ?? []) {
    const safeId = assetLibraryReferenceAssetId(libraryAsset.asset_id);
    if (safeId) return safeId;
  }
  return null;
}

function uploadedAssetEntityId(asset: UploadedAsset) {
  return asset.library_entity_id ?? asset.library_entity?.entity_id ?? asset.entity_id ?? null;
}

function assetLibraryReferenceAssetId(value: string | null | undefined) {
  if (!value?.trim()) return null;
  const assetId = value.trim();
  return isFrontendUploadAssetId(assetId) ? null : assetId;
}

function isFrontendUploadAssetId(assetId: string) {
  return /^asset_/i.test(assetId);
}

export function defaultAssetReferenceRole(value: Pick<AssetReferenceSuggestion, "entity_type" | "asset_type" | "semantic_type"> | Pick<AssetLibraryEntitySummary, "entity_type" | "semantic_type">) {
  const entityType = String(value.entity_type ?? "").toLowerCase();
  const semanticType = String(value.semantic_type ?? "").toLowerCase();
  const assetType = "asset_type" in value ? String(value.asset_type ?? "").toLowerCase() : "";
  if (entityType === "product" || semanticType === "product_reference") return "product_reference";
  if (entityType === "character") return "character_reference";
  if (entityType === "scene") return "scene_reference";
  if (entityType === "style_reference" || semanticType === "style_reference") return "style_reference";
  if (entityType === "bgm" || semanticType === "bgm" || assetType === "audio") return "bgm_reference";
  if (entityType === "video" || entityType === "video_clip" || assetType === "video") return "video_reference";
  if (entityType === "storyboard" || entityType === "storyboard_shot" || semanticType.startsWith("storyboard")) return "storyboard_reference";
  return "general_reference";
}

function isProductReference(reference: AssetLibraryReference) {
  return reference.role === "product_reference" || reference.reference_kind === "product_reference";
}

function hasExplicitReferenceTarget(reference: AssetLibraryReference) {
  return Boolean(
    reference.target_node_id ||
      reference.target_node_ids?.length ||
      reference.target_entity_id ||
      reference.target_item_id ||
      reference.target_slot_id ||
      reference.item_id,
  );
}

function uploadedAssetMatchesReference(asset: UploadedAsset, reference: AssetLibraryReference) {
  const entityId = uploadedAssetEntityId(asset);
  if (reference.entity_id && entityId === reference.entity_id) return true;
  if (!reference.asset_id) return false;
  return uploadedAssetReferenceAssetIds(asset).some((assetId) => assetId === reference.asset_id);
}

function uploadedAssetReferenceAssetIds(asset: UploadedAsset) {
  const ids = new Set<string>();
  const add = (value?: string | null) => {
    if (!value?.trim()) return;
    ids.add(value.trim());
    const libraryId = assetLibraryReferenceAssetId(value);
    if (libraryId) ids.add(libraryId);
  };
  add(asset.asset_id);
  add(asset.library_asset_id);
  for (const id of asset.library_asset_ids ?? []) add(id);
  for (const libraryAsset of asset.library_assets ?? []) add(libraryAsset.asset_id);
  for (const libraryAsset of asset.library_entity?.assets ?? []) add(libraryAsset.asset_id);
  return [...ids];
}

export function syncAssetMentionReferencesWithText(text: string, references: AssetLibraryReference[]) {
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

export function assetMentionQueryFromText(text: string, caretIndex: number | null | undefined) {
  const caret = typeof caretIndex === "number" ? caretIndex : text.length;
  const beforeCaret = text.slice(0, caret);
  const atIndex = beforeCaret.lastIndexOf("@");
  if (atIndex < 0) return null;
  const prefix = beforeCaret.slice(0, atIndex);
  if (prefix && !/[\s([{，。！？；：,.!?;:]$/.test(prefix)) return null;
  const query = beforeCaret.slice(atIndex + 1);
  if (/\s/.test(query)) return null;
  return {
    start: atIndex,
    end: caret,
    query,
  };
}
