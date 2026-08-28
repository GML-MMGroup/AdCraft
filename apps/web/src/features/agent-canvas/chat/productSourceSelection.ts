import type { GuidedProductAssetVersionRefV1 } from "../../../types-v2.ts";

export type ProductSourceInputKind = "main" | "multiview";

export interface ProductSourceAssetVersionDraftItem {
  kind: "asset_version";
  key: string;
  assetId: string;
  versionId: string;
  displayName: string;
  previewUrl: string | null;
  pendingHandoffId: string | null;
}

export interface ProductSourceLocalFileDraftItem {
  kind: "local_file";
  key: string;
  file: File;
  displayName: string;
  previewUrl: string;
  uploadIdempotencyKey: string;
}

export type ProductSourceDraftItem =
  | ProductSourceAssetVersionDraftItem
  | ProductSourceLocalFileDraftItem;

export type ProductSourceSelectionErrorCode =
  | "duplicate"
  | "max_count"
  | "unresolved_upload"
  | "conflicting_handoff";

export class ProductSourceSelectionError extends Error {
  readonly code: ProductSourceSelectionErrorCode;

  constructor(code: ProductSourceSelectionErrorCode, message: string) {
    super(message);
    this.name = "ProductSourceSelectionError";
    this.code = code;
  }
}

export interface ProductSourceUploadedIdentity {
  assetId: string;
  versionId: string;
  pendingHandoffId: string | null;
}

export function createAssetVersionDraftItem(input: {
  assetId: string;
  versionId: string;
  displayName: string;
  previewUrl: string | null;
  pendingHandoffId?: string | null;
}): ProductSourceAssetVersionDraftItem {
  return {
    kind: "asset_version",
    key: `asset-version:${input.assetId}:${input.versionId}`,
    ...input,
    pendingHandoffId: input.pendingHandoffId ?? null,
  };
}

export function createLocalFileDraftItem(
  file: File,
  uploadIdempotencyKey: string,
  previewUrl: string,
): ProductSourceLocalFileDraftItem {
  return {
    kind: "local_file",
    key: `local-file:${file.name}:${file.size}:${file.type}:${file.lastModified}`,
    file,
    displayName: file.name || "Uploaded Product source",
    previewUrl,
    uploadIdempotencyKey,
  };
}

export function addProductSourceItem(
  current: readonly ProductSourceDraftItem[],
  item: ProductSourceDraftItem,
  inputKind: ProductSourceInputKind,
  maxAssetCount: number,
): ProductSourceDraftItem[] {
  if (inputKind === "main") return [item];
  if (current.some((candidate) => candidate.key === item.key)) {
    throw new ProductSourceSelectionError("duplicate", "This Product source is already selected.");
  }
  if (current.length >= maxAssetCount) {
    throw new ProductSourceSelectionError(
      "max_count",
      `You can select at most ${maxAssetCount} Product source${maxAssetCount === 1 ? "" : "s"}.`,
    );
  }
  return [...current, item];
}

export function removeProductSourceItem(
  current: readonly ProductSourceDraftItem[],
  key: string,
): ProductSourceDraftItem[] {
  return current.filter((item) => item.key !== key);
}

export function moveProductSourceItem(
  current: readonly ProductSourceDraftItem[],
  key: string,
  direction: -1 | 1,
): ProductSourceDraftItem[] {
  const index = current.findIndex((item) => item.key === key);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= current.length) return [...current];
  const next = [...current];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

export function validateProductSourceDraft(
  current: readonly ProductSourceDraftItem[],
  inputKind: ProductSourceInputKind,
  minAssetCount: number,
  maxAssetCount: number,
): string | null {
  if (current.length >= minAssetCount && current.length <= maxAssetCount) return null;
  if (inputKind === "main") return `Select exactly ${minAssetCount} Product source.`;
  return `Select ${minAssetCount}-${maxAssetCount} Product sources.`;
}

export function resolveProductSourceAssetVersions(
  current: readonly ProductSourceDraftItem[],
  uploadedByDraftKey: ReadonlyMap<string, ProductSourceUploadedIdentity>,
): {
  assetVersions: GuidedProductAssetVersionRefV1[];
  pendingHandoffId: string | null;
} {
  const pendingHandoffIds = new Set<string>();
  const assetVersions = current.map((item) => {
    if (item.kind === "asset_version") {
      if (item.pendingHandoffId) pendingHandoffIds.add(item.pendingHandoffId);
      return { asset_id: item.assetId, version_id: item.versionId };
    }
    const uploaded = uploadedByDraftKey.get(item.key);
    if (!uploaded) {
      throw new ProductSourceSelectionError(
        "unresolved_upload",
        "A Product upload did not return an immutable AssetVersion.",
      );
    }
    if (uploaded.pendingHandoffId) pendingHandoffIds.add(uploaded.pendingHandoffId);
    return { asset_id: uploaded.assetId, version_id: uploaded.versionId };
  });

  if (pendingHandoffIds.size > 1) {
    throw new ProductSourceSelectionError(
      "conflicting_handoff",
      "The Product uploads returned conflicting pending handoffs.",
    );
  }
  if (new Set(assetVersions.map((item) => `${item.asset_id}:${item.version_id}`)).size !== assetVersions.length) {
    throw new ProductSourceSelectionError("duplicate", "This Product source is already selected.");
  }

  return {
    assetVersions,
    pendingHandoffId: pendingHandoffIds.values().next().value ?? null,
  };
}
