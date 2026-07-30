import type {
  CanvasInputRoleV2,
  CanvasRuntimeEventV2,
} from "../../../types-v2.ts";

const INPUT_ROLES = new Set<CanvasInputRoleV2>([
  "instruction",
  "visual_reference",
  "first_frame",
  "motion_reference",
  "source_video",
  "audio_reference",
]);
const MEDIA_TYPES = new Set(["image", "video", "audio"]);
const SOURCE_TYPES = new Set(["text", "script"]);

export interface ProviderResolvedInputSummary {
  binding_id: string;
  asset_id: string | null;
  source_node_id: string | null;
  source_type: "text" | "script" | null;
  media_type: "image" | "video" | "audio" | null;
  input_role: CanvasInputRoleV2;
  source_semantic_role: string | null;
  reference_purpose: string | null;
  required: boolean | null;
  display_order: number;
  label: string;
}

export interface ProviderOptionalInputOmission {
  binding_id: string;
  reason: string;
}

export interface ProviderInputsResolvedState {
  node_id: string;
  model_id: string | null;
  input_counts: Partial<Record<"text" | "script" | "image" | "video" | "audio", number>>;
  inputs: ProviderResolvedInputSummary[];
  requested_duration_seconds: number | null;
  effective_duration_seconds: number | null;
  normalizations: string[];
  omitted_optional_inputs: ProviderOptionalInputOmission[];
  event_seq: number;
}

type UnknownRecord = Record<string, unknown>;

function record(value: unknown): UnknownRecord | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as UnknownRecord
    : null;
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function nullableString(value: unknown): string | null {
  return value === null || value === undefined ? null : nonEmptyString(value);
}

function nonNegativeInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
    ? value
    : null;
}

function positiveNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? value
    : null;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function normalizeInput(value: unknown): ProviderResolvedInputSummary | null {
  const item = record(value);
  if (!item) return null;
  const bindingId = nonEmptyString(item.binding_id);
  const label = nonEmptyString(item.label);
  const inputRole = nonEmptyString(item.input_role);
  const displayOrder = nonNegativeInteger(item.display_order);
  if (
    !bindingId
    || !label
    || !inputRole
    || !INPUT_ROLES.has(inputRole as CanvasInputRoleV2)
    || displayOrder === null
  ) {
    return null;
  }
  const mediaType = nonEmptyString(item.media_type);
  const sourceType = nonEmptyString(item.source_type);
  return {
    binding_id: bindingId,
    asset_id: nullableString(item.asset_id),
    source_node_id: nullableString(item.source_node_id),
    source_type: sourceType && SOURCE_TYPES.has(sourceType)
      ? sourceType as "text" | "script"
      : null,
    media_type: mediaType && MEDIA_TYPES.has(mediaType)
      ? mediaType as "image" | "video" | "audio"
      : null,
    input_role: inputRole as CanvasInputRoleV2,
    source_semantic_role: nullableString(item.source_semantic_role),
    reference_purpose: nullableString(item.reference_purpose),
    required: typeof item.required === "boolean" ? item.required : null,
    display_order: displayOrder,
    label,
  };
}

function normalizeInputCounts(
  value: unknown,
): ProviderInputsResolvedState["input_counts"] {
  const counts = record(value);
  if (!counts) return {};
  return Object.fromEntries(
    ["text", "script", "image", "video", "audio"].flatMap((key) => {
      const count = nonNegativeInteger(counts[key]);
      return count === null ? [] : [[key, count]];
    }),
  );
}

function normalizeOmissions(value: unknown): ProviderOptionalInputOmission[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((candidate) => {
    const item = record(candidate);
    const bindingId = nonEmptyString(item?.binding_id);
    const reason = nonEmptyString(item?.reason);
    return bindingId && reason ? [{ binding_id: bindingId, reason }] : [];
  });
}

export function parseProviderInputsResolvedEvent(
  event: CanvasRuntimeEventV2,
): ProviderInputsResolvedState | null {
  if (event.event_type !== "provider_inputs_resolved") return null;
  const payload = record(event.payload);
  if (!payload) return null;
  const manifest = record(payload.seedance_input_manifest) ?? payload;
  const nodeId = nonEmptyString(manifest.node_id)
    ?? nonEmptyString(payload.node_id)
    ?? event.node_id;
  if (!nodeId) return null;

  const directInputs = Array.isArray(payload.inputs) ? payload.inputs : null;
  const inputs = (
    directInputs
    ?? [
      ...(Array.isArray(manifest.text_inputs) ? manifest.text_inputs : []),
      ...(Array.isArray(manifest.media_inputs) ? manifest.media_inputs : []),
    ]
  )
    .map(normalizeInput)
    .filter((item): item is ProviderResolvedInputSummary => item !== null)
    .sort((left, right) => (
      left.display_order - right.display_order
      || left.binding_id.localeCompare(right.binding_id)
    ));

  return {
    node_id: nodeId,
    model_id: nullableString(manifest.model_id ?? payload.model_id),
    input_counts: normalizeInputCounts(manifest.input_counts ?? payload.input_counts),
    inputs,
    requested_duration_seconds: positiveNumber(
      manifest.requested_duration_seconds ?? payload.requested_duration_seconds,
    ),
    effective_duration_seconds: positiveNumber(
      manifest.effective_duration_seconds ?? payload.effective_duration_seconds,
    ),
    normalizations: stringList(manifest.normalizations ?? payload.normalizations),
    omitted_optional_inputs: normalizeOmissions(
      payload.omitted_optional_inputs ?? payload.optional_input_omissions,
    ),
    event_seq: event.seq,
  };
}

export function resolvedInputPurposeLabel(
  input: ProviderResolvedInputSummary,
): string {
  if (
    input.source_semantic_role === "storyboard_grid"
    && input.reference_purpose === "storyboard_sequence"
  ) {
    return "Storyboard Grid";
  }
  if (
    input.source_semantic_role === "scene_design_board"
    && input.reference_purpose === "scene_reference"
  ) {
    return "Scene Design Board";
  }
  return input.label;
}

export function durationHintForResolvedInputs(
  resolved: ProviderInputsResolvedState,
): string | null {
  if (
    !resolved.normalizations.includes("duration_clamped_to_provider_limit")
    || resolved.effective_duration_seconds === null
  ) {
    return null;
  }
  const requested = resolved.requested_duration_seconds;
  return requested === null
    ? `The selected provider will generate a ${resolved.effective_duration_seconds}-second clip.`
    : `The requested ${requested}-second clip was adjusted to a ${resolved.effective_duration_seconds}-second clip for the selected provider.`;
}
