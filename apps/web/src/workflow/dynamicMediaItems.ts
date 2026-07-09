import type {
  AssetLibraryReference,
  DynamicMediaItem,
  DynamicMediaItemType,
  DynamicMediaItemWorkingVersion,
  NodeRunRequest,
  NodeRunResult,
  ResolvedNodeInputs,
  UploadedAsset,
  WorkflowItemRegenerateRequest,
  WorkflowNode,
} from "../types";
import { dedupeAssets } from "./assets.ts";

type DynamicMediaItemOptions = {
  run?: NodeRunResult | null;
  resolvedInputs?: ResolvedNodeInputs | null;
  outputAssets?: UploadedAsset[];
};

type DynamicMediaItemRuntimePatch = {
  item_id?: string | null;
  target_entity_id?: string | null;
  entity_id?: string | null;
  semantic_type?: string | null;
  status?: string | null;
  generation_status?: string | null;
  error?: string | null;
  error_code?: string | null;
  connection_state?: string | null;
};

type ExplicitDynamicItemValue = {
  value: unknown;
  hint?: DynamicMediaItemType;
  legacyFallback?: boolean;
};

export function dynamicMediaItemsForNode(node: WorkflowNode, options: DynamicMediaItemOptions = {}): DynamicMediaItem[] {
  const nodeType = workflowNodeType(node);
  const explicitItems = explicitDynamicItemValues(node, options);
  if (explicitItems.length) {
    return explicitItems
      .map(({ value, hint, legacyFallback }, index) => normalizeDynamicMediaItem(value, index, nodeType, node.status, hint, legacyFallback))
      .filter((item): item is DynamicMediaItem => Boolean(item))
      .sort(compareDynamicMediaItems);
  }

  return fallbackDynamicMediaItemsFromAssets(node, options).sort(compareDynamicMediaItems);
}

export function applyDynamicMediaItemRuntime(items: DynamicMediaItem[], patch: DynamicMediaItemRuntimePatch) {
  const itemId = firstString(patch.item_id, patch.target_entity_id, patch.entity_id);
  const status = firstString(patch.status, patch.generation_status);
  if (!itemId || !status) return items;

  return items.map((item) => {
    if (item.itemId !== itemId) return item;
    return {
      ...item,
      status,
      semanticType: firstString(patch.semantic_type) ?? item.semanticType,
      error: firstString(patch.error) ?? item.error,
      errorCode: firstString(patch.error_code) ?? item.errorCode,
    };
  });
}

export function buildDynamicMediaItemRunRequest(
  node: Pick<WorkflowNode, "id" | "node_type" | "type" | "input_assets">,
  item: DynamicMediaItem,
  workflowId?: string | null,
  assetReferences: AssetLibraryReference[] = [],
): NodeRunRequest {
  const nodeType = workflowNodeType(node);
  return {
    workflow_id: workflowId,
    node_id: node.id,
    node_type: nodeType,
    item_id: item.itemId,
    target_entity_id: item.itemId,
    semantic_type: item.semanticType ?? semanticTypeForItemType(item.itemType),
    input_context: {
      item_id: item.itemId,
      target_entity_id: item.itemId,
      semantic_type: item.semanticType ?? semanticTypeForItemType(item.itemType),
      item_prompt: item.prompt,
      ...(item.negativePrompt ? { negative_prompt: item.negativePrompt } : {}),
      ...(item.metadata ? { item_metadata: item.metadata } : {}),
    },
    input_assets: dedupeAssets([...(node.input_assets ?? []), ...item.inputAssets, ...item.referenceAssets]),
    asset_references: assetReferences.map((reference) => ({
      ...reference,
      target_node_id: node.id,
      target_node_type: nodeType,
      target_node_ids: [node.id],
      target_entity_id: item.itemId,
      item_id: item.itemId,
    })),
    mode: "real",
    media_mode: "real",
    save_outputs: true,
    auto_resolve: Boolean(workflowId),
    run_downstream: false,
    force_rerun: true,
  };
}

export function buildDynamicMediaItemRegenerateRequest(
  item: Pick<
    DynamicMediaItem,
    "itemId" | "itemType" | "semanticType" | "prompt" | "inputAssetIds" | "inputAssets" | "referenceAssets" | "outputAssets" | "currentWorkingVersion" | "metadata"
  >,
  assetReferences: AssetLibraryReference[] = [],
): WorkflowItemRegenerateRequest {
  const semanticType = item.semanticType ?? semanticTypeForItemType(item.itemType);
  const sourceAsset = item.currentWorkingVersion?.assets?.[0] ?? item.outputAssets[0] ?? null;
  const sourceAssetPrompt = sourceAsset ? assetPromptFromAsset(sourceAsset) || item.currentWorkingVersion?.prompt || undefined : undefined;
  const referenceAssetIds = uniqueStrings([
    ...item.inputAssets.map((asset) => asset.asset_id),
    ...item.referenceAssets.map((asset) => asset.asset_id),
    ...assetReferences.flatMap((reference) => [reference.asset_id ?? ""]),
  ]);

  return {
    prompt_scope: "item",
    source_item_id: item.itemId,
    source_item_prompt: item.prompt,
    ...(sourceAsset?.asset_id ? { source_asset_id: sourceAsset.asset_id } : {}),
    ...(sourceAssetPrompt ? { source_asset_prompt: sourceAssetPrompt } : {}),
    semantic_type: semanticType,
    reference_asset_ids: referenceAssetIds,
    asset_slot_id: semanticType,
    ...(assetReferences.length ? { asset_references: assetReferences } : {}),
  };
}

