import type { CanvasNodeTypeV2 } from "../../../types-v2.ts";

export interface AgentCanvasNodeSize {
  width: number;
  height: number;
}

export interface AgentCanvasMediaDimensions {
  width: number | null | undefined;
  height: number | null | undefined;
}

export const DEFAULT_AGENT_CANVAS_NODE_SIZE: AgentCanvasNodeSize = {
  width: 272,
  height: 184,
};

export const UNKNOWN_IMAGE_NODE_SIZE: AgentCanvasNodeSize = {
  width: 360,
  height: 360,
};

export const AGENT_CANVAS_NODE_HORIZONTAL_GAP = 68;
export const AGENT_CANVAS_NODE_VERTICAL_GAP = 68;

const IMAGE_NODE_TARGET_AREA = 96_000;
const IMAGE_NODE_MAX_WIDTH = 360;
const IMAGE_NODE_MAX_HEIGHT = 360;
const IMAGE_NODE_MIN_EDGE = 128;
const FOCUSED_NODE_MAX_WIDTH = 1040;
const FOCUSED_NODE_MAX_HEIGHT = 680;

export function validAgentCanvasMediaDimensions(
  dimensions?: AgentCanvasMediaDimensions | null,
): dimensions is { width: number; height: number } {
  return Boolean(
    dimensions
    && typeof dimensions.width === "number"
    && Number.isFinite(dimensions.width)
    && dimensions.width > 0
    && typeof dimensions.height === "number"
    && Number.isFinite(dimensions.height)
    && dimensions.height > 0,
  );
}

export function agentCanvasNodeSize(
  nodeType: CanvasNodeTypeV2,
  dimensions?: AgentCanvasMediaDimensions | null,
): AgentCanvasNodeSize {
  if (nodeType !== "image" || !validAgentCanvasMediaDimensions(dimensions)) {
    return DEFAULT_AGENT_CANVAS_NODE_SIZE;
  }

  const ratio = dimensions.width / dimensions.height;
  const areaWidth = Math.sqrt(IMAGE_NODE_TARGET_AREA * ratio);
  const areaHeight = Math.sqrt(IMAGE_NODE_TARGET_AREA / ratio);
  const scale = Math.min(
    1,
    IMAGE_NODE_MAX_WIDTH / areaWidth,
    IMAGE_NODE_MAX_HEIGHT / areaHeight,
  );

  return {
    width: Math.max(IMAGE_NODE_MIN_EDGE, Math.round(areaWidth * scale)),
    height: Math.max(IMAGE_NODE_MIN_EDGE, Math.round(areaHeight * scale)),
  };
}

export function agentCanvasNodePlacementSize(
  nodeType: CanvasNodeTypeV2,
  dimensions?: AgentCanvasMediaDimensions | null,
): AgentCanvasNodeSize {
  if (nodeType === "image" && !validAgentCanvasMediaDimensions(dimensions)) {
    return UNKNOWN_IMAGE_NODE_SIZE;
  }
  return agentCanvasNodeSize(nodeType, dimensions);
}

export function agentCanvasFocusedNodeSize(
  nodeType: CanvasNodeTypeV2,
  dimensions?: AgentCanvasMediaDimensions | null,
): AgentCanvasNodeSize {
  if (
    !["image", "video", "editing"].includes(nodeType)
    || !validAgentCanvasMediaDimensions(dimensions)
  ) {
    return { width: FOCUSED_NODE_MAX_WIDTH, height: FOCUSED_NODE_MAX_HEIGHT };
  }

  const ratio = dimensions.width / dimensions.height;
  if (ratio >= FOCUSED_NODE_MAX_WIDTH / FOCUSED_NODE_MAX_HEIGHT) {
    return {
      width: FOCUSED_NODE_MAX_WIDTH,
      height: Math.round(FOCUSED_NODE_MAX_WIDTH / ratio),
    };
  }
  return {
    width: Math.round(FOCUSED_NODE_MAX_HEIGHT * ratio),
    height: FOCUSED_NODE_MAX_HEIGHT,
  };
}
