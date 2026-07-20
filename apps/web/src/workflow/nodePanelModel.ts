import type { UploadedAsset, WorkflowNode } from "../types";

export type NodePanelKind = "requirements" | "media" | "text" | "preview" | "utility";

export interface RequirementField {
  key: string;
  label: string;
  value: string;
}

export interface NodePanelModel {
  kind: NodePanelKind;
  requirementFields: RequirementField[];
  sections: {
    requirements: boolean;
    prompt: boolean;
    config: boolean;
    inputAssets: boolean;
    resolvedInputs: boolean;
    outputPreview: boolean;
    debug: boolean;
  };
}

const REQUIREMENT_FIELDS: Array<{ key: string; label: string; aliases?: string[]; format?: (value: unknown) => string }> = [
  { key: "product", label: "Product", aliases: ["product_name"] },
  { key: "core_selling_point", label: "Core selling point", aliases: ["product_description"] },
  { key: "target_audience", label: "Target audience" },
  { key: "campaign_goal", label: "Campaign goal" },
  { key: "desired_emotion", label: "Desired emotion" },
  { key: "duration_seconds", label: "Duration", format: formatDuration },
  { key: "visual_style", label: "Visual style" },
  { key: "references", label: "References", format: formatListValue },
  { key: "selected_assets", label: "Selected assets", format: formatListValue },
];

export function nodePanelModel(node: WorkflowNode, options: { output?: Record<string, unknown> | null } = {}): NodePanelModel {
  const kind = classifyNodePanelKind(node);
  const isRequirements = kind === "requirements";
  return {
    kind,
    requirementFields: isRequirements ? requirementFieldsForNode(node, options.output) : [],
    sections: {
      requirements: isRequirements,
      prompt: true,
      config: false,
      inputAssets: true,
      resolvedInputs: false,
      outputPreview: false,
      debug: true,
    },
  };
}

function classifyNodePanelKind(node: WorkflowNode): NodePanelKind {
  const nodeType = normalizedNodeType(node);
  const category = String(node.category ?? "").toLowerCase();
  if (nodeType === "requirements-analysis" || node.id === "requirements-analysis") return "requirements";
  if (["character-generation", "scene-generation", "storyboard", "storyboard-video-generation", "bgm"].includes(nodeType)) return "media";
  if (nodeType === "final-composition") return "preview";
  if (category.includes("image") || category.includes("video") || category.includes("audio")) return "media";
  if (["image", "video", "audio"].some((token) => nodeType.includes(token))) return "media";
  if (category.includes("preview") || category.includes("composition")) return "preview";
  if (nodeType.includes("preview") || nodeType.includes("composition") || nodeType.includes("final")) return "preview";
  if (category.includes("text") || category.includes("agent")) return "text";
  if (["product", "creative", "script", "character", "scene", "storyboard", "text", "prompt", "design"].some((token) => nodeType.includes(token))) return "text";
  return "utility";
}

function requirementFieldsForNode(node: WorkflowNode, output?: Record<string, unknown> | null): RequirementField[] {
  const source = requirementSourceForNode(node, output);
  return REQUIREMENT_FIELDS.flatMap((field) => {
    const value = valueByAliases(source, field.key, field.aliases);
    const formatted = field.format ? field.format(value) : formatScalarValue(value);
    return formatted ? [{ key: field.key, label: field.label, value: formatted }] : [];
  });
}

function requirementSourceForNode(node: WorkflowNode, output?: Record<string, unknown> | null): Record<string, unknown> {
  const candidates = [
    recordValue(output),
    node.output,
    node.content,
    recordValue(node.input_context?.requirements),
    recordValue(node.input_context?.ad_request),
    recordValue(node.metadata?.ad_request),
  ];
  return candidates.find((candidate) => candidate && Object.keys(candidate).length > 0) ?? {};
}

function valueByAliases(source: Record<string, unknown>, key: string, aliases: string[] = []) {
  for (const name of [key, ...aliases]) {
    const value = source[name];
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return undefined;
}

function formatScalarValue(value: unknown) {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function formatDuration(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return `${value}s`;
  const text = formatScalarValue(value);
  return text ? `${text.replace(/s$/i, "")}s` : "";
}

function formatListValue(value: unknown) {
  if (!Array.isArray(value)) return formatScalarValue(value);
  return value.map(formatListItem).filter(Boolean).join(", ");
}

function formatListItem(value: unknown) {
  if (typeof value === "string") return value.trim();
  if (!value || typeof value !== "object") return "";
  const asset = value as Partial<UploadedAsset> & Record<string, unknown>;
  return formatScalarValue(asset.filename) || formatScalarValue(asset.asset_id) || formatScalarValue(asset.url) || formatScalarValue(asset.local_path);
}

function normalizedNodeType(node: WorkflowNode) {
  return String(node.node_type ?? node.type ?? node.id).toLowerCase();
}

function recordValue(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}
