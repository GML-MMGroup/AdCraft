import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { agentCanvasApi } from "../../../api/agentCanvasApi.ts";
import { createOperationKey } from "../../../api/operationKey.ts";
import type {
  AgentCanvasAssetMediaTypeV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import type {
  AgentAssetBrowserItem,
  AgentAssetMediaFilter,
  AgentAssetScope,
} from "./assetSelection.ts";

type LibraryRecord = Record<string, unknown>;

export interface AgentAssetUploadOptions {
  semanticRole?: string | null;
  metadata?: Record<string, unknown>;
}

export interface UseAgentCanvasAssetsOptions {
  workflowId: string;
  scope: AgentAssetScope;
  category?: string | null;
  mediaType?: AgentAssetMediaFilter;
  search?: string;
}

export interface UseAgentCanvasAssetsResult {
  items: AgentAssetBrowserItem[];
  loading: boolean;
  error: string | null;
  uploading: boolean;
  uploadError: string | null;
  retry: () => Promise<void>;
  uploadFiles: (
    files: Iterable<File>,
    options?: AgentAssetUploadOptions,
  ) => Promise<ProjectAssetSummaryV2[]>;
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) return error.message;
  return fallback;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function recordValue(value: unknown): LibraryRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as LibraryRecord
    : null;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const normalized = stringValue(item);
    return normalized ? [normalized] : [];
  });
}

function projectItem(asset: ProjectAssetSummaryV2): AgentAssetBrowserItem {
  return {
    id: `project:${asset.asset_id}`,
    assetId: asset.asset_id,
    source: "project",
    mediaType: asset.media_type,
    displayName: asset.display_name,
    previewUrl: asset.preview_url,
    mediaUrl: asset.media_url,
    status: asset.status,
    tags: [asset.source_type, asset.mime_type],
    identity: {
      source: "project",
      assetId: asset.asset_id,
      entityId: null,
      versionId: null,
    },
    projectAsset: asset,
  };
}

function libraryItem(
  scope: "my" | "recommended",
  value: LibraryRecord,
): AgentAssetBrowserItem | null {
  const previewMember = recordValue(value.preview_member);
  const mediaType = stringValue(previewMember?.media_type);
  if (mediaType && mediaType !== "image") return null;

  const entityId = stringValue(value.entity_id);
  const assetId = stringValue(previewMember?.asset_id) ?? stringValue(value.asset_id);
  if (!entityId || !assetId) return null;

  const displayName = stringValue(value.display_name) ?? entityId;
  const previewUrl =
    stringValue(value.preview_url)
    ?? stringValue(previewMember?.thumbnail_url)
    ?? stringValue(previewMember?.public_url);
  return {
    id: `${scope}:${entityId}`,
    assetId,
    source: scope,
    mediaType: "image",
    displayName,
    previewUrl,
    mediaUrl: stringValue(previewMember?.public_url) ?? previewUrl,
    status: stringValue(value.status) === "unavailable" ? "unavailable" : "ready",
    tags: stringList(value.tags),
    identity: {
      source: scope,
      assetId,
      entityId,
      versionId: stringValue(previewMember?.version_id) ?? stringValue(value.version_id),
    },
    projectAsset: null,
  };
}

function mediaTypeForFile(file: File): AgentCanvasAssetMediaTypeV2 {
  const [family] = file.type.toLowerCase().split("/");
  if (family === "image" || family === "video" || family === "audio") return family;
  throw new Error(`Unsupported media type for ${file.name || "selected file"}.`);
}

function titleForFile(file: File): string {
  const name = file.name.trim() || "Uploaded media";
  const extensionIndex = name.lastIndexOf(".");
  return extensionIndex > 0 ? name.slice(0, extensionIndex) : name;
}

export function useAgentCanvasAssets({
  workflowId,
  scope,
  category = null,
  mediaType = "all",
  search = "",
}: UseAgentCanvasAssetsOptions): UseAgentCanvasAssetsResult {
  const [allItems, setAllItems] = useState<AgentAssetBrowserItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const requestIdRef = useRef(0);

  const load = useCallback(async (): Promise<void> => {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError(null);
    try {
      let nextItems: AgentAssetBrowserItem[];
      if (scope === "project") {
        const response = await agentCanvasApi.listAgentCanvasProjectAssets(workflowId);
        nextItems = response.assets.map(projectItem);
      } else {
        const response = scope === "my"
          ? await agentCanvasApi.listAgentCanvasMyAssets(category)
          : await agentCanvasApi.listAgentCanvasRecommendedAssets(category);
        nextItems = response.items.flatMap((item) => {
          const normalized = libraryItem(scope, item);
          return normalized ? [normalized] : [];
        });
      }
      if (requestId === requestIdRef.current) setAllItems(nextItems);
    } catch (loadError) {
      if (requestId === requestIdRef.current) {
        setAllItems([]);
        setError(errorMessage(loadError, "Unable to load assets."));
      }
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, [category, scope, workflowId]);

  useEffect(() => {
    void load();
    return () => {
      requestIdRef.current += 1;
    };
  }, [load]);

  const uploadFiles = useCallback(async (
    files: Iterable<File>,
    options: AgentAssetUploadOptions = {},
  ): Promise<ProjectAssetSummaryV2[]> => {
    if (scope !== "project") {
      throw new Error("Uploads are available only in Project Assets.");
    }
    const selectedFiles = Array.from(files);
    if (selectedFiles.length === 0) return [];

    setUploading(true);
    setUploadError(null);
    try {
      const uploaded: ProjectAssetSummaryV2[] = [];
      for (const file of selectedFiles) {
        const metadata = {
          media_type: mediaTypeForFile(file),
          title: titleForFile(file),
          semantic_role: options.semanticRole ?? null,
          metadata: options.metadata ?? {},
        };
        const formData = new FormData();
        formData.append("file", file);
        formData.append("metadata", JSON.stringify(metadata));
        const response = await agentCanvasApi.uploadAgentCanvasAsset(
          workflowId,
          formData,
          createOperationKey("asset-upload"),
        );
        uploaded.push(response.asset);
      }
      await load();
      return uploaded;
    } catch (uploadFailure) {
      const message = errorMessage(uploadFailure, "Unable to upload media.");
      setUploadError(message);
      throw uploadFailure;
    } finally {
      setUploading(false);
    }
  }, [load, scope, workflowId]);

  const items = useMemo(() => {
    const normalizedSearch = search.trim().toLocaleLowerCase();
    return allItems.filter((item) => {
      if (mediaType !== "all" && item.mediaType !== mediaType) return false;
      if (!normalizedSearch) return true;
      return [item.displayName, item.assetId, ...item.tags]
        .some((value) => value.toLocaleLowerCase().includes(normalizedSearch));
    });
  }, [allItems, mediaType, search]);

  return {
    items,
    loading,
    error,
    uploading,
    uploadError,
    retry: load,
    uploadFiles,
  };
}
