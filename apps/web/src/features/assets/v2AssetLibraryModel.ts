import type {
  V2AssetLibraryCategory,
  V2AssetLibraryEntityDetail,
  V2AssetLibraryEntitySummary,
  V2AssetLibraryMember,
  V2AssetLibraryPreviewMember,
  V2AssetVersionReferenceSelection,
  V2AssetReferenceSelection,
} from "../../types-v2.ts";

export const V2_ASSET_LIBRARY_CATEGORIES: Array<{ id: V2AssetLibraryCategory; label: string; entityType: string }> = [
  { id: "characters", label: "Characters", entityType: "character" },
  { id: "scenes", label: "Scenes", entityType: "scene" },
  { id: "props", label: "Props", entityType: "product" },
];

export function v2AssetCategoryForEntityType(entityType: string): V2AssetLibraryCategory | null {
  if (entityType === "character") return "characters";
  if (entityType === "scene") return "scenes";
  if (entityType === "product") return "props";
  return null;
}

export function v2AssetEntityTypeForCategory(category: V2AssetLibraryCategory): string {
  return V2_ASSET_LIBRARY_CATEGORIES.find((item) => item.id === category)?.entityType ?? "product";
}

export function v2AssetPreviewUrl(entity: Pick<V2AssetLibraryEntitySummary, "preview_url" | "preview_member"> | V2AssetLibraryMember | null | undefined): string | null {
  if (!entity) return null;
  if (!("asset_id" in entity) && entity.preview_url) return entity.preview_url;
  const member: V2AssetLibraryPreviewMember | null | undefined = "asset_id" in entity ? entity : entity.preview_member;
  return member?.thumbnail_url || member?.public_url || null;
}

export function v2AssetMediaUrl(member: V2AssetLibraryMember | null | undefined): string | null {
  return member?.public_url || null;
}

export function v2AssetSelectionKey(selection: V2AssetReferenceSelection | V2AssetVersionReferenceSelection): string {
  return selection.selection_type === "entity"
    ? `entity:${selection.entity_id}`
    : `asset_version:${selection.asset_id}:${selection.version_id}`;
}

export function v2EntitySelection(entity: V2AssetLibraryEntitySummary): V2AssetReferenceSelection {
  return { selection_type: "entity", entity_id: entity.entity_id };
}

export function v2MemberSelection(member: Pick<V2AssetLibraryMember, "asset_id" | "version_id">): V2AssetVersionReferenceSelection {
  return { selection_type: "asset_version", asset_id: member.asset_id, version_id: member.version_id };
}

export function v2DefaultMemberSelections(entity: V2AssetLibraryEntityDetail): V2AssetVersionReferenceSelection[] {
  return entity.members
    .filter((member) => member.is_default_reference)
    .map(v2MemberSelection);
}

export function v2AssetEntityDisplay(entity: Pick<V2AssetLibraryEntitySummary, "display_name" | "member_count">): string {
  return entity.member_count === 1 ? entity.display_name : `${entity.display_name} · ${entity.member_count} views`;
}

export function splitAssetLibraryTags(value: string): string[] {
  return value
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}
