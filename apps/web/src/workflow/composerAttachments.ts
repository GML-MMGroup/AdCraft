import type { AssetLibraryReference, AssetReferenceSuggestion, UploadedAsset } from "../types.ts";
import type { V2InputAssetUploadItem } from "../types-v2.ts";
import {
  assetReferenceFromSuggestion,
  assetReferenceKey,
  defaultAssetReferenceRole,
} from "./assetMentions.ts";

export type ComposerAttachmentSource = "upload" | "asset_library" | "canvas_asset";

export type ComposerAttachment = {
  id: string;
  source: ComposerAttachmentSource;
  assetId?: string | null;
  entityId?: string | null;
  semanticType?: string | null;
  previewUrl?: string | null;
  filename?: string | null;
  mimeType?: string | null;
  inputAssetLocator?: string | null;
  reference: AssetLibraryReference;
};

export function composerAttachmentFromUploadedAsset(asset: UploadedAsset): ComposerAttachment | null {
  if (!isPreviewableImageAsset(asset)) return null;
  const entityId = firstString(asset.library_entity_id, asset.library_entity?.entity_id, asset.entity_id);
  const displayName = firstString(asset.library_entity?.display_name, asset.filename, asset.asset_id) ?? "Uploaded image";
  const referenceSource = entityId ? "asset_library" : "canvas_asset";
  const referenceAssetId = referenceSource === "asset_library" ? uploadedAssetLibraryAssetId(asset) : asset.asset_id ?? null;
  const reference: AssetLibraryReference = {
    reference_source: referenceSource,
    entity_id: referenceSource === "asset_library" ? entityId ?? null : null,
    asset_id: referenceAssetId,
    mention_text: `@${displayName}`,
    display_name: displayName,
    role: defaultAssetReferenceRole({
      entity_type: asset.entity_type,
      semantic_type: asset.semantic_type,
      asset_type: asset.asset_type,
    }),
    use_as_prompt: true,
  };
  return {
    id: composerAttachmentIdentity({
      assetId: referenceAssetId ?? asset.asset_id,
      entityId,
      semanticType: asset.semantic_type,
      previewUrl: uploadedAssetPreviewUrl(asset),
      reference,
    }),
    source: "upload",
    assetId: referenceAssetId ?? asset.asset_id,
    entityId,
    semanticType: asset.semantic_type,
    previewUrl: uploadedAssetPreviewUrl(asset),
    filename: asset.filename,
    mimeType: asset.mime_type,
    reference,
  };
}

export function composerAttachmentFromV2InputAsset(asset: V2InputAssetUploadItem): ComposerAttachment | null {
  if (!asset.locator) return null;
  const displayName = firstString(asset.display_name, asset.asset_id) ?? "Uploaded reference";
  const semanticType = firstString(asset.semantic_type) ?? "product_reference";
  const reference: AssetLibraryReference = {
    reference_source: "canvas_asset",
    entity_id: null,
    asset_id: asset.asset_id || null,
    mention_text: `@${displayName}`,
    display_name: displayName,
    role: defaultAssetReferenceRole({
      entity_type: semanticType === "product_reference" ? "product" : "",
      semantic_type: semanticType,
      asset_type: asset.media_type,
    }),
    use_as_prompt: true,
  };
  return {
    id: composerAttachmentIdentity({
      assetId: asset.asset_id,
      semanticType,
      previewUrl: asset.public_url,
      reference,
    }),
    source: "upload",
    assetId: asset.asset_id,
    semanticType,
    previewUrl: asset.public_url,
    filename: displayName,
    mimeType: null,
    inputAssetLocator: asset.locator,
    reference,
  };
}

export function composerAttachmentFromSuggestion(
  suggestion: AssetReferenceSuggestion,
  reference: AssetLibraryReference = assetReferenceFromSuggestion(suggestion),
): ComposerAttachment | null {
  if (!isPreviewableSuggestion(suggestion)) return null;
  const previewUrl = firstString(
    suggestion.thumbnail_url,
    suggestion.preview_url,
    suggestion.thumbnail_path,
    suggestion.local_path,
    suggestion.asset?.thumbnail_url,
    suggestion.asset?.preview_url,
    suggestion.asset?.thumbnail_path,
    suggestion.asset?.preview_path,
    suggestion.asset?.public_url,
    suggestion.asset?.url,
    suggestion.asset?.remote_url,
    suggestion.asset?.local_path,
  );
  const assetId = firstString(suggestion.asset_id, suggestion.asset?.asset_id, reference.asset_id);
  const entityId = firstString(suggestion.entity_id, suggestion.library_entity?.entity_id, reference.entity_id);
  const semanticType = firstString(suggestion.semantic_type, suggestion.asset?.semantic_type);
  return {
    id: composerAttachmentIdentity({ assetId, entityId, semanticType, previewUrl, reference }),
    source: suggestion.reference_source,
    assetId,
    entityId,
    semanticType,
    previewUrl,
    filename: suggestion.asset?.filename ?? suggestion.display_name,
    mimeType: suggestion.asset?.mime_type ?? null,
    reference,
  };
}

