import type { V2ReferenceSelectionsRequest, V2AssetReferenceSelection, V2AssetVersionReferenceSelection } from "../../../../types-v2.ts";

export type V2ReferenceSelection = V2AssetReferenceSelection | V2AssetVersionReferenceSelection;

export function v2ReferenceSelectionKey(selection: V2ReferenceSelection): string {
  return selection.selection_type === "entity"
    ? `entity:${selection.entity_id}`
    : `asset_version:${selection.asset_id}:${selection.version_id}`;
}

export function buildV2ReferenceSelectionsRequest(selections: V2ReferenceSelection[], referenceRole = "visual_reference"): V2ReferenceSelectionsRequest {
  return {
    selections,
    reference_role: referenceRole,
    use_as_prompt: true,
  };
}

export function toggleV2ReferenceSelection(current: V2ReferenceSelection[], next: V2ReferenceSelection): V2ReferenceSelection[] {
  const key = v2ReferenceSelectionKey(next);
  return current.some((selection) => v2ReferenceSelectionKey(selection) === key)
    ? current.filter((selection) => v2ReferenceSelectionKey(selection) !== key)
    : [...current, next];
}

export function hasV2ReferenceSelection(current: V2ReferenceSelection[], next: V2ReferenceSelection): boolean {
  const key = v2ReferenceSelectionKey(next);
  return current.some((selection) => v2ReferenceSelectionKey(selection) === key);
}
