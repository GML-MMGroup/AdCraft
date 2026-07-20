import type { UploadedAsset } from "../types";
import { dedupeAssets } from "./assets.ts";

export type SemanticGalleryKind = "character" | "scene";

export type SemanticGalleryItem = {
  id: string;
  title: string;
  main?: UploadedAsset;
  face?: UploadedAsset;
  threeView?: UploadedAsset;
  multiView?: UploadedAsset;
};

export type SemanticAssetGallery = {
  kind: SemanticGalleryKind;
  items: SemanticGalleryItem[];
};

type SemanticGallerySlot = "main" | "face" | "threeView" | "multiView";
type UploadedAssetRecord = UploadedAsset & Record<string, unknown>;
type AssetGroup = Partial<Record<SemanticGallerySlot, UploadedAsset>>;

const CHARACTER_SEMANTIC_TYPES: Record<string, SemanticGallerySlot> = {
  character_main: "main",
  character_face_id: "face",
  character_three_view: "threeView",
};

const SCENE_SEMANTIC_TYPES: Record<string, SemanticGallerySlot> = {
  scene_main: "main",
  scene_multi_view: "multiView",
};

export function isSemanticGalleryNode(nodeType?: string | null) {
  const normalized = normalizeNodeKey(nodeType);
  return normalized === "character-generation" || normalized === "scene-generation";
}

export function semanticGalleryPreviewAssets(nodeType: string, assets: UploadedAsset[]) {
  return isSemanticGalleryNode(nodeType) ? assets : assets.slice(0, 3);
}

export function buildSemanticAssetGallery({
  nodeType,
  output,
  assets,
}: {
  nodeType: string;
  output?: Record<string, unknown> | null;
  assets: UploadedAsset[];
}): SemanticAssetGallery | null {
  const kind = semanticGalleryKind(nodeType);
  if (!kind) return null;

  const semanticAssets = semanticAssetsForKind(kind, [...assetsFromOutput(output), ...assets]);
  const assetGroups = groupSemanticAssets(kind, semanticAssets);
  const structuredItems = structuredGalleryItems(kind, output, assetGroups);
  const items = structuredItems.length ? structuredItems : fallbackGalleryItems(kind, assetGroups);
  const visibleItems = items.filter(hasGalleryAsset);

  return visibleItems.length ? { kind, items: visibleItems } : null;
}

function semanticGalleryKind(nodeType: string): SemanticGalleryKind | null {
  const normalized = normalizeNodeKey(nodeType);
  if (normalized === "character-generation") return "character";
  if (normalized === "scene-generation") return "scene";
  return null;
}

function structuredGalleryItems(kind: SemanticGalleryKind, output: Record<string, unknown> | null | undefined, assetGroups: Map<string, AssetGroup>) {
  const structuredOutput = recordValue(output?.structured_output);
  const records = kind === "character" ? arrayRecords(structuredOutput?.characters) : arrayRecords(structuredOutput?.scenes);

  return records.map((record, index) => {
    const id = entityIdFromRecord(record, kind, index);
    const fallbackAssets = assetGroups.get(id) ?? {};
    const title = entityTitleFromRecord(record, kind, index);

    if (kind === "character") {
      return {
        id,
        title,
        main: assetFromRecordField(record, ["roleMainImageUri", "role_main_image_uri", "mainImageUri", "main_image_uri"], "character", "character_main", id, `${title} main`) ?? fallbackAssets.main,
        face: assetFromRecordField(record, ["roleFaceIdImageUri", "role_face_id_image_uri", "faceIdImageUri", "face_id_image_uri"], "character", "character_face_id", id, `${title} face`) ?? fallbackAssets.face,
        threeView: assetFromRecordField(record, ["roleThreeViewImageUri", "role_three_view_image_uri", "threeViewImageUri", "three_view_image_uri"], "character", "character_three_view", id, `${title} three view`) ?? fallbackAssets.threeView,
      };
    }

    return {
      id,
      title,
      main: assetFromRecordField(record, ["sceneMainImageUri", "scene_main_image_uri", "mainImageUri", "main_image_uri"], "scene", "scene_main", id, `${title} main`) ?? fallbackAssets.main,
      multiView: assetFromRecordField(record, ["sceneMultiViewImageUri", "scene_multi_view_image_uri", "multiViewImageUri", "multi_view_image_uri"], "scene", "scene_multi_view", id, `${title} multi view`) ?? fallbackAssets.multiView,
    };
  });
}

function fallbackGalleryItems(kind: SemanticGalleryKind, assetGroups: Map<string, AssetGroup>) {
  return Array.from(assetGroups.entries()).map(([id, assets], index) => ({
    id,
    title: galleryFallbackTitle(kind, index),
    ...assets,
  }));
}

function groupSemanticAssets(kind: SemanticGalleryKind, assets: UploadedAsset[]) {
  const result = new Map<string, AssetGroup>();
  assets.forEach((asset, index) => {
    const slot = semanticSlotForAsset(kind, asset);
    if (!slot) return;
    const id = semanticAssetEntityId(asset, kind, index);
    const group = result.get(id) ?? {};
    if (!group[slot]) group[slot] = asset;
    result.set(id, group);
  });
  return result;
}

function semanticAssetsForKind(kind: SemanticGalleryKind, assets: UploadedAsset[]) {
  return dedupeAssets(assets.filter((asset) => Boolean(semanticSlotForAsset(kind, asset))));
}