export function mergeComposerAttachments(...groups: Array<ComposerAttachment[] | undefined | null>) {
  const result: ComposerAttachment[] = [];
  const seen = new Set<string>();
  for (const group of groups) {
    for (const attachment of group ?? []) {
      const key = composerAttachmentKey(attachment);
      if (seen.has(key)) continue;
      seen.add(key);
      result.push(attachment);
    }
  }
  return result;
}

export function removeComposerAttachment(attachments: ComposerAttachment[], attachmentId: string) {
  return attachments.filter((attachment) => attachment.id !== attachmentId);
}

export function syncComposerAttachmentsWithReferences(
  attachments: ComposerAttachment[],
  references: AssetLibraryReference[],
) {
  const referenceKeys = new Set(references.map(assetReferenceKey));
  return attachments.filter((attachment) => attachment.source === "upload" || referenceKeys.has(assetReferenceKey(attachment.reference)));
}

export function composerAttachmentKey(attachment: ComposerAttachment) {
  return composerAttachmentIdentity(attachment);
}

function composerAttachmentIdentity(value: {
  assetId?: string | null;
  entityId?: string | null;
  semanticType?: string | null;
  previewUrl?: string | null;
  reference?: AssetLibraryReference;
}) {
  const source = value.reference?.reference_source;
  const referenceEntityId = firstString(value.reference?.entity_id);
  const referenceAssetId = firstString(value.reference?.asset_id);
  if (source === "asset_library" && referenceEntityId && referenceAssetId) return `asset_library:${referenceEntityId}:${referenceAssetId}`;
  if (source === "asset_library" && referenceEntityId) return `asset_library:${referenceEntityId}`;
  if (source === "canvas_asset" && referenceAssetId) return `canvas_asset:${referenceAssetId}`;
  const entityId = firstString(value.entityId, value.reference?.entity_id);
  const semanticType = firstString(value.semanticType);
  if (entityId) return `entity:${entityId}:${semanticType ?? ""}`;
  const assetId = firstString(value.assetId, value.reference?.asset_id);
  if (assetId) return `asset:${assetId}`;
  const url = firstString(value.previewUrl);
  if (url) return `url:${url}`;
  if (value.reference) return `reference:${assetReferenceKey(value.reference)}`;
  return "attachment:unknown";
}

function uploadedAssetLibraryAssetId(asset: UploadedAsset) {
  for (const id of asset.library_asset_ids ?? []) {
    const safeId = libraryAssetReferenceId(id);
    if (safeId) return safeId;
  }
  for (const libraryAsset of asset.library_assets ?? []) {
    const safeId = libraryAssetReferenceId(libraryAsset.asset_id);
    if (safeId) return safeId;
  }
  for (const libraryAsset of asset.library_entity?.assets ?? []) {
    const safeId = libraryAssetReferenceId(libraryAsset.asset_id);
    if (safeId) return safeId;
  }
  return null;
}

function libraryAssetReferenceId(value?: string | null) {
  if (!value?.trim()) return null;
  const assetId = value.trim();
  return /^asset_/i.test(assetId) ? null : assetId;
}

function uploadedAssetPreviewUrl(asset: UploadedAsset) {
  return firstString(
    asset.thumbnail_url,
    asset.preview_url,
    asset.public_url,
    asset.url,
    asset.remote_url,
    asset.thumbnail_path,
    asset.preview_path,
    asset.local_path,
    asset.uri,
  );
}

function isPreviewableImageAsset(asset: UploadedAsset) {
  return Boolean(
    String(asset.mime_type ?? "").toLowerCase().startsWith("image/") ||
      String(asset.asset_type ?? "").toLowerCase() === "image" ||
      uploadedAssetPreviewUrl(asset),
  );
}

function isPreviewableSuggestion(suggestion: AssetReferenceSuggestion) {
  const assetType = String(suggestion.asset_type ?? suggestion.asset?.asset_type ?? "").toLowerCase();
  const entityType = String(suggestion.entity_type ?? suggestion.library_entity?.entity_type ?? "").toLowerCase();
  const semanticType = String(suggestion.semantic_type ?? suggestion.asset?.semantic_type ?? "").toLowerCase();
  return Boolean(
    assetType === "image" ||
      entityType === "product" ||
      entityType === "character" ||
      entityType === "scene" ||
      entityType === "style_reference" ||
      semanticType.includes("image") ||
      semanticType.includes("view") ||
      semanticType.includes("reference") ||
      suggestion.thumbnail_url ||
      suggestion.preview_url ||
      suggestion.thumbnail_path ||
      suggestion.local_path ||
      suggestion.asset?.thumbnail_url ||
      suggestion.asset?.preview_url ||
      suggestion.asset?.thumbnail_path ||
      suggestion.asset?.preview_path ||
      suggestion.asset?.public_url ||
      suggestion.asset?.url ||
      suggestion.asset?.remote_url ||
      suggestion.asset?.local_path,
  );
}

function firstString(...values: Array<unknown>) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}
