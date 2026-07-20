import type {
  AssetVersionV2,
  ProviderTaskStatusV2,
  RuntimeRecordV2,
  SlotFunctionalCardViewModel,
  SlotReferenceBindingViewModel,
  WorkflowItemV2,
  WorkflowNodeV2,
  WorkflowRuntimeV2,
  WorkflowSlotV2,
  WorkflowV2,
} from "../types-v2.ts";
import { versionedMediaPath } from "../workflow/mediaPreview.ts";
import { effectiveSlotPrompt } from "../types-v2.ts";
import { chooseMoreCompleteV2Asset } from "./assets.ts";

export function assetVersionByAssetId(workflow: Pick<WorkflowV2, "asset_versions">) {
  const map = new Map<string, AssetVersionV2>();
  for (const asset of workflow.asset_versions) {
    if (asset.asset_id) map.set(asset.asset_id, chooseMoreCompleteV2Asset(map.get(asset.asset_id), asset));
  }
  return map;
}

export function assetVersionByVersionId(workflow: Pick<WorkflowV2, "asset_versions">) {
  const map = new Map<string, AssetVersionV2>();
  for (const asset of workflow.asset_versions) {
    if (asset.version_id) map.set(asset.version_id, chooseMoreCompleteV2Asset(map.get(asset.version_id), asset));
  }
  return map;
}

export function assetByAssetId(workflow: Pick<WorkflowV2, "asset_versions">) {
  const map = assetVersionByAssetId(workflow);
  for (const [versionId, asset] of assetVersionByVersionId(workflow)) {
    if (!map.has(versionId)) map.set(versionId, asset);
  }
  return map;
}

export function activeItemsByNodeId(workflow: Pick<WorkflowV2, "items">) {
  const map = new Map<string, WorkflowItemV2[]>();
  for (const item of workflow.items) {
    if (item.lifecycle_state === "archived") continue;
    map.set(item.node_id, [...(map.get(item.node_id) ?? []), item]);
  }
  return map;
}

export function slotsByItemId(workflow: Pick<WorkflowV2, "slots">) {
  const map = new Map<string, WorkflowSlotV2[]>();
  for (const slot of workflow.slots) {
    map.set(slot.item_id, [...(map.get(slot.item_id) ?? []), slot]);
  }
  return map;
}

export function regionItemsForNode(workflow: Pick<WorkflowV2, "items">, nodeId: string) {
  return workflow.items.filter((item) => item.node_id === nodeId && item.lifecycle_state !== "archived");
}

export function selectV2NodeItems(workflow: Pick<WorkflowV2, "items"> | null | undefined, nodeId: string) {
  return (workflow?.items ?? []).filter((item) => item.node_id === nodeId && item.lifecycle_state !== "archived");
}

export function selectV2ItemSlots(workflow: Pick<WorkflowV2, "slots"> | null | undefined, itemId: string) {
  return (workflow?.slots ?? []).filter((slot) => slot.item_id === itemId);
}

export function selectV2AssetById(workflow: Pick<WorkflowV2, "asset_versions"> | null | undefined, assetId: string | null | undefined) {
  if (!workflow || !assetId) return null;
  const assets = assetByAssetId(workflow);
  return assets.get(assetId) ?? null;
}

export function slotCompletionSummary(slots: WorkflowSlotV2[]) {
  const total = slots.length;
  const completed = slots.filter((slot) => slot.status === "completed" || Boolean(slot.selected_asset_id)).length;
  const waiting = slots.filter((slot) => slot.status === "waiting" || slot.status === "running").length;
  const failed = slots.filter((slot) => slot.status === "failed").length;
  return { total, completed, waiting, failed };
}

export function selectV2FinalCompositionItem(workflow: Pick<WorkflowV2, "items"> | null | undefined) {
  return (workflow?.items ?? []).find((item) => item.node_id === "final-composition" && item.item_type === "final_composition") ?? null;
}

export function selectV2FinalVideoSlot(workflow: Pick<WorkflowV2, "items" | "slots"> | null | undefined) {
  const item = selectV2FinalCompositionItem(workflow);
  if (!item) return null;
  return (workflow?.slots ?? []).find((slot) => slot.item_id === item.item_id && slot.slot_type === "final_video") ?? null;
}