export function dynamicMediaItemHistoryFilter(item: Pick<DynamicMediaItem, "itemId" | "semanticType" | "itemType">) {
  return {
    entity_id: item.itemId,
    semantic_type: item.semanticType ?? semanticTypeForItemType(item.itemType),
  };
}

function explicitDynamicItemValues(node: WorkflowNode, options: DynamicMediaItemOptions) {
  const canonicalItems = canonicalDynamicItemValues(node, options);
  if (canonicalItems.length) return canonicalItems;

  const sources = [
    node as unknown,
    node.input_context,
    node.output,
    options.run?.output,
    options.run?.resolved_input_context,
    options.run?.metadata,
    options.resolvedInputs?.resolved_input_context,
  ];

  for (const source of sources) {
    const values = explicitItemsFromRecord(source, workflowNodeType(node));
    if (values.length) return values;
  }
  return [];
}

function canonicalDynamicItemValues(node: WorkflowNode, options: DynamicMediaItemOptions): ExplicitDynamicItemValue[] {
  const nodeType = workflowNodeType(node);
  const canonicalSources = [
    node.output,
    options.run?.output,
    node.content,
    node as unknown,
    options.resolvedInputs?.resolved_input_context,
    options.run?.resolved_input_context,
  ];

  if (nodeType === "scene-generation") {
    const sceneAssets = firstCollection(canonicalSources, "scene_assets");
    if (sceneAssets.length) return sceneAssets.map((value) => ({ value, hint: "scene" }));

    const legacyScenes = firstCollection(canonicalSources, "scenes");
    if (legacyScenes.length) return legacyScenes.map((value) => ({ value, hint: "scene", legacyFallback: true }));
  }

  if (nodeType === "storyboard") {
    const shots = firstCollection(canonicalSources, "shots");
    if (shots.length) return shots.map((value) => ({ value, hint: "storyboard_image" }));

    const mediaItems = firstCollection([node.input_context, options.run?.resolved_input_context, options.resolvedInputs?.resolved_input_context], "media_items")
      .filter((item) => isMediaItemSemanticType(item, "storyboard_image"));
    if (mediaItems.length) return mediaItems.map((value) => ({ value, hint: "storyboard_image" }));

    const legacyStoryboardItems = [
      ...firstCollection(canonicalSources, "storyboard_items"),
      ...firstCollection(canonicalSources, "storyboardItems"),
    ];
    if (legacyStoryboardItems.length) {
      return legacyStoryboardItems.map((value) => ({ value, hint: "storyboard_image", legacyFallback: true }));
    }

    const legacyScenes = firstCollection(canonicalSources, "scenes");
    if (legacyScenes.length) return legacyScenes.map((value) => ({ value, hint: "storyboard_image", legacyFallback: true }));
  }

  if (nodeType === "storyboard-video-generation") {
    const segments = firstCollection(canonicalSources, "segments");
    if (segments.length) return segments.map((value) => ({ value, hint: "storyboard_video" }));

    const mediaItems = firstCollection([node.input_context, options.run?.resolved_input_context, options.resolvedInputs?.resolved_input_context], "media_items")
      .filter((item) => isMediaItemSemanticType(item, "storyboard_video"));
    if (mediaItems.length) return mediaItems.map((value) => ({ value, hint: "storyboard_video" }));
  }

  return [];
}

