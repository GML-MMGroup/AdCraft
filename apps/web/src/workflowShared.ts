import type { UploadedAsset, WorkflowEdgeMapping } from "./types";

type EdgeLike = {
  source?: string | null;
  target?: string | null;
  source_node_id?: string | null;
  target_node_id?: string | null;
  source_handle?: string | null;
  target_handle?: string | null;
  sourceHandle?: string | null;
  targetHandle?: string | null;
  label?: unknown;
  mapping?: WorkflowEdgeMapping[];
  data?: { label?: unknown; dataType?: string; mapping?: WorkflowEdgeMapping[] };
};

const TEXT_DATA_TYPES = new Set(["prompt", "text", "json", "data"]);
const URL_IDENTITY_FIELDS = ["public_url", "remote_url", "url"] as const;
const QUALITY_REVIEW_FIELDS = new Set(["quality_status", "quality_score", "quality_issues", "quality_warnings", "reviewer"]);

const SOURCE_CONTEXT_KEYS: Record<string, string> = {
  "requirements-analysis": "requirements",
  "product-design": "product_design",
  "creative-direction": "creative_direction",
  script: "script",
  "character-design": "character_design",
  "scene-design": "scene_design",
  "character-image-generation": "character_images",
  "scene-image-generation": "scene_images",
  storyboard: "storyboard",
  "storyboard-image-generation": "storyboard_images",
  "storyboard-video-generation": "storyboard_video",
  bgm: "bgm",
};

export function workflowEdgeMappingOrDefault(edge: EdgeLike): WorkflowEdgeMapping[] {
  const mapping = Array.isArray(edge.mapping) ? edge.mapping : edge.data?.mapping;
  return hasExecutableMapping(mapping) ? mapping : defaultWorkflowEdgeMapping(edge);
}

export function defaultWorkflowEdgeMapping(edge: EdgeLike): WorkflowEdgeMapping[] {
  const dataType = edgeDataType(edge);
  if (dataType && !TEXT_DATA_TYPES.has(dataType)) {
    return [{ from: "output_assets", to: "input_assets" }];
  }
  return [{ from: "output", to: `input_context.${contextKeyForEdge(edge)}` }];
}

export function dedupeAssets<T extends UploadedAsset>(assets: readonly (T | null | undefined)[]): T[] {
  const result: T[] = [];
  const identityToIndex = new Map<string, number>();

  for (const asset of assets) {
    if (!asset || typeof asset !== "object") continue;
    const keys = assetIdentityKeys(asset);
    const existingIndex = keys.map((key) => identityToIndex.get(key)).find((index): index is number => typeof index === "number");

    if (existingIndex === undefined) {
      const nextIndex = result.length;
      result.push(asset);
      for (const key of keys) identityToIndex.set(key, nextIndex);
      continue;
    }

    const merged = mergeAssetFields(result[existingIndex], asset);
    result[existingIndex] = merged;
    for (const key of [...keys, ...assetIdentityKeys(merged)]) {
      identityToIndex.set(key, existingIndex);
    }
  }

  return result;
}

function hasExecutableMapping(mapping: WorkflowEdgeMapping[] | undefined): mapping is WorkflowEdgeMapping[] {
  return Boolean(
    mapping?.length &&
      mapping.every((item) => {
        if (!item || typeof item.from !== "string" || typeof item.to !== "string") return false;
        if (!item.from.trim() || !item.to.trim()) return false;
        return !item.from.includes(":") && !item.to.includes(":");
      }),
  );
}

function edgeDataType(edge: EdgeLike) {
  return (
    dataTypeFromHandle(edge.source_handle ?? edge.sourceHandle) ??
    dataTypeFromHandle(edge.target_handle ?? edge.targetHandle) ??
    normalizeDataType(edge.data?.dataType) ??
    dataTypeFromLabel(stringValue(edge.label) ?? stringValue(edge.data?.label))
  );
}

function dataTypeFromHandle(handle?: string | null) {
  if (!handle) return undefined;
  const [, rawType] = handle.split(":");
  return normalizeDataType(rawType);
}

function dataTypeFromLabel(label?: string | null) {
  const value = label?.toLowerCase() ?? "";
  if (/image|character references|scene references|shot/.test(value)) return "image";
  if (/video|segment/.test(value)) return "video";
  if (/audio|music|bgm|sound/.test(value)) return "audio";
  return "text";
}

function normalizeDataType(value?: string | null) {
  if (!value) return undefined;
  const normalized = value.toLowerCase();
  if (["prompt", "text", "image", "video", "audio", "json", "resource", "data"].includes(normalized)) {
    return normalized;
  }
  return undefined;
}

function contextKeyForEdge(edge: EdgeLike) {
  const sourceId = edge.source_node_id ?? edge.source;
  if (sourceId && SOURCE_CONTEXT_KEYS[sourceId]) return SOURCE_CONTEXT_KEYS[sourceId];
  const labelKey = snakeCase(stringValue(edge.label) ?? stringValue(edge.data?.label));
  if (labelKey) return labelKey;
  return snakeCase(sourceId) || "input";
}

function assetIdentityKeys(asset: UploadedAsset) {
  const keys = [
    identityKey("asset_id", asset.asset_id),
    identityKey("local_path", asset.local_path),
    ...URL_IDENTITY_FIELDS.map((field) => identityKey("url", asset[field])),
  ].filter((key): key is string => Boolean(key));

  if (keys.length) return keys;

  const filename = normalizedValue(asset.filename);
  return filename ? [`filename:${filename}`] : [];
}

function identityKey(kind: string, value: unknown) {
  const normalized = normalizedValue(value);
  return normalized ? `${kind}:${normalized}` : undefined;
}

function normalizedValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function mergeAssetFields<T extends UploadedAsset>(primary: T, supplement: T): T {
  const merged = { ...primary } as Record<string, unknown>;
  for (const [key, value] of Object.entries(supplement)) {
    if (QUALITY_REVIEW_FIELDS.has(key) && Object.prototype.hasOwnProperty.call(merged, key)) {
      continue;
    }
    if (!hasUsableValue(merged[key]) && hasUsableValue(value)) {
      merged[key] = value;
    }
  }
  return merged as T;
}

function hasUsableValue(value: unknown) {
  if (value === undefined || value === null) return false;
  if (typeof value === "string") return Boolean(value.trim());
  if (Array.isArray(value)) return value.length > 0;
  return true;
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : undefined;
}

function snakeCase(value?: string | null) {
  return (value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}