export function selectedAssetForSlot(
  workflowOrSlot: Pick<WorkflowV2, "asset_versions"> | WorkflowSlotV2 | undefined,
  slotOrAssets?: WorkflowSlotV2 | Map<string, AssetVersionV2>,
) {
  const { slot, byAssetId } = resolveSlotAssetLookup(workflowOrSlot, slotOrAssets);
  if (!slot?.selected_asset_id) return undefined;
  return byAssetId.get(slot.selected_asset_id);
}

export function workingAssetForSlot(workflow: Pick<WorkflowV2, "asset_versions">, slot: WorkflowSlotV2 | undefined) {
  if (!slot) return undefined;
  const byAssetId = assetVersionByAssetId(workflow);
  const byVersionId = assetVersionByVersionId(workflow);
  return (
    (slot.current_working_version_id ? byVersionId.get(slot.current_working_version_id) : undefined) ??
    (slot.current_working_asset_id ? byAssetId.get(slot.current_working_asset_id) : undefined)
  );
}

export function workingVersionForSlot(slot: WorkflowSlotV2 | undefined, assets: Map<string, AssetVersionV2>) {
  if (!slot) return undefined;
  return (
    (slot.current_working_version_id ? assets.get(slot.current_working_version_id) : undefined) ??
    (slot.current_working_asset_id ? assets.get(slot.current_working_asset_id) : undefined)
  );
}

export function historyAssetsForSlot(workflow: Pick<WorkflowV2, "asset_versions">, slot: WorkflowSlotV2 | undefined) {
  if (!slot?.history_version_ids?.length) return [];
  const byAssetId = assetVersionByAssetId(workflow);
  const byVersionId = assetVersionByVersionId(workflow);
  const selected = selectedAssetForSlot(workflow, slot);
  const working = workingAssetForSlot(workflow, slot);
  const excluded = new Set([selected?.asset_id, selected?.version_id, working?.asset_id, working?.version_id].filter(Boolean));
  const result: AssetVersionV2[] = [];
  const seen = new Set<string>();
  for (const id of slot.history_version_ids) {
    if (excluded.has(id)) continue;
    const asset = byVersionId.get(id) ?? byAssetId.get(id);
    const key = asset ? `${asset.asset_id}:${asset.version_id}` : "";
    if (!asset || seen.has(key) || excluded.has(asset.asset_id) || excluded.has(asset.version_id)) continue;
    seen.add(key);
    result.push(asset);
  }
  return result;
}

export function historyVersionsForSlot(slot: WorkflowSlotV2 | undefined, assets: Map<string, AssetVersionV2>) {
  if (!slot?.history_version_ids?.length) return [];
  const selected = selectedAssetForSlot(slot, assets);
  const working = workingVersionForSlot(slot, assets);
  const excluded = new Set([selected?.asset_id, selected?.version_id, working?.asset_id, working?.version_id].filter(Boolean));
  return slot.history_version_ids
    .filter((assetId) => !excluded.has(assetId))
    .map((assetId) => assets.get(assetId))
    .filter((asset): asset is AssetVersionV2 => Boolean(asset))
    .filter((asset) => !excluded.has(asset.asset_id) && !excluded.has(asset.version_id));
}

export function dedupeSlotVersionAssets(versions: AssetVersionV2[]) {
  const seen = new Set<string>();
  const result: AssetVersionV2[] = [];
  for (const asset of versions) {
    const key = asset.asset_id || asset.version_id;
    if (!key || seen.has(key)) continue;
    seen.add(key);
    result.push(asset);
  }
  return result;
}

export function isIdOnlyAssetVersion(asset?: AssetVersionV2 | null) {
  return Boolean(asset?.metadata?.id_only);
}

export function usableAssetVersionUrl(asset?: AssetVersionV2 | null) {
  if (!asset || isIdOnlyAssetVersion(asset)) return "";
  return versionedMediaPath(asset.public_url || asset.proxy_path || asset.thumbnail_path || asset.file_path, asset);
}