function explicitItemsFromRecord(value: unknown, nodeType: string): ExplicitDynamicItemValue[] {
  const record = recordFromUnknown(value);
  if (!record) return [];

  const direct = arrayFromUnknown(record.media_items);
  if (direct.length) return direct.map((item) => ({ value: item }));

  const output = recordFromUnknown(record.output);
  const outputItems = arrayFromUnknown(output?.media_items);
  if (outputItems.length) return outputItems.map((item) => ({ value: item }));

  const inputContext = recordFromUnknown(record.input_context);
  const inputItems = arrayFromUnknown(inputContext?.media_items);
  if (inputItems.length) return inputItems.map((item) => ({ value: item }));

  const structured = recordFromUnknown(record.structured_output) ?? recordFromUnknown(output?.structured_output);
  if (!structured) return [];

  const structuredSources: Array<{ key: string; hint?: DynamicMediaItemType }> = [
    { key: "items" },
    { key: "products", hint: "product_image" },
    { key: "product_items", hint: "product_image" },
    { key: "product_images", hint: "product_image" },
    { key: "characters", hint: "character" },
    { key: "scene_assets", hint: "scene" },
    { key: "scenes", hint: "scene" },
    { key: "shots", hint: "storyboard_image" },
    { key: "storyboard_items", hint: "storyboard_image" },
    { key: "segments", hint: nodeType === "storyboard-video-generation" ? "storyboard_video" : "unknown" },
  ];
  for (const source of structuredSources) {
    const items = arrayFromUnknown(structured[source.key]);
    if (items.length) return items.map((item) => ({ value: item, hint: source.hint }));
  }

  return [];
}

function normalizeDynamicMediaItem(
  value: unknown,
  index: number,
  nodeType: string,
  nodeStatus?: string | null,
  hint?: DynamicMediaItemType,
  legacyFallback = false,
): DynamicMediaItem | null {
  const record = recordFromUnknown(value);
  if (!record) return null;
  const itemType = itemTypeFromRecord(record, nodeType, hint);
  const semanticType = firstString(record.semantic_type) ?? semanticTypeForItemType(itemType);
  const itemId = itemIdFromRecord(record, itemType) ?? `${itemType}-${index + 1}`;
  const order = numberFromUnknown(record.order) ?? numberFromUnknown(record.index) ?? index + 1;
  const metadata = itemMetadataFromRecord(record, legacyFallback);
  const inputAssets = assetArrayFromUnknown(record.input_assets);
  const referenceAssets = dedupeAssets([
    ...assetArrayFromUnknown(record.reference_assets),
    ...assetArrayFromUnknown(record.product_reference_assets),
    ...assetArrayFromUnknown(record.product_references),
    ...assetArrayFromUnknown(record.references),
  ]);
  const displayName = firstString(record.display_name, record.name, record.title, record.label) ?? fallbackDisplayName(itemType, order);
  const outputAssets = dedupeAssets([
    ...assetArrayFromUnknown(record.output_assets),
    ...assetArrayFromUnknown(record.assets),
    ...assetArrayFromUnknown(record.media_assets),
    ...canonicalMediaAssetsFromRecord(record, itemType, itemId, displayName),
  ]);
  const mainAsset = primarySemanticAssetForItem(itemType, outputAssets);
  const firstLibraryAsset = outputAssets.find((asset) => asset.library_state || asset.library_entity_id || asset.library_asset_id || asset.library_error || asset.source_type);

  return {
    itemId,
    itemType,
    semanticType,
    order,
    displayName,
    description: firstString(record.description, record.summary, metadata?.description, metadata?.summary) ?? null,
    prompt: firstString(record.prompt, record.item_prompt, record.user_prompt, record.description) ?? "",
    negativePrompt: firstString(record.negative_prompt, record.negativePrompt) ?? null,
    lifecycleState: firstString(record.lifecycle_state, metadata?.lifecycle_state) ?? null,
    shotType: firstString(record.shot_type, metadata?.shot_type) ?? null,
    segmentId: firstString(record.segment_id, metadata?.segment_id) ?? null,
    primarySceneId: firstString(record.primary_scene_id, metadata?.primary_scene_id) ?? null,
    sceneReferenceIds: stringArrayFromUnknown(record.scene_reference_ids).concat(stringArrayFromUnknown(metadata?.scene_reference_ids)),
    characterIds: stringArrayFromUnknown(record.character_ids).concat(stringArrayFromUnknown(metadata?.character_ids)),
    productReferenceIds: stringArrayFromUnknown(record.product_reference_ids).concat(stringArrayFromUnknown(metadata?.product_reference_ids)),
    styleReferenceIds: stringArrayFromUnknown(record.style_reference_ids).concat(stringArrayFromUnknown(metadata?.style_reference_ids)),
    noSceneReason: firstString(record.no_scene_reason, metadata?.no_scene_reason) ?? null,
    missingSceneBinding: missingSceneBindingForRecord(record, metadata, itemType),
    referenceBindings: recordFromUnknown(metadata?.reference_bindings) ?? recordFromUnknown(record.reference_bindings) ?? undefined,
    legacyFallback,
    currentWorkingVersion: workingVersionFromUnknown(record.current_working_version ?? record.currentWorkingVersion) ?? legacyCurrentWorkingVersionFromRecord(record),
    selectedVersion: workingVersionFromUnknown(record.selected_version ?? record.selectedVersion) ?? legacySelectedVersionFromAssets(outputAssets),
    historyVersions: workingVersionArrayFromUnknown(record.history_versions ?? record.historyVersions),
    needsApply: booleanFromUnknown(record.needs_apply ?? record.needsApply) ?? legacyNeedsApply(record, outputAssets),
    qualityStatus: firstString(record.quality_status, metadata?.quality_status) ?? null,
    qualityIssues: qualityIssuesFromUnknown(record.quality_issues ?? metadata?.quality_issues),
    videoCurrentWorkingVersion: workingVersionFromUnknown(
      record.video_current_working_version ??
        record.shot_video_current_working_version ??
        record.storyboard_video_current_working_version ??
        record.videoCurrentWorkingVersion,
    ),
    videoSelectedVersion: workingVersionFromUnknown(
      record.video_selected_version ??
        record.shot_video_selected_version ??
        record.storyboard_video_selected_version ??
        record.videoSelectedVersion,
    ),
    videoHistoryVersions: workingVersionArrayFromUnknown(
      record.video_history_versions ??
        record.shot_video_history_versions ??
        record.storyboard_video_history_versions ??
        record.videoHistoryVersions,
    ),
    inputAssetIds: stringArrayFromUnknown(record.input_asset_ids)
      .concat(stringArrayFromUnknown(record.reference_asset_ids))
      .concat(stringArrayFromUnknown(record.product_reference_asset_ids)),
    inputAssets,
    referenceAssets,
    status: itemStatus(record, nodeStatus),
    outputAssets,
    mainAsset,
    faceIdAsset: outputAssets.find((asset) => asset.semantic_type === "character_face_id") ?? null,
    threeViewAsset: outputAssets.find((asset) => asset.semantic_type === "character_three_view") ?? null,
    multiViewAsset: outputAssets.find((asset) => asset.semantic_type === "scene_multi_view") ?? null,
    libraryState: firstString(record.library_state, metadata?.library_state, firstLibraryAsset?.library_state) ?? null,
    libraryEntityId: firstString(record.library_entity_id, metadata?.library_entity_id, firstLibraryAsset?.library_entity_id) ?? null,
    libraryAssetId: firstString(record.library_asset_id, metadata?.library_asset_id, firstLibraryAsset?.library_asset_id) ?? null,
    libraryError: firstString(record.library_error, metadata?.library_error, firstLibraryAsset?.library_error) ?? null,
    sourceType: firstString(record.source_type, metadata?.source_type, firstLibraryAsset?.source_type) ?? null,
    candidateCount: numberFromUnknown(record.candidate_count) ?? undefined,
    candidateWarningCount: numberFromUnknown(record.candidate_warning_count) ?? undefined,
    historyCount: numberFromUnknown(record.history_count) ?? undefined,
    durationSeconds: numberFromUnknown(record.duration_seconds),
    referenceMode: firstString(record.reference_mode, metadata?.reference_mode) ?? null,
    referenceRequired: booleanFromUnknown(record.product_reference_required) ?? booleanFromUnknown(metadata?.product_reference_required),
    identityLocked: booleanFromUnknown(record.product_identity_locked) ?? booleanFromUnknown(metadata?.product_identity_locked),
    error: firstString(record.error, record.message) ?? null,
    errorCode: firstString(record.error_code, record.code) ?? null,
    metadata,
  };
}

