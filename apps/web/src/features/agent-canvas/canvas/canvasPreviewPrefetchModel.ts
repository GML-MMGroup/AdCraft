import type { Viewport } from "@xyflow/react";

import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import {
  mediaAssetCanvasPosterRenditionPath,
  mediaAssetCanvasPreviewRenditionPath,
  mediaAssetCanvasPreviewSrcSet,
} from "../../../workflow/mediaPreview.ts";
import type { AgentCanvasFlowNode } from "./AgentCanvasNode.tsx";
import type { CanvasPreviewCandidate } from "./canvasPreviewPrefetch.ts";

const WARM_MARGIN_PX = 640;
const IDLE_MARGIN_PX = 1_120;
const DEFAULT_NODE_WIDTH = 272;
const DEFAULT_NODE_HEIGHT = 184;

function nodeSize(node: AgentCanvasFlowNode) {
  const width = node.measured?.width ?? node.width ?? numericStyle(node.style?.width) ?? DEFAULT_NODE_WIDTH;
  const height = node.measured?.height ?? node.height ?? numericStyle(node.style?.height) ?? DEFAULT_NODE_HEIGHT;
  return { width, height };
}

function numericStyle(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && Number.isFinite(Number.parseFloat(value))) return Number.parseFloat(value);
  return undefined;
}

function previewUrl(node: AgentCanvasFlowNode): string {
  const asset = node.data.asset as ProjectAssetSummaryV2 | null | undefined;
  if (!asset) return "";
  if (node.data.node.node_type === "image") {
    return preferredSrcSetCandidate(asset, mediaAssetCanvasPreviewRenditionPath(asset));
  }
  if (node.data.node.node_type === "video") {
    const poster = mediaAssetCanvasPosterRenditionPath(asset);
    return preferredSrcSetCandidate(asset, poster);
  }
  return "";
}

function preferredSrcSetCandidate(asset: ProjectAssetSummaryV2, fallback: string): string {
  const srcSet = mediaAssetCanvasPreviewSrcSet(asset);
  return srcSet.match(/^(?:\S+) 320w,\s*(\S+) 640w$/)?.[1] ?? fallback;
}

export function canvasPreviewCandidates(
  nodes: readonly AgentCanvasFlowNode[],
  viewport: Viewport,
  boardWidth: number,
  boardHeight: number,
): CanvasPreviewCandidate[] {
  if (!Number.isFinite(viewport.zoom) || viewport.zoom <= 0 || boardWidth <= 0 || boardHeight <= 0) return [];
  const zoom = viewport.zoom;
  const flowLeft = -viewport.x / zoom;
  const flowTop = -viewport.y / zoom;
  const flowRight = (boardWidth - viewport.x) / zoom;
  const flowBottom = (boardHeight - viewport.y) / zoom;
  const warmMargin = WARM_MARGIN_PX / zoom;
  const idleMargin = IDLE_MARGIN_PX / zoom;
  const warmBounds = {
    left: flowLeft - warmMargin,
    top: flowTop - warmMargin,
    right: flowRight + warmMargin,
    bottom: flowBottom + warmMargin,
  };
  const viewportBounds = {
    left: flowLeft,
    top: flowTop,
    right: flowRight,
    bottom: flowBottom,
  };
  const idleBounds = {
    left: flowLeft - idleMargin,
    top: flowTop - idleMargin,
    right: flowRight + idleMargin,
    bottom: flowBottom + idleMargin,
  };
  const intersects = (bounds: typeof warmBounds, x: number, y: number, width: number, height: number) => (
    x <= bounds.right && x + width >= bounds.left && y <= bounds.bottom && y + height >= bounds.top
  );
  const candidates: CanvasPreviewCandidate[] = [];
  const viewportCenter = {
    x: (flowLeft + flowRight) / 2,
    y: (flowTop + flowBottom) / 2,
  };
  for (const node of nodes) {
    const url = previewUrl(node);
    if (!url) continue;
    const { width, height } = nodeSize(node);
    const x = node.position.x;
    const y = node.position.y;
    // Mounted nodes use eager loading. The queue is reserved for nodes just
    // outside the viewport so they are warm before React Flow mounts them.
    if (intersects(viewportBounds, x, y, width, height)) continue;
    const priority = intersects(warmBounds, x, y, width, height)
      ? "warm"
      : intersects(idleBounds, x, y, width, height) ? "idle" : null;
    if (!priority) continue;
    const asset = node.data.asset as ProjectAssetSummaryV2 | null | undefined;
    const identity = asset?.asset_id ?? node.id;
    const version = asset?.version_id ?? "unversioned";
    const centerX = x + width / 2;
    const centerY = y + height / 2;
    const distance = Math.hypot(centerX - viewportCenter.x, centerY - viewportCenter.y) * zoom;
    candidates.push({ key: `${identity}:${version}:${url}`, url, priority, distance });
  }
  return candidates;
}
