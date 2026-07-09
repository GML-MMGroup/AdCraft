import type { WorkflowEdgeMapping } from "../types";

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