function workingVersionFromUnknown(value: unknown): DynamicMediaItemWorkingVersion | null {
  const record = recordFromUnknown(value);
  if (!record) return null;
  return {
    ...record,
    version_id: firstString(record.version_id, record.id, record.revision_id) ?? null,
    revision_id: firstString(record.revision_id) ?? null,
    asset_ids: stringArrayFromUnknown(record.asset_ids).concat(stringArrayFromUnknown(record.assetIds)),
    assets: assetArrayFromUnknown(record.assets).concat(assetArrayFromUnknown(record.output_assets)),
    status: firstString(record.status) ?? null,
    prompt: firstString(record.prompt) ?? null,
    provider_prompt: firstString(record.provider_prompt, record.providerPrompt) ?? null,
    quality_status: firstString(record.quality_status, record.qualityStatus) ?? null,
    quality_issues: qualityIssuesFromUnknown(record.quality_issues ?? record.qualityIssues),
    created_at: firstString(record.created_at, record.createdAt) ?? null,
    source: firstString(record.source) ?? null,
    selected_at: firstString(record.selected_at, record.selectedAt) ?? null,
    selected_by: firstString(record.selected_by, record.selectedBy) ?? null,
    quality_override: booleanFromUnknown(record.quality_override ?? record.qualityOverride),
    metadata: recordFromUnknown(record.metadata) ?? undefined,
  };
}

function workingVersionArrayFromUnknown(value: unknown): DynamicMediaItemWorkingVersion[] {
  return arrayFromUnknown(value).flatMap((item) => {
    const version = workingVersionFromUnknown(item);
    return version ? [version] : [];
  });
}

