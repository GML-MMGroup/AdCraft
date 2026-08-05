import type {
  AgentCanvasAssetMediaTypeV2,
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
