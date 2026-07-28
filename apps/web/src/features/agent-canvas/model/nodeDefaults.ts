import type {
  AgentCanvasAssetMediaTypeV2,
  CanvasNodeCreateRequestV2,
  CanvasNodeTypeV2,
  CanvasPositionV2,
} from "../../../types-v2.ts";

export const AGENT_CANVAS_NODE_LABELS: Record<CanvasNodeTypeV2, string> = {
  text: "Text",
  script: "Script",
  image: "Image",
  video: "Video",
  audio: "Audio",
  editing: "Editing",
};

const DEFAULT_SEMANTIC_ROLES: Record<CanvasNodeTypeV2, string> = {
  text: "generic_text",
  script: "advertising_script",
  image: "generic_image",
  video: "generic_video",
  audio: "bgm",
  editing: "final_composition",
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
  nodeType: CanvasNodeTypeV2,
  position: CanvasPositionV2,
): CanvasNodeCreateRequestV2 {
  return {
    node_type: nodeType,
    semantic_role: DEFAULT_SEMANTIC_ROLES[nodeType],
    role_contract_version: "ad-media-role-v1",
    title: AGENT_CANVAS_NODE_LABELS[nodeType],
    summary_prompt: null,
    generation_prompt: ["script", "image", "video", "audio"].includes(nodeType)
      ? ""
      : null,
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
): "generic_image" | "uploaded_video" | "bgm" {
  if (mediaType === "image") return "generic_image";
  return mediaType === "video" ? "uploaded_video" : "bgm";
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