function legacyCurrentWorkingVersionFromRecord(record: Record<string, unknown>): DynamicMediaItemWorkingVersion | null {
  const candidates = workingVersionArrayFromUnknown(record.candidate_versions)
    .concat(workingVersionArrayFromUnknown(record.candidates))
    .concat(workingVersionArrayFromUnknown(record.pending_candidates));
  const readyCandidate = candidates.find((candidate) => {
    const status = String(candidate.status ?? "").toLowerCase();
    return status === "ready" || status === "completed" || status === "selected";
  });
  if (readyCandidate) return readyCandidate;
  return workingVersionFromUnknown(record.candidate_version ?? record.current_candidate);
}

function legacySelectedVersionFromAssets(assets: UploadedAsset[]): DynamicMediaItemWorkingVersion | null {
  if (!assets.length) return null;
  return {
    version_id: firstString(assets[0].version, assets[0].asset_id) ?? assets[0].asset_id,
    asset_ids: assets.map((asset) => asset.asset_id),
    assets,
    status: "selected",
    source: "active_asset",
  };
}

function legacyNeedsApply(record: Record<string, unknown>, outputAssets: UploadedAsset[]) {
  const current = workingVersionFromUnknown(record.current_working_version ?? record.currentWorkingVersion) ?? legacyCurrentWorkingVersionFromRecord(record);
  const selected = workingVersionFromUnknown(record.selected_version ?? record.selectedVersion) ?? legacySelectedVersionFromAssets(outputAssets);
  const currentId = firstString(current?.version_id, ...(current?.asset_ids ?? []));
  const selectedId = firstString(selected?.version_id, ...(selected?.asset_ids ?? []));
  return Boolean(currentId && selectedId && currentId !== selectedId);
}

function qualityIssuesFromUnknown(value: unknown) {
  return arrayFromUnknown(value)
    .map((item) => recordFromUnknown(item))
    .filter((record): record is Record<string, unknown> => Boolean(record));
}

function firstCollection(sources: unknown[], key: string): unknown[] {
  for (const source of sources) {
    const values = collectionFromRecord(source, key);
    if (values.length) return values;
  }
  return [];
}

function collectionFromRecord(source: unknown, key: string): unknown[] {
  const record = recordFromUnknown(source);
  if (!record) return [];
  const direct = arrayFromUnknown(record[key]);
  if (direct.length) return direct;
  const structured = recordFromUnknown(record.structured_output);
  const structuredValues = arrayFromUnknown(structured?.[key]);
  if (structuredValues.length) return structuredValues;
  const output = recordFromUnknown(record.output);
  const outputDirect = arrayFromUnknown(output?.[key]);
  if (outputDirect.length) return outputDirect;
  const outputStructured = recordFromUnknown(output?.structured_output);
  const outputStructuredValues = arrayFromUnknown(outputStructured?.[key]);
  if (outputStructuredValues.length) return outputStructuredValues;
  const content = recordFromUnknown(record.content);
  const contentValues = arrayFromUnknown(content?.[key]);
  if (contentValues.length) return contentValues;
  const inputContext = recordFromUnknown(record.input_context);
  return arrayFromUnknown(inputContext?.[key]);
}

function isMediaItemSemanticType(value: unknown, semanticType: string) {
  const record = recordFromUnknown(value);
  if (!record) return false;
  const itemType = firstString(record.item_type, record.type);
  const semantic = firstString(record.semantic_type);
  return itemType === semanticType || semantic === semanticType;
}

function itemIdFromRecord(record: Record<string, unknown>, itemType: DynamicMediaItemType) {
  if (itemType === "scene") {
    return firstString(record.scene_id, record.item_id, record.id, record.entity_id, record.asset_id);
  }
  if (itemType === "character") {
    return firstString(record.character_id, record.item_id, record.id, record.entity_id, record.asset_id);
  }
  if (itemType === "product_image") {
    return firstString(record.product_id, record.item_id, record.id, record.entity_id, record.asset_id);
  }
  if (itemType === "storyboard_image" || itemType === "storyboard_video") {
    return firstString(record.shot_id, record.item_id, record.entity_id, record.id, record.segment_id, record.asset_id);
  }
  return firstString(record.item_id, record.id, record.entity_id, record.scene_id, record.character_id, record.shot_id, record.segment_id, record.asset_id);
}

function itemMetadataFromRecord(record: Record<string, unknown>, legacyFallback: boolean) {
  const base = recordFromUnknown(record.metadata) ?? {};
  const referencedByShotIds = stringArrayFromUnknown(record.referenced_by_shot_ids);
  const referencedByShots = stringArrayFromUnknown(record.referenced_by_shots);
  const metadata: Record<string, unknown> = { ...base };
  if (referencedByShotIds.length) metadata.referenced_by_shot_ids = referencedByShotIds;
  if (referencedByShots.length) metadata.referenced_by_shots = referencedByShots;
  if (legacyFallback) metadata.legacy_fallback = true;
  return Object.keys(metadata).length ? metadata : undefined;
}