export function productReferenceAssetsForItem(
  item: WorkflowItemV2,
  slots: WorkflowSlotV2[],
  assets: Map<string, AssetVersionV2>,
) {
  const referenceIds = new Set<string>();
  collectReferenceIds(referenceIds, item.metadata?.product_reference_asset_ids);
  collectReferenceIds(referenceIds, item.metadata?.uploaded_product_reference_asset_ids);
  collectReferenceIds(referenceIds, item.metadata?.reference_asset_ids);
  collectReferenceIdsFromRelations(referenceIds, item.metadata?.reference_relations);
  for (const slot of slots) {
    collectReferenceIds(referenceIds, slot.explicit_reference_ids);
    collectReferenceIds(referenceIds, slot.media_prompt_asset_ids);
  }

  const result: AssetVersionV2[] = [];
  const seen = new Set<string>();
  for (const id of referenceIds) {
    const asset = assets.get(id);
    if (!asset || seen.has(asset.asset_id)) continue;
    seen.add(asset.asset_id);
    result.push(asset);
  }

  if (result.length) return result;

  for (const asset of assets.values()) {
    if (
      asset.item_id === item.item_id &&
      asset.semantic_type === "product_reference" &&
      !seen.has(asset.asset_id)
    ) {
      seen.add(asset.asset_id);
      result.push(asset);
    }
  }
  return result;
}

export function runtimeForSlot(runtime: WorkflowRuntimeV2 | undefined, slotId: string): RuntimeRecordV2 | undefined {
  if (!runtime) return undefined;
  if (runtime.slot_runtime[slotId]) return runtime.slot_runtime[slotId];
  if (runtime.running_slot_ids.includes(slotId)) return { status: "running" };
  if (runtime.waiting_slot_ids.includes(slotId)) return { status: "waiting" };
  if (runtime.failed_slot_ids.includes(slotId)) return { status: "failed" };
  if (runtime.completed_slot_ids.includes(slotId)) return { status: "completed" };
  return undefined;
}

export function slotRuntimeStatus(workflow: Pick<WorkflowV2, "slots">, runtime: WorkflowRuntimeV2 | undefined, slotId: string): SlotFunctionalCardViewModel["runtime_status"] {
  const runtimeStatus = runtimeForSlot(runtime, slotId)?.status;
  if (runtimeStatus) return runtimeStatus;
  return workflow.slots.find((slot) => slot.slot_id === slotId)?.status ?? "empty";
}

export function buildSlotFunctionalCardViewModel(
  workflow: WorkflowV2,
  nodeId: string,
  itemId: string,
  slotId: string,
): SlotFunctionalCardViewModel {
  const slot = workflow.slots.find((candidate) => candidate.slot_id === slotId && candidate.item_id === itemId && candidate.node_id === nodeId) ??
    workflow.slots.find((candidate) => candidate.slot_id === slotId);
  const item = workflow.items.find((candidate) => candidate.item_id === itemId);
  const slotType = slot?.slot_type ?? "slot";
  return {
    workflow_id: workflow.workflow_id,
    node_id: nodeId,
    item_id: itemId,
    slot_id: slotId,
    slot_type: slotType,
    media_type: slot?.media_type ?? "image",
    title: titleForSlot(slot, item),
    prompt: slot ? effectiveSlotPrompt(slot) : item?.item_prompt ?? "",
    prompt_source: slot?.prompt_source ?? item?.prompt_source ?? "system",
    manual_prompt_dirty: Boolean(slot?.manual_prompt_dirty),
    selected_asset: slot ? selectedAssetForSlot(workflow, slot) ?? null : null,
    working_asset: slot ? workingAssetForSlot(workflow, slot) ?? null : null,
    history_assets: slot ? historyAssetsForSlot(workflow, slot) : [],
    references: slot ? referenceBindingsForSlot(workflow, slot) : [],
    runtime_status: slotRuntimeStatus(workflow, workflow.runtime, slotId),
    warnings: warningsForSlot(slot),
  };
}

export type V2ProviderSlotAudit = {
  materializer_mode?: string;
  materializer_warnings: Array<string | Record<string, unknown>>;
  model_id?: string;
  agent_route_snapshot?: Record<string, unknown>;
  provider_prompt_snapshot?: unknown;
  provider_payload_snapshot?: unknown;
  provider?: string;
  provider_model?: string;
  provider_task_id?: string;
  remote_task_id?: string;
  task_status?: ProviderTaskStatusV2;
  last_error_code?: string;
  last_error_message?: string;
};

