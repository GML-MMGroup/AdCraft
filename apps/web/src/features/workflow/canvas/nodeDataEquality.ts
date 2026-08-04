import type { UploadedAsset } from "../../../types.ts";
import type { AssetVersionV2, WorkflowItemV2, WorkflowSlotV2 } from "../../../types-v2.ts";
import type { NodePort, V2LibraryReferenceOption } from "../types.ts";

export function sameStringRecord(left?: Record<string, string>, right?: Record<string, string>) {
  if (left === right) return true;
  const leftEntries = Object.entries(left ?? {});
  const rightRecord = right ?? {};
  if (leftEntries.length !== Object.keys(rightRecord).length) return false;
  return leftEntries.every(([key, value]) => rightRecord[key] === value);
}

export function sameV2AssetVersionList(left: AssetVersionV2[] = [], right: AssetVersionV2[] = []) {
  if (left === right) return true;
  if (left.length !== right.length) return false;
  return left.every((asset, index) => {
    const other = right[index];
    return (
      asset.asset_id === other.asset_id &&
      asset.version_id === other.version_id &&
      asset.media_type === other.media_type &&
      asset.source_type === other.source_type &&
      asset.public_url === other.public_url &&
      asset.proxy_path === other.proxy_path &&
      asset.thumbnail_path === other.thumbnail_path &&
      asset.file_path === other.file_path &&
      asset.status === other.status &&
      asset.quality_status === other.quality_status &&
      asset.node_id === other.node_id &&
      asset.item_id === other.item_id &&
      asset.slot_id === other.slot_id &&
      asset.semantic_type === other.semantic_type
    );
  });
}

export function sameV2AssetVersionMap(left: Record<string, AssetVersionV2[]> = {}, right: Record<string, AssetVersionV2[]> = {}) {
  if (left === right) return true;
  const leftKeys = Object.keys(left);
  const rightKeys = Object.keys(right);
  if (leftKeys.length !== rightKeys.length) return false;
  return leftKeys.every((key) => sameV2AssetVersionList(left[key] ?? [], right[key] ?? []));
}

export function sameV2LibraryReferenceOptions(left: V2LibraryReferenceOption[] = [], right: V2LibraryReferenceOption[] = []) {
  if (left === right) return true;
  if (left.length !== right.length) return false;
  return left.every((option, index) => {
    const other = right[index];
    return (
      option.entity_id === other.entity_id &&
      option.display_name === other.display_name &&
      option.library_asset_id === other.library_asset_id &&
      option.semantic_type === other.semantic_type
    );
  });
}

export function sameV2Items(left: WorkflowItemV2[] = [], right: WorkflowItemV2[] = []) {
  if (left === right) return true;
  if (left.length !== right.length) return false;
  return left.every((item, index) => {
    const other = right[index];
    return (
      item.item_id === other.item_id &&
      item.node_id === other.node_id &&
      item.item_type === other.item_type &&
      item.display_name === other.display_name &&
      item.description === other.description &&
      item.item_prompt === other.item_prompt &&
      item.prompt_source === other.prompt_source &&
      item.manual_prompt_dirty === other.manual_prompt_dirty &&
      item.status === other.status &&
      item.lifecycle_state === other.lifecycle_state &&
      item.shot_id === other.shot_id &&
      item.shot_index === other.shot_index &&
      item.aspect_ratio === other.aspect_ratio &&
      item.duration_seconds === other.duration_seconds &&
      item.shot_summary_prompt === other.shot_summary_prompt &&
      sameStringArray(item.reference_item_ids, other.reference_item_ids)
    );
  });
}

export function sameV2Slots(left: WorkflowSlotV2[] = [], right: WorkflowSlotV2[] = []) {
  if (left === right) return true;
  if (left.length !== right.length) return false;
  return left.every((slot, index) => {
    const other = right[index];
    return (
      slot.slot_id === other.slot_id &&
      slot.node_id === other.node_id &&
      slot.item_id === other.item_id &&
      slot.slot_type === other.slot_type &&
      slot.media_type === other.media_type &&
      slot.required === other.required &&
      slot.status === other.status &&
      slot.selected_asset_id === other.selected_asset_id &&
      slot.selected_version_id === other.selected_version_id &&
      slot.current_working_asset_id === other.current_working_asset_id &&
      slot.current_working_version_id === other.current_working_version_id &&
      slot.slot_prompt === other.slot_prompt &&
      slot.system_suggested_prompt === other.system_suggested_prompt &&
      slot.user_prompt === other.user_prompt &&
      slot.negative_prompt === other.negative_prompt &&
      slot.prompt_source === other.prompt_source &&
      slot.manual_prompt_dirty === other.manual_prompt_dirty &&
      slot.dialogue_prompt === other.dialogue_prompt &&
      slot.audio_description_prompt === other.audio_description_prompt &&
      slot.voice_style_prompt === other.voice_style_prompt &&
      slot.negative_constraints === other.negative_constraints &&
      sameStringArray(slot.media_prompt_asset_ids, other.media_prompt_asset_ids) &&
      sameStringArray(slot.implicit_reference_ids, other.implicit_reference_ids) &&
      sameStringArray(slot.explicit_reference_ids, other.explicit_reference_ids) &&
      sameStringArray(slot.dependency_slot_ids, other.dependency_slot_ids) &&
      sameStringArray(slot.history_version_ids, other.history_version_ids)
    );
  });
}

export function sameNodePorts(left: NodePort[] = [], right: NodePort[] = []) {
  if (left === right) return true;
  if (left.length !== right.length) return false;
  return left.every((port, index) => {
    const other = right[index];
    return (
      port.id === other.id &&
      port.label === other.label &&
      port.dataType === other.dataType &&
      port.required === other.required &&
      port.multiple === other.multiple
    );
  });
}

export function samePreviewAssets(left: UploadedAsset[] = [], right: UploadedAsset[] = []) {
  if (left === right) return true;
  if (left.length !== right.length) return false;
  return left.every((asset, index) => {
    const other = right[index];
    return (
      asset.asset_id === other.asset_id &&
      asset.filename === other.filename &&
      asset.local_path === other.local_path &&
      asset.url === other.url &&
      asset.public_url === other.public_url &&
      asset.preview_url === other.preview_url &&
      asset.thumbnail_url === other.thumbnail_url &&
      asset.media_type === other.media_type &&
      asset.asset_type === other.asset_type &&
      asset.semantic_type === other.semantic_type
    );
  });
}

function sameStringArray(left: string[] = [], right: string[] = []) {
  if (left === right) return true;
  if (left.length !== right.length) return false;
  return left.every((item, index) => item === right[index]);
}