function missingSceneBindingForRecord(
  record: Record<string, unknown>,
  metadata: Record<string, unknown> | undefined,
  itemType: DynamicMediaItemType,
) {
  if (itemType !== "storyboard_image" && itemType !== "storyboard_video") return false;
  const sceneReferenceIds = stringArrayFromUnknown(record.scene_reference_ids).concat(stringArrayFromUnknown(metadata?.scene_reference_ids));
  const primarySceneId = firstString(record.primary_scene_id, metadata?.primary_scene_id);
  const noSceneReason = firstString(record.no_scene_reason, metadata?.no_scene_reason);
  const hasCanonicalBindingFields =
    Object.hasOwn(record, "scene_reference_ids") ||
    Object.hasOwn(record, "primary_scene_id") ||
    Object.hasOwn(record, "no_scene_reason") ||
    Boolean(metadata && (Object.hasOwn(metadata, "scene_reference_ids") || Object.hasOwn(metadata, "primary_scene_id") || Object.hasOwn(metadata, "no_scene_reason")));
  if (!hasCanonicalBindingFields) return false;
  if (primarySceneId || sceneReferenceIds.length) return false;
  return !isValidNoSceneReason(noSceneReason);
}

function isValidNoSceneReason(value?: string | null) {
  return (
    value === "product_packshot" ||
    value === "title_card" ||
    value === "abstract_visual" ||
    value === "transition" ||
    value === "user_requested_scene_free_shot"
  );
}

function fallbackDynamicMediaItemsFromAssets(node: WorkflowNode, options: DynamicMediaItemOptions): DynamicMediaItem[] {
  const nodeType = workflowNodeType(node);
  const canonicalAssets = dedupeAssets([
    ...(options.outputAssets ?? []),
    ...(node.output_assets ?? []),
    ...(options.run?.output_assets ?? []),
  ]);
  const legacyOutputAssets = dedupeAssets([
    ...assetArrayFromUnknown(node.output?.output_assets),
    ...assetArrayFromUnknown(node.output?.assets),
    ...assetArrayFromUnknown(options.run?.output?.output_assets),
    ...assetArrayFromUnknown(options.run?.output?.assets),
  ]);
  const assets = canonicalAssets.length ? canonicalAssets : legacyOutputAssets;
  if (!assets.length) return [];

  const groups = new Map<string, UploadedAsset[]>();
  for (const asset of assets) {
    const key = fallbackAssetItemKey(asset);
    groups.set(key, [...(groups.get(key) ?? []), asset]);
  }

  return [...groups.entries()].map(([itemId, groupAssets], index) => {
    const itemType = itemTypeFromNodeType(nodeType, groupAssets[0]?.semantic_type);
    const semanticType = semanticTypeFromAssets(groupAssets) ?? semanticTypeForItemType(itemType);
    return {
      itemId,
      itemType,
      semanticType,
      order: index + 1,
      displayName: fallbackDisplayName(itemType, index + 1),
      prompt: "",
      inputAssetIds: [],
      inputAssets: [],
      referenceAssets: [],
      status: fallbackStatusFromNode(node.status),
      outputAssets: groupAssets,
    };
  });
}

function fallbackAssetItemKey(asset: UploadedAsset) {
  const record = asset as UploadedAsset & Record<string, unknown>;
  const metadata = recordFromUnknown(asset.metadata);
  return firstString(
    asset.entity_id,
    record.scene_id,
    record.character_id,
    record.shot_id,
    record.segment_id,
    metadata?.entity_id,
    metadata?.scene_id,
    metadata?.character_id,
    metadata?.shot_id,
    metadata?.segment_id,
    record.order,
    asset.asset_id,
    asset.semantic_type,
    asset.asset_role,
  ) ?? asset.asset_id;
}

function itemStatus(record: Record<string, unknown>, nodeStatus?: string | null) {
  return firstString(record.status, record.generation_status, record.state) ?? fallbackStatusFromNode(nodeStatus);
}

function fallbackStatusFromNode(status?: string | null) {
  if (!status || status === "running" || status === "waiting" || status === "queued") return "unknown";
  return status;
}

function itemTypeFromRecord(record: Record<string, unknown>, nodeType: string, hint?: DynamicMediaItemType): DynamicMediaItemType {
  const explicit = firstString(record.item_type, record.type);
  if (isDynamicMediaItemType(explicit)) return explicit;
  const semanticType = firstString(record.semantic_type);
  return itemTypeFromNodeType(nodeType, semanticType, hint);
}

