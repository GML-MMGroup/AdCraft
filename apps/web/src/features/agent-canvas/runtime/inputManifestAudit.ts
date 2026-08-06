import type {
  AgentCanvasAssetMediaTypeV2,
  CanvasBindingInputRoleV2,
  CanvasRuntimeEventV2,
  ProviderInputManifestAuditV2,
  ProviderOmittedOptionalInputAuditV2,
  ProviderResolvedMediaInputAuditV2,
  ProviderResolvedTextInputAuditV2,
  ProviderResolvedWorldSettingInputAuditV1,
  UpstreamInputReadinessIssueV2,
  WorldSettingProjectionAudienceV1,
} from "../../../types-v2.ts";

const WORLD_SETTING_AUDIENCES = new Set<WorldSettingProjectionAudienceV1>([
  "shared",
  "script_writer",
  "product_designer",
  "prop_designer",
  "character_designer",
  "scene_designer",
  "storyboard_artist",
  "video_director",
  "bgm_director",
]);

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function string(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function optionalString(value: unknown): string | null {
  return value === null || value === undefined ? null : string(value);
}

function nonNegativeInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function inputRole(value: unknown): CanvasBindingInputRoleV2 | null {
  return value === "text_context"
    || value === "image_reference"
    || value === "video_reference"
    || value === "audio_reference"
    ? value
    : null;
}

function mediaType(value: unknown): AgentCanvasAssetMediaTypeV2 | null {
  return value === "image" || value === "video" || value === "audio" ? value : null;
}

function sorted<T extends { binding_id: string; display_order: number }>(items: T[]): T[] {
  return items.sort((left, right) => (
    left.display_order - right.display_order || left.binding_id.localeCompare(right.binding_id)
  ));
}

function textInput(value: unknown): ProviderResolvedTextInputAuditV2 | null {
  const item = record(value);
  if (!item) return null;
  const bindingId = string(item.binding_id);
  const sourceNodeId = string(item.source_node_id);
  const order = nonNegativeInteger(item.display_order);
  if (!bindingId || !sourceNodeId || order === null || item.input_role !== "text_context" || typeof item.required !== "boolean") {
    return null;
  }
  return {
    binding_id: bindingId,
    source_node_id: sourceNodeId,
    snapshot_id: optionalString(item.snapshot_id),
    input_role: "text_context",
    required: item.required,
    display_order: order,
  };
}

function mediaInput(value: unknown): ProviderResolvedMediaInputAuditV2 | null {
  const item = record(value);
  if (!item) return null;
  const bindingId = string(item.binding_id);
  const assetId = string(item.asset_id);
  const role = inputRole(item.input_role);
  const type = mediaType(item.media_type);
  const order = nonNegativeInteger(item.display_order);
  if (!bindingId || !assetId || !role || !type || order === null || typeof item.required !== "boolean") return null;
  return {
    binding_id: bindingId,
    source_node_id: optionalString(item.source_node_id),
    asset_id: assetId,
    media_type: type,
    input_role: role,
    source_semantic_role: optionalString(item.source_semantic_role),
    transport_type: optionalString(item.transport_type),
    required: item.required,
    display_order: order,
  };
}

function worldSettingInput(value: unknown): ProviderResolvedWorldSettingInputAuditV1 | null {
  const item = record(value);
  if (!item) return null;
  const bindingId = string(item.binding_id);
  const sourceNodeId = string(item.source_node_id);
  const sourceNodeRevision = nonNegativeInteger(item.source_node_revision);
  const order = nonNegativeInteger(item.display_order);
  const audience = string(item.projection_audience) as WorldSettingProjectionAudienceV1 | null;
  const projectionSnapshotId = string(item.projection_snapshot_id);
  const projectionMode = item.projection_mode === "ready" || item.projection_mode === "fallback"
    ? item.projection_mode
    : null;
  if (
    !bindingId
    || !sourceNodeId
    || sourceNodeRevision === null
    || sourceNodeRevision < 1
    || order === null
    || !audience
    || !WORLD_SETTING_AUDIENCES.has(audience)
    || item.projection_contract_version !== "world-setting-projection-v1"
    || !projectionSnapshotId
    || !projectionMode
    || typeof item.required !== "boolean"
  ) return null;
  return {
    binding_id: bindingId,
    source_node_id: sourceNodeId,
    source_node_revision: sourceNodeRevision,
    required: item.required,
    display_order: order,
    projection_audience: audience,
    projection_contract_version: "world-setting-projection-v1",
    projection_snapshot_id: projectionSnapshotId,
    projection_mode: projectionMode,
    warning_code: optionalString(item.warning_code),
  };
}

function omittedOptionalInput(value: unknown): ProviderOmittedOptionalInputAuditV2 | null {
  const item = record(value);
  if (!item) return null;
  const bindingId = string(item.binding_id);
  const reasonCode = string(item.reason_code);
  if (!bindingId || !reasonCode) return null;
  return {
    binding_id: bindingId,
    source_node_id: optionalString(item.source_node_id),
    reason_code: reasonCode,
  };
}

export function inputManifestAuditFromEvent(
  event: CanvasRuntimeEventV2,
): ProviderInputManifestAuditV2 | null {
  if (event.event_type !== "provider_inputs_resolved" || !event.node_id) return null;
  const payload = event.payload;
  const manifestId = payload ? string(payload.input_manifest_id) : null;
  if (!payload || !manifestId) return null;
  const textInputs = Array.isArray(payload.text_inputs)
    ? sorted(payload.text_inputs.map(textInput).filter((item): item is ProviderResolvedTextInputAuditV2 => Boolean(item)))
    : [];
  const worldSettingInputs = Array.isArray(payload.world_setting_inputs)
    ? sorted(payload.world_setting_inputs
      .map(worldSettingInput)
      .filter((item): item is ProviderResolvedWorldSettingInputAuditV1 => Boolean(item)))
    : [];
  const mediaInputs = Array.isArray(payload.media_inputs)
    ? sorted(payload.media_inputs.map(mediaInput).filter((item): item is ProviderResolvedMediaInputAuditV2 => Boolean(item)))
    : [];
  const omitted = Array.isArray(payload.omitted_optional_inputs)
    ? payload.omitted_optional_inputs
      .map(omittedOptionalInput)
      .filter((item): item is ProviderOmittedOptionalInputAuditV2 => Boolean(item))
    : [];
  return {
    node_id: event.node_id,
    input_manifest_id: manifestId,
    execution_id: event.execution_id,
    node_run_id: optionalString(payload.node_run_id),
    text_inputs: textInputs,
    world_setting_inputs: worldSettingInputs,
    media_inputs: mediaInputs,
    omitted_optional_inputs: omitted,
  };
}

export function upstreamInputReadinessIssueFromDetails(
  targetNodeId: string,
  details: Record<string, unknown>,
): UpstreamInputReadinessIssueV2 | null {
  const missing = Array.isArray(details.missing_required_source_node_ids)
    ? details.missing_required_source_node_ids.map(string).filter((item): item is string => Boolean(item))
    : [];
  const fallback = string(details.source_node_id);
  const sourceNodeIds = [...new Set(missing.length ? missing : fallback ? [fallback] : [])];
  return sourceNodeIds.length ? { target_node_id: targetNodeId, source_node_ids: sourceNodeIds } : null;
}
