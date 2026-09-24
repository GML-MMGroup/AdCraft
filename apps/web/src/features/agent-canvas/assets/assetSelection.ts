import { mediaAssetContentPath, mediaAssetPreviewPath } from "../../../workflow/mediaPreview.ts";
import type {
  AgentCanvasAssetMediaTypeV2,
  CanvasBindingSourceImageAssetWriteV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";

export type AgentAssetScope = "project" | "my" | "recommended";

export type AgentAssetMediaFilter = "all" | AgentCanvasAssetMediaTypeV2;

export interface AgentAssetStableIdentity {
  source: AgentAssetScope;
  assetId: string;
  entityId: string | null;
  versionId: string | null;
}

export interface AgentAssetBrowserItem {
  id: string;
  assetId: string;
  source: AgentAssetScope;
  mediaType: AgentCanvasAssetMediaTypeV2;
  displayName: string;
  previewUrl: string | null;
  mediaUrl: string | null;
  status: "ready" | "unavailable";
  tags: string[];
  identity: AgentAssetStableIdentity;
  projectAsset: ProjectAssetSummaryV2 | null;
}

export interface AgentAssetReferenceSelection {
  source: AgentAssetScope;
  assetId: string;
  entityId: string | null;
  versionId: string | null;
  mediaType: "image";
  displayName: string;
}

export interface AgentAssetSourceNodeSelection {
  source: AgentAssetScope;
  assetId: string;
  entityId: string | null;
  versionId: string | null;
  mediaType: AgentCanvasAssetMediaTypeV2;
  displayName: string;
  durationSeconds: number | null;
  width: number | null;
  height: number | null;
}

export function toReferenceSelection(
  item: AgentAssetBrowserItem,
): AgentAssetReferenceSelection | null {
  if (item.mediaType !== "image") return null;
  return {
    source: item.source,
    assetId: item.identity.assetId,
    entityId: item.identity.entityId,
    versionId: item.identity.versionId,
    mediaType: "image",
    displayName: item.displayName,
  };
}

export function toImageBindingSource(
  selection: AgentAssetReferenceSelection,
): CanvasBindingSourceImageAssetWriteV2 {
  if (!selection.versionId) {
    throw new Error(`Image reference ${selection.displayName} has no immutable asset version.`);
  }
  return {
    kind: "image_asset",
    source_asset_id: selection.assetId,
    source_asset_version_id: selection.versionId,
  };
}

export function toSourceNodeSelection(
  item: AgentAssetBrowserItem,
): AgentAssetSourceNodeSelection | null {
  if (item.status !== "ready") return null;
  return {
    source: item.source,
    assetId: item.identity.assetId,
    entityId: item.identity.entityId,
    versionId: item.identity.versionId,
    mediaType: item.mediaType,
    displayName: item.displayName,
    durationSeconds: item.projectAsset?.duration_seconds ?? null,
    width: item.projectAsset?.width ?? null,
    height: item.projectAsset?.height ?? null,
  };
}

export function toProjectAssetBrowserItem(asset: ProjectAssetSummaryV2): AgentAssetBrowserItem {
  return {
    id: `project:${asset.asset_id}`,
    assetId: asset.asset_id,
    source: "project",
    mediaType: asset.media_type,
    displayName: asset.display_name,
    previewUrl: mediaAssetPreviewPath(asset) || null,
    mediaUrl: mediaAssetContentPath(asset) || null,
    status: asset.status,
    tags: [asset.source_type, asset.mime_type],
    identity: {
      source: "project",
      assetId: asset.asset_id,
      entityId: null,
      versionId: asset.version_id ?? null,
    },
    projectAsset: asset,
  };
}