function itemTypeFromNodeType(nodeType: string, semanticType?: string | null, hint?: DynamicMediaItemType): DynamicMediaItemType {
  if (hint) return hint;
  const semantic = String(semanticType ?? "").toLowerCase();
  if (semantic.includes("bgm") || semantic.includes("music") || semantic.includes("audio")) return "bgm";
  if (semantic.includes("storyboard_video")) return "storyboard_video";
  if (semantic.includes("storyboard")) return "storyboard_image";
  if (semantic.includes("character")) return "character";
  if (semantic.includes("scene")) return "scene";
  if (semantic.includes("product")) return "product_image";
  const type = nodeType.toLowerCase();
  if (type.includes("character")) return "character";
  if (type.includes("scene")) return "scene";
  if (type.includes("product")) return "product_image";
  if (type.includes("storyboard-video")) return "storyboard_video";
  if (type.includes("storyboard")) return "storyboard_image";
  if (type.includes("bgm") || type.includes("music") || type.includes("audio")) return "bgm";
  return "unknown";
}

function semanticTypeForItemType(itemType: DynamicMediaItemType) {
  if (itemType === "character") return "character_main";
  if (itemType === "scene") return "scene_main";
  if (itemType === "storyboard_image") return "storyboard_image";
  if (itemType === "storyboard_video") return "storyboard_video";
  if (itemType === "bgm") return "bgm";
  if (itemType === "product_image") return "product_image";
  return "unknown";
}

function semanticTypeFromAssets(assets: UploadedAsset[]) {
  return assets.find((asset) => asset.semantic_type)?.semantic_type ?? null;
}

function primarySemanticAssetForItem(itemType: DynamicMediaItemType, assets: UploadedAsset[]) {
  if (itemType === "character") return assets.find((asset) => asset.semantic_type === "character_main") ?? assets[0] ?? null;
  if (itemType === "scene") return assets.find((asset) => asset.semantic_type === "scene_main") ?? assets[0] ?? null;
  if (itemType === "storyboard_image") return assets.find((asset) => asset.semantic_type === "storyboard_image") ?? assets[0] ?? null;
  if (itemType === "storyboard_video") return assets.find((asset) => asset.semantic_type === "storyboard_video" || asset.asset_type === "video") ?? assets[0] ?? null;
  if (itemType === "bgm") return assets.find((asset) => asset.semantic_type === "bgm" || asset.asset_type === "audio") ?? assets[0] ?? null;
  if (itemType === "product_image") return assets.find((asset) => asset.semantic_type === "product_image") ?? assets[0] ?? null;
  return assets[0] ?? null;
}

function fallbackDisplayName(itemType: DynamicMediaItemType, order?: number | null) {
  const position = order && order > 0 ? order : 1;
  if (itemType === "character") return `Character ${position}`;
  if (itemType === "scene") return `Scene ${position}`;
  if (itemType === "storyboard_image") return `Shot ${position}`;
  if (itemType === "storyboard_video") return `Segment ${position}`;
  if (itemType === "bgm") return `BGM ${position}`;
  if (itemType === "product_image") return `Product ${position}`;
  return `Item ${position}`;
}

function compareDynamicMediaItems(a: DynamicMediaItem, b: DynamicMediaItem) {
  return (a.order ?? 0) - (b.order ?? 0) || a.itemId.localeCompare(b.itemId);
}

function assetArrayFromUnknown(value: unknown): UploadedAsset[] {
  return arrayFromUnknown(value)
    .map((item) => recordFromUnknown(item))
    .filter((record): record is Record<string, unknown> => Boolean(record?.asset_id))
    .map((record) => record as unknown as UploadedAsset);
}

function stringArrayFromUnknown(value: unknown): string[] {
  return arrayFromUnknown(value).flatMap((item) => {
    const text = firstString(item);
    return text ? [text] : [];
  });
}

function uniqueStrings(values: unknown[]) {
  return Array.from(new Set(values.flatMap((value) => {
    const text = firstString(value);
    return text ? [text] : [];
  })));
}

function arrayFromUnknown(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function recordFromUnknown(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function numberFromUnknown(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return null;
}

function booleanFromUnknown(value: unknown): boolean | undefined {
  if (typeof value === "boolean") return value;
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (normalized === "true") return true;
    if (normalized === "false") return false;
  }
  return undefined;
}

function firstString(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
  }
  return null;
}

function workflowNodeType(node: Pick<WorkflowNode, "id" | "node_type" | "type">) {
  return node.node_type ?? node.type ?? node.id;
}

function assetPromptFromAsset(asset: UploadedAsset) {
  const record = asset as UploadedAsset & Record<string, unknown>;
  const metadata = recordFromUnknown(asset.metadata);
  return firstString(record.prompt, record.generation_prompt, metadata?.prompt, metadata?.generation_prompt);
}

type CanonicalMediaField = {
  fields: string[];
  semanticType: string;
  assetType: UploadedAsset["asset_type"];
  assetRole: UploadedAsset["asset_role"];
  suffix: string;
};

