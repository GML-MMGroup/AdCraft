import type { CanvasRuntimeEventV2, CanvasRuntimeModelResolutionV2 } from "../../../types-v2.ts";

function nonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function nonNegativeInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

/**
 * Runtime event payloads can contain a model resolution alongside other
 * provider data. Keep only the documented, non-secret identity fields.
 */
export function modelResolutionFromEvent(
  event: CanvasRuntimeEventV2,
): CanvasRuntimeModelResolutionV2 | null {
  if (!event.node_id || !event.payload) return null;
  const candidate = event.payload.model_resolution;
  if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return null;
  const record = candidate as Record<string, unknown>;
  const model_ref = nonEmptyString(record.model_ref);
  const provider_id = nonEmptyString(record.provider_id);
  const provider_model_id = nonEmptyString(record.provider_model_id);
  const credential_revision = nonNegativeInteger(record.credential_revision);
  const catalog_revision = nonNegativeInteger(record.catalog_revision);
  if (!model_ref || !provider_id || !provider_model_id || credential_revision === null || catalog_revision === null) {
    return null;
  }
  return {
    node_id: event.node_id,
    model_ref,
    provider_id,
    provider_model_id,
    credential_revision,
    catalog_revision,
  };
}