export function providerAuditForSlot(
  slot: WorkflowSlotV2,
  runtimeRecord?: RuntimeRecordV2 | null,
  assetVersion?: AssetVersionV2 | null,
): V2ProviderSlotAudit {
  const slotMetadata = recordValue(slot.metadata) ?? {};
  const runtimeMetadata = recordValue(runtimeRecord?.metadata) ?? {};
  const assetMetadata = recordValue(assetVersion?.metadata) ?? {};
  const taskStatus = firstString(
    runtimeMetadata.task_status,
    runtimeMetadata.provider_task_status,
    runtimeMetadata.status,
    runtimeRecord?.status,
  );
  return {
    materializer_mode: firstString(slotMetadata.materializer_mode, runtimeMetadata.materializer_mode, assetMetadata.materializer_mode),
    materializer_warnings: warningArray(slotMetadata.materializer_warnings ?? runtimeMetadata.materializer_warnings ?? assetMetadata.materializer_warnings),
    model_id: firstString(slotMetadata.model_id, runtimeMetadata.model_id, assetMetadata.model_id),
    agent_route_snapshot: firstRecord(slotMetadata.agent_route_snapshot, runtimeMetadata.agent_route_snapshot, assetMetadata.agent_route_snapshot),
    provider_prompt_snapshot: firstPresent(slotMetadata.provider_prompt_snapshot, runtimeMetadata.provider_prompt_snapshot, assetMetadata.provider_prompt_snapshot),
    provider_payload_snapshot: firstPresent(assetVersion?.provider_payload_snapshot, assetMetadata.provider_payload_snapshot, runtimeMetadata.provider_payload_snapshot, slotMetadata.provider_payload_snapshot),
    provider: firstString(runtimeMetadata.provider, slotMetadata.provider, slot.provider, assetMetadata.provider),
    provider_model: firstString(runtimeMetadata.provider_model, slotMetadata.provider_model, assetMetadata.provider_model),
    provider_task_id: firstString(runtimeMetadata.provider_task_id, slotMetadata.provider_task_id, assetMetadata.provider_task_id),
    remote_task_id: firstString(runtimeMetadata.remote_task_id, slotMetadata.remote_task_id, assetMetadata.remote_task_id),
    task_status: taskStatus,
    last_error_code: firstString(runtimeMetadata.last_error_code, slotMetadata.last_error_code, assetMetadata.last_error_code),
    last_error_message: firstString(runtimeMetadata.last_error_message, slotMetadata.last_error_message, assetMetadata.last_error_message),
  };
}

export function safeProviderSnapshotText(value: unknown) {
  if (value === undefined || value === null || value === "") return "";
  const sanitized = redactInlineBase64(value);
  const text = typeof sanitized === "string" ? sanitized : JSON.stringify(sanitized, null, 2);
  return containsInlineBase64(text) ? "[redacted provider snapshot: inline base64 payload omitted]" : text;
}

export function aggregateItemStatus(item: WorkflowItemV2, slots: WorkflowSlotV2[], runtime?: WorkflowRuntimeV2) {
  const activeStatuses = slots.map((slot) => runtimeForSlot(runtime, slot.slot_id)?.status ?? slot.status);
  if (activeStatuses.includes("running")) return "running";
  if (activeStatuses.includes("waiting")) return "waiting";
  if (activeStatuses.includes("failed") && activeStatuses.includes("completed")) return "partial_failed";
  if (activeStatuses.length && activeStatuses.every((status) => status === "completed" || status === "skipped")) return "completed";
  if (activeStatuses.includes("ready") || activeStatuses.includes("empty")) return "ready";
  if (activeStatuses.includes("blocked")) return "not_ready";
  return item.status;
}

export function aggregateNodeStatus(node: WorkflowNodeV2, items: WorkflowItemV2[], slots: WorkflowSlotV2[], runtime?: WorkflowRuntimeV2) {
  if (runtime?.running_node_ids?.includes(node.node_id)) return "running";
  if (runtime?.waiting_node_ids?.includes(node.node_id)) return "waiting";
  if (runtime?.failed_node_ids?.includes(node.node_id)) return "failed";
  if (runtime?.completed_node_ids?.includes(node.node_id)) return "completed";
  if (runtime?.waiting_slot_ids.some((slotId) => slots.some((slot) => slot.slot_id === slotId))) return "waiting";
  const itemStatuses = items.map((item) => aggregateItemStatus(item, slots.filter((slot) => slot.item_id === item.item_id), runtime));
  if (itemStatuses.includes("running")) return "running";
  if (itemStatuses.includes("waiting")) return "waiting";
  if (itemStatuses.includes("partial_failed")) return "partial_failed";
  if (itemStatuses.includes("failed") && itemStatuses.includes("completed")) return "partial_failed";
  if (itemStatuses.length && itemStatuses.every((status) => status === "completed")) return "completed";
  if (itemStatuses.includes("ready")) return "ready";
  return node.status;
}