const CANONICAL_MEDIA_FIELDS: Record<DynamicMediaItemType, CanonicalMediaField[]> = {
  character: [
    { fields: ["roleMainImageUri", "role_main_image_uri", "mainImageUri", "main_image_uri"], semanticType: "character_main", assetType: "image", assetRole: "character", suffix: "main" },
    { fields: ["roleFaceIdImageUri", "role_face_id_image_uri", "faceIdImageUri", "face_id_image_uri"], semanticType: "character_face_id", assetType: "image", assetRole: "character", suffix: "face" },
    { fields: ["roleThreeViewImageUri", "role_three_view_image_uri", "threeViewImageUri", "three_view_image_uri"], semanticType: "character_three_view", assetType: "image", assetRole: "character", suffix: "three-view" },
    { fields: ["roleConceptImageUri", "role_concept_image_uri", "conceptImageUri", "concept_image_uri"], semanticType: "character_concept", assetType: "image", assetRole: "character", suffix: "concept" },
  ],
  scene: [
    { fields: ["sceneMainImageUri", "scene_main_image_uri", "mainImageUri", "main_image_uri"], semanticType: "scene_main", assetType: "image", assetRole: "scene", suffix: "main" },
    { fields: ["sceneMultiViewImageUri", "scene_multi_view_image_uri", "multiViewImageUri", "multi_view_image_uri"], semanticType: "scene_multi_view", assetType: "image", assetRole: "scene", suffix: "multi-view" },
  ],
  storyboard_image: [
    { fields: ["storyboardImageUri", "storyboard_image_uri", "imageUri", "image_uri"], semanticType: "storyboard_image", assetType: "image", assetRole: "reference", suffix: "storyboard" },
  ],
  storyboard_video: [
    { fields: ["storyboardVideoUri", "storyboard_video_uri", "videoUri", "video_uri"], semanticType: "storyboard_video", assetType: "video", assetRole: "reference", suffix: "video" },
  ],
  bgm: [
    { fields: ["musicUri", "music_uri", "bgmUri", "bgm_uri", "audioUri", "audio_uri"], semanticType: "bgm", assetType: "audio", assetRole: "audio", suffix: "music" },
  ],
  product_image: [
    { fields: ["productImageUri", "product_image_uri", "imageUri", "image_uri"], semanticType: "product_image", assetType: "image", assetRole: "product", suffix: "product" },
  ],
  unknown: [],
};

function canonicalMediaAssetsFromRecord(
  record: Record<string, unknown>,
  itemType: DynamicMediaItemType,
  entityId: string,
  displayName: string,
): UploadedAsset[] {
  return (CANONICAL_MEDIA_FIELDS[itemType] ?? []).flatMap((field) => {
    const value = field.fields.map((key) => record[key]).find(hasUsableValue);
    if (!value) return [];
    return [canonicalMediaAsset(value, field, entityId, displayName)];
  });
}

function canonicalMediaAsset(value: unknown, field: CanonicalMediaField, entityId: string, displayName: string): UploadedAsset {
  const record = recordFromUnknown(value);
  const path = record
    ? firstString(record.local_path, record.public_url, record.remote_url, record.url, record.preview_path, record.thumbnail_path) ?? ""
    : firstString(value) ?? "";
  return {
    ...(record ?? {}),
    asset_id: firstString(record?.asset_id, record?.id) ?? `${entityId}-${field.semanticType}`,
    asset_type: field.assetType,
    asset_role: field.assetRole,
    filename: firstString(record?.filename, record?.name) ?? `${displayName} ${field.suffix}`,
    mime_type: firstString(record?.mime_type, record?.content_type) ?? defaultMimeType(field.assetType),
    local_path: firstString(record?.local_path) ?? path,
    public_url: firstString(record?.public_url),
    remote_url: firstString(record?.remote_url),
    preview_path: firstString(record?.preview_path),
    thumbnail_path: firstString(record?.thumbnail_path),
    semantic_type: firstString(record?.semantic_type) ?? field.semanticType,
    entity_id: firstString(record?.entity_id) ?? entityId,
  } as UploadedAsset;
}

function defaultMimeType(assetType: UploadedAsset["asset_type"]) {
  if (assetType === "image") return "image/*";
  if (assetType === "video") return "video/*";
  if (assetType === "audio") return "audio/*";
  return "application/octet-stream";
}

function hasUsableValue(value: unknown) {
  if (value === undefined || value === null) return false;
  if (typeof value === "string") return Boolean(value.trim());
  return true;
}

function isDynamicMediaItemType(value?: string | null): value is DynamicMediaItemType {
  return value === "character" || value === "scene" || value === "storyboard_image" || value === "storyboard_video" || value === "bgm" || value === "product_image" || value === "unknown";
}
