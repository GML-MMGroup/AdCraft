import type {
  AgentCanvasAssetMediaTypeV2,
  CanvasCreativeRoleV2,
  CanvasNodeCreateRequestV2,
  CanvasNodeTypeV2,
  CanvasPositionV2,
  CanvasRoleContractVersionV2,
} from "../../../types-v2.ts";

export const AGENT_CANVAS_ROLE_CONTRACT_VERSION: CanvasRoleContractVersionV2 = "ad-media-role-v2";

export type AgentCanvasVisibleNodeTypeV2 = Exclude<CanvasNodeTypeV2, "script">;

export const AGENT_CANVAS_VISIBLE_NODE_TYPES: readonly AgentCanvasVisibleNodeTypeV2[] = [
  "text",
  "image",
  "video",
  "audio",
  "editing",
];

export function isAgentCanvasVisibleNodeType(
  nodeType: CanvasNodeTypeV2,
): nodeType is AgentCanvasVisibleNodeTypeV2 {
  return nodeType !== "script";
}

export const AGENT_CANVAS_NODE_LABELS: Record<CanvasNodeTypeV2, string> = {
  text: "Text",
  script: "Script",
  image: "Image",
  video: "Video",
  audio: "Audio",
  editing: "Editing",
};

const DEFAULT_CREATIVE_ROLES: Record<CanvasNodeTypeV2, CanvasCreativeRoleV2> = {
  text: "general_text",
  script: "script",
  image: "general_image",
  video: "general_video",
  audio: "bgm",
  editing: "editing",
};

function bgmContent(summary: string, durationSeconds = 30): Record<string, unknown> {
  return {
    music_summary: summary,
    duration_seconds: Math.max(0.1, durationSeconds),
    pace: "Moderate",
    energy_curve: "Balanced progression supporting the advertisement",
    instrumentation: "Contemporary instrumental arrangement",
    mood: "Cinematic and brand appropriate",
    instrumental_only: true,
    no_vocals: true,
  };
}

export function createDefaultCanvasNodeRequest(
  nodeType: AgentCanvasVisibleNodeTypeV2,
  position: CanvasPositionV2,
): CanvasNodeCreateRequestV2 {
  return {
    node_type: nodeType,
    creative_role: DEFAULT_CREATIVE_ROLES[nodeType],
    role_contract_version: AGENT_CANVAS_ROLE_CONTRACT_VERSION,
    title: AGENT_CANVAS_NODE_LABELS[nodeType],
    summary_prompt: null,
    generation_prompt: ["script", "image", "video", "audio"].includes(nodeType)
      ? ""
      : null,
    model_selection_mode: "default",
    model_ref: null,
    ...(nodeType === "text"
      ? { structured_content: { content: "" } }
      : nodeType === "audio"
        ? { structured_content: bgmContent("Original background music for the advertisement") }
      : {}),
    position,
  };
}

export function sourceAssetSemanticRole(
  mediaType: AgentCanvasAssetMediaTypeV2,
): CanvasCreativeRoleV2 {
  if (mediaType === "image") return "general_image";
  return mediaType === "video" ? "general_video" : "general_audio";
}

export function sourceAssetStructuredContent(
  mediaType: AgentCanvasAssetMediaTypeV2,
  displayName: string,
  durationSeconds: number | null,
): Record<string, unknown> {
  return mediaType === "audio"
    ? bgmContent(displayName, durationSeconds ?? 30)
    : {};
}