function resolveSlotAssetLookup(
  workflowOrSlot: Pick<WorkflowV2, "asset_versions"> | WorkflowSlotV2 | undefined,
  slotOrAssets?: WorkflowSlotV2 | Map<string, AssetVersionV2>,
) {
  if (slotOrAssets instanceof Map) {
    return { slot: workflowOrSlot as WorkflowSlotV2 | undefined, byAssetId: slotOrAssets };
  }
  const workflow = workflowOrSlot as Pick<WorkflowV2, "asset_versions"> | undefined;
  return {
    slot: slotOrAssets as WorkflowSlotV2 | undefined,
    byAssetId: workflow?.asset_versions ? assetVersionByAssetId(workflow) : new Map<string, AssetVersionV2>(),
  };
}

function titleForSlot(slot: WorkflowSlotV2 | undefined, item: WorkflowItemV2 | undefined) {
  const slotLabel = slot?.slot_type ? slot.slot_type.replace(/_/g, " ") : "Slot";
  return [item?.display_name, slotLabel].filter(Boolean).join(" · ");
}

function referenceBindingsForSlot(workflow: WorkflowV2, slot: WorkflowSlotV2): SlotReferenceBindingViewModel[] {
  const byAssetId = assetVersionByAssetId(workflow);
  const byVersionId = assetVersionByVersionId(workflow);
  const ids = new Set<string>();
  collectReferenceIds(ids, slot.explicit_reference_ids);
  collectReferenceIds(ids, slot.media_prompt_asset_ids);
  collectReferenceIds(ids, slot.implicit_reference_ids);
  const result: SlotReferenceBindingViewModel[] = [];
  for (const id of ids) {
    const asset = byAssetId.get(id) ?? byVersionId.get(id) ?? null;
    result.push({
      asset_id: asset?.asset_id ?? id,
      version_id: asset?.version_id ?? null,
      display_name: asset?.semantic_type || asset?.asset_id || id,
      media_type: asset?.media_type,
      source_type: asset?.source_type,
      asset,
    });
  }
  return result;
}

function warningsForSlot(slot: WorkflowSlotV2 | undefined): Array<{ code: string; message: string }> {
  if (!slot) return [];
  const warnings = Array.isArray(slot.warnings) && slot.warnings.length ? slot.warnings : warningArrayFromUnknown(slot.metadata?.warnings ?? slot.metadata?.warning);
  return warnings.map((warning) => ({
    code: firstString(warning.code) || "warning",
    message: firstString(warning.message) || firstString(warning.detail) || JSON.stringify(warning),
  }));
}

function warningArrayFromUnknown(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item === "string") return [{ code: "warning", message: item }];
    const record = recordValue(item);
    return record ? [record] : [];
  });
}

function collectReferenceIds(target: Set<string>, value: unknown) {
  if (!Array.isArray(value)) return;
  for (const item of value) {
    if (typeof item === "string" && item.trim()) target.add(item.trim());
  }
}

function collectReferenceIdsFromRelations(target: Set<string>, value: unknown) {
  if (!Array.isArray(value)) return;
  for (const relation of value) {
    if (!relation || typeof relation !== "object") continue;
    const record = relation as Record<string, unknown>;
    for (const key of ["asset_id", "source_asset_id", "version_id", "source_version_id"]) {
      const id = record[key];
      if (typeof id === "string" && id.trim()) target.add(id.trim());
    }
  }
}

function firstPresent(...values: unknown[]) {
  for (const value of values) {
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return undefined;
}

function firstRecord(...values: unknown[]) {
  for (const value of values) {
    const record = recordValue(value);
    if (record) return record;
  }
  return undefined;
}

function warningArray(value: unknown): Array<string | Record<string, unknown>> {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string | Record<string, unknown> => typeof item === "string" || Boolean(recordValue(item)));
}

function redactInlineBase64(value: unknown): unknown {
  if (typeof value === "string") return containsInlineBase64(value) ? "[redacted inline base64 payload]" : value;
  if (Array.isArray(value)) return value.map(redactInlineBase64);
  const record = recordValue(value);
  if (!record) return value;
  return Object.fromEntries(Object.entries(record).map(([key, item]) => [key, redactInlineBase64(item)]));
}

function containsInlineBase64(value: string) {
  return /data:(?:image|video|audio)\//i.test(value) || /;base64,/i.test(value);
}

function recordValue(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

function firstString(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
  }
  return undefined;
}