function semanticSlotForAsset(kind: SemanticGalleryKind, asset: UploadedAsset) {
  const semanticType = semanticTypeForAsset(asset);
  return kind === "character" ? CHARACTER_SEMANTIC_TYPES[semanticType] : SCENE_SEMANTIC_TYPES[semanticType];
}

function semanticTypeForAsset(asset: UploadedAsset) {
  const record = asset as UploadedAssetRecord;
  const metadata = recordValue(record.metadata);
  return normalizeKey(record.semantic_type ?? record.semanticType ?? metadata?.semantic_type ?? metadata?.semanticType);
}

function semanticAssetEntityId(asset: UploadedAsset, kind: SemanticGalleryKind, index: number) {
  const record = asset as UploadedAssetRecord;
  const metadata = recordValue(record.metadata);
  return (
    stringValue(record.entity_id) ||
    stringValue(record.entityId) ||
    stringValue(record.character_id) ||
    stringValue(record.characterId) ||
    stringValue(record.scene_id) ||
    stringValue(record.sceneId) ||
    stringValue(metadata?.entity_id) ||
    stringValue(metadata?.entityId) ||
    stringValue(record.asset_id) ||
    `${kind}-${index + 1}`
  );
}

function assetsFromOutput(output: Record<string, unknown> | null | undefined) {
  const outputAssets = assetArray(output?.output_assets);
  return outputAssets.length ? outputAssets : assetArray(output?.assets);
}

function assetArray(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object")).map(normalizeAssetRecord) : [];
}

function normalizeAssetRecord(record: Record<string, unknown>, index: number): UploadedAsset {
  const path = stringValue(record.local_path) || stringValue(record.public_url) || stringValue(record.remote_url) || stringValue(record.url) || stringValue(record.preview_path) || stringValue(record.thumbnail_path);
  const assetType = normalizeAssetType(record.asset_type, path);
  return {
    ...record,
    asset_id: stringValue(record.asset_id) || stringValue(record.id) || `semantic-asset-${index + 1}`,
    asset_type: assetType,
    asset_role: normalizeAssetRole(record.asset_role),
    filename: stringValue(record.filename) || stringValue(record.name) || stringValue(record.asset_id) || `asset-${index + 1}`,
    mime_type: stringValue(record.mime_type) || stringValue(record.content_type) || (assetType === "image" ? "image/*" : ""),
    local_path: stringValue(record.local_path) || path,
  } as UploadedAsset;
}

function assetFromRecordField(
  record: Record<string, unknown>,
  fieldNames: string[],
  role: "character" | "scene",
  semanticType: string,
  entityId: string,
  filename: string,
) {
  const value = fieldNames.map((field) => record[field]).find(hasUsableValue);
  if (!value) return undefined;
  if (typeof value === "object") {
    return normalizeAssetRecord({ ...(value as Record<string, unknown>), semantic_type: semanticType, entity_id: entityId, asset_role: role }, 0);
  }
  const path = stringValue(value);
  if (!path) return undefined;
  return {
    asset_id: `${entityId}-${semanticType}`,
    asset_type: "image",
    asset_role: role,
    filename,
    mime_type: "image/*",
    local_path: path,
    semantic_type: semanticType,
    entity_id: entityId,
  } as UploadedAsset;
}

function entityIdFromRecord(record: Record<string, unknown>, kind: SemanticGalleryKind, index: number) {
  return (
    stringValue(record.id) ||
    stringValue(record.entity_id) ||
    stringValue(record.entityId) ||
    stringValue(record.character_id) ||
    stringValue(record.characterId) ||
    stringValue(record.scene_id) ||
    stringValue(record.sceneId) ||
    `${kind}-${index + 1}`
  );
}

function entityTitleFromRecord(record: Record<string, unknown>, kind: SemanticGalleryKind, index: number) {
  return (
    stringValue(record.name) ||
    stringValue(record.title) ||
    stringValue(record.display_name) ||
    stringValue(record.character_name) ||
    stringValue(record.characterName) ||
    stringValue(record.scene_name) ||
    stringValue(record.sceneName) ||
    galleryFallbackTitle(kind, index)
  );
}

function galleryFallbackTitle(kind: SemanticGalleryKind, index: number) {
  return kind === "character" ? `Character ${index + 1}` : `Scene ${index + 1}`;
}

function hasGalleryAsset(item: SemanticGalleryItem) {
  return Boolean(item.main || item.face || item.threeView || item.multiView);
}

function recordValue(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

function arrayRecords(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object")) : [];
}

function stringValue(value: unknown) {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return "";
}

function normalizeKey(value: unknown) {
  return stringValue(value).toLowerCase();
}

function normalizeNodeKey(value: unknown) {
  return normalizeKey(value).replace(/_/g, "-");
}

function normalizeAssetType(value: unknown, path: string): UploadedAsset["asset_type"] {
  if (value === "image" || value === "video" || value === "audio" || value === "document") return value;
  const lowerPath = path.toLowerCase();
  if (/\.(mp4|mov|webm|mkv|avi)(\?|$)/.test(lowerPath)) return "video";
  if (/\.(mp3|wav|m4a|aac|ogg)(\?|$)/.test(lowerPath)) return "audio";
  if (/\.(md|txt|pdf|doc|docx)(\?|$)/.test(lowerPath)) return "document";
  return "image";
}

function normalizeAssetRole(value: unknown): UploadedAsset["asset_role"] {
  if (value === "product" || value === "character" || value === "scene" || value === "reference" || value === "audio" || value === "document") return value;
  return "reference";
}

function hasUsableValue(value: unknown) {
  if (value === undefined || value === null) return false;
  if (typeof value === "string") return Boolean(value.trim());
  return true;
}
