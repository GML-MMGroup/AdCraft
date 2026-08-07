import {
  Handle,
  Position,
  useUpdateNodeInternals,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { useLayoutEffect, useState, type ReactNode } from "react";

import { PlayIcon } from "../../../icons.tsx";
import type {
  CanvasNodeStatusV2,
  CanvasNodeTypeV2,
  CanvasNodeV2,
  NodeRuntimeV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import { AgentCanvasAudioPlayer } from "./AgentCanvasAudioPlayer.tsx";
import { AgentCanvasNodeContent } from "./AgentCanvasNodeContent.tsx";
import {
  agentCanvasNodeSize,
  validAgentCanvasMediaDimensions,
  type AgentCanvasMediaDimensions,
} from "./nodeGeometry.ts";
import "./AgentCanvasNode.css";

const NODE_TYPE_LABELS: Record<CanvasNodeTypeV2, string> = {
  text: "Text",
  script: "Script",
  image: "Image",
  video: "Video",
  audio: "Audio",
  editing: "Editing",
};

const NODE_STATUS_LABELS: Record<CanvasNodeStatusV2, string> = {
  draft: "Draft",
  working: "Working",
  ready: "Ready",
  failed: "Failed",
};

const IMAGE_ROLE_LABELS: Partial<Record<CanvasNodeV2["creative_role"], string>> = {
  product: "Product",
  prop: "Prop",
  character: "Character",
  scene: "Scene",
  storyboard_sequence: "Storyboard Sequence",
};

export interface AgentCanvasNodeCallbacks {
  onRun?: (nodeId: string) => void;
  onRetry?: (nodeId: string) => void;
  onExport?: (nodeId: string) => void;
  onOpenVideoPreview?: (nodeId: string, asset: ProjectAssetSummaryV2) => void;
  renderWorkbench?: (node: CanvasNodeV2) => ReactNode;
  onOpenConnectedNodeMenu?: (
    nodeId: string,
    direction: "upstream" | "downstream",
    point: { x: number; y: number },
  ) => void;
}

export interface AgentCanvasNodeData extends Record<string, unknown>, AgentCanvasNodeCallbacks {
  node: CanvasNodeV2;
  asset?: ProjectAssetSummaryV2 | null;
  runtime?: NodeRuntimeV2 | null;
  disabled?: boolean;
  showInputHandle?: boolean;
  showOutputHandle?: boolean;
}

export type AgentCanvasFlowNode = Node<AgentCanvasNodeData, "agentCanvas">;

interface AgentCanvasNodeCardProps extends AgentCanvasNodeCallbacks {
  node: CanvasNodeV2;
  asset?: ProjectAssetSummaryV2 | null;
  runtime?: NodeRuntimeV2 | null;
  selected?: boolean;
  disabled?: boolean;
  onMediaDimensionsResolved?: (dimensions: { width: number; height: number }) => void;
}

function semanticNodeLabel(node: CanvasNodeV2): string {
  if (node.node_type === "text" && node.creative_role === "world_setting") return "World Setting";
  if (node.node_type !== "image") return NODE_TYPE_LABELS[node.node_type];
  return IMAGE_ROLE_LABELS[node.creative_role] ?? NODE_TYPE_LABELS.image;
}

function typeIconLabel(node: CanvasNodeV2, label: string): string {
  if (node.creative_role === "world_setting") return label;
  return node.node_type === "image" && IMAGE_ROLE_LABELS[node.creative_role]
    ? `${label} image`
    : node.node_type;
}

/* eslint-disable jsx-a11y/no-noninteractive-element-interactions -- Image load only reports intrinsic media dimensions; the image remains non-interactive. */
function MediaSurface({
  node,
  asset,
  onOpenVideoPreview,
  onMediaDimensionsResolved,
  label,
}: {
  node: CanvasNodeV2;
  asset?: ProjectAssetSummaryV2 | null;
  onOpenVideoPreview?: AgentCanvasNodeCallbacks["onOpenVideoPreview"];
  onMediaDimensionsResolved?: AgentCanvasNodeCardProps["onMediaDimensionsResolved"];
  label: string;
}) {
  const mediaUrl = asset?.media_url ?? asset?.preview_url ?? null;
  const videoUrl = asset?.media_type === "video" ? asset.media_url : null;
  if (node.node_type === "video" && videoUrl && asset) {
    return (
      <div className="agent-canvas-node__video-stage">
        <video
          className="agent-canvas-node__media agent-canvas-node__media--cover"
          src={videoUrl}
          poster={asset.preview_url ?? undefined}
          aria-label={asset.display_name || "Video output"}
          muted
          playsInline
          preload="metadata"
        />
        {onOpenVideoPreview ? (
          <button
            className="agent-canvas-node__video-play nodrag nopan"
            type="button"
            aria-label="Play video output"
            title="Play video"
            onPointerDown={(event) => event.stopPropagation()}
            onDoubleClick={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation();
              onOpenVideoPreview(node.node_id, asset);
            }}
          >
            <PlayIcon />
          </button>
        ) : null}
      </div>
    );
  }

  return mediaUrl ? (
    <img
      className={`agent-canvas-node__media agent-canvas-node__media--${node.node_type === "image" ? "contain" : "cover"}`}
      src={mediaUrl}
      alt={asset?.display_name || `${NODE_TYPE_LABELS[node.node_type]} output`}
      draggable={false}
      loading="lazy"
      decoding="async"
      onLoad={(event) => {
        const { naturalWidth, naturalHeight } = event.currentTarget;
        if (naturalWidth > 0 && naturalHeight > 0) {
          onMediaDimensionsResolved?.({ width: naturalWidth, height: naturalHeight });
        }
      }}
    />
  ) : <AgentCanvasNodeContent node={node} iconLabel={typeIconLabel(node, label)} />;
}
/* eslint-enable jsx-a11y/no-noninteractive-element-interactions */

function NodeSurface({
  node,
  asset,
  status,
  onOpenVideoPreview,
  onMediaDimensionsResolved,
  label,
}: Pick<AgentCanvasNodeCardProps, "node" | "asset" | "onOpenVideoPreview" | "onMediaDimensionsResolved"> & { status: CanvasNodeStatusV2; label: string }) {
  if (node.node_type === "text") {
    return <AgentCanvasNodeContent node={node} iconLabel={typeIconLabel(node, label)} />;
  }
  if (node.node_type === "audio") {
    return <AgentCanvasAudioPlayer node={node} status={status} asset={asset} />;
  }
  return (
    <MediaSurface
      node={node}
      asset={asset}
      label={label}
      onOpenVideoPreview={onOpenVideoPreview}
      onMediaDimensionsResolved={onMediaDimensionsResolved}
    />
  );
}

export function AgentCanvasNodeCard({
  node,
  asset,
  runtime,
  selected = false,
  onOpenVideoPreview,
  onMediaDimensionsResolved,
}: AgentCanvasNodeCardProps) {
  if (node.node_type === "script") return null;

  const status = runtime?.visible_status ?? node.status;
  const label = semanticNodeLabel(node);
  const blockedByUpstream = runtime?.waiting_reason === "blocked_by_upstream"
    || Boolean(runtime?.blocked_by_node_ids.length);
  const usedDeterministicFallback = node.metadata.materialization_mode === "deterministic_fallback"
    && node.metadata.warning_code === "specialist_materialization_fallback";

  return (
    <article
      className={[
        "agent-canvas-node",
        `agent-canvas-node--${node.node_type}`,
        `agent-canvas-node--${status}`,
        selected ? "agent-canvas-node--selected" : "",
      ].filter(Boolean).join(" ")}
      data-testid={`agent-canvas-node-${node.node_id}`}
      data-node-type={node.node_type}
      data-node-status={status}
      aria-label={`${label} node, ${NODE_STATUS_LABELS[status]}`}
    >
      <div className="agent-canvas-node__surface">
        <NodeSurface
          node={node}
          asset={asset}
          status={status}
          label={label}
          onOpenVideoPreview={onOpenVideoPreview}
          onMediaDimensionsResolved={onMediaDimensionsResolved}
        />
        {status === "working" && node.node_type !== "audio" ? (
          <div className="agent-canvas-node__working" aria-label={`${node.node_type} node is working`}>
            <span className="agent-canvas-node__working-orbit" aria-hidden="true" />
            <span className="agent-canvas-node__working-sheen" aria-hidden="true" />
          </div>
        ) : null}
        {status === "failed" ? (
          <div className="agent-canvas-node__error" title={runtime?.error?.message ?? node.error?.message ?? "Generation failed"}>
            <span aria-hidden="true">!</span>
          </div>
        ) : null}
      </div>

      {node.node_type !== "audio" ? (
        <span
          className={`agent-canvas-node__status agent-canvas-node__status--${status}${blockedByUpstream ? " agent-canvas-node__status--blocked" : ""}`}
          title={blockedByUpstream ? "Waiting for required upstream nodes." : undefined}
        >
          <i aria-hidden="true" />
          {blockedByUpstream ? "Waiting for upstream" : NODE_STATUS_LABELS[status]}
        </span>
      ) : null}

      {usedDeterministicFallback ? (
        <span className="agent-canvas-node__fallback-warning" role="status">
          Created with a simplified fallback
        </span>
      ) : null}

    </article>
  );
}

export function AgentCanvasNodeRenderer({
  id,
  data,
  selected,
  isConnectable,
}: NodeProps<AgentCanvasFlowNode>) {
  const updateNodeInternals = useUpdateNodeInternals();
  const [intrinsicDimensions, setIntrinsicDimensions] = useState<(
    AgentCanvasMediaDimensions & { assetId: string | null }
  ) | null>(null);
  const label = semanticNodeLabel(data.node);
  const visible = data.node.node_type !== "script";
  const workbench = visible ? data.renderWorkbench?.(data.node) : null;
  const assetDimensions = validAgentCanvasMediaDimensions(data.asset)
    ? { width: data.asset.width, height: data.asset.height }
    : intrinsicDimensions?.assetId === (data.asset?.asset_id ?? null)
      ? intrinsicDimensions
      : null;
  const nodeSize = agentCanvasNodeSize(data.node.node_type, assetDimensions);

  useLayoutEffect(() => {
    if (visible) updateNodeInternals(id);
  }, [id, nodeSize.height, nodeSize.width, updateNodeInternals, visible]);

  if (!visible) return null;

  return (
    <div
      className="agent-canvas-node-shell"
      style={{ width: nodeSize.width, height: nodeSize.height }}
    >
      {data.showInputHandle !== false ? (
        <Handle
          id="input"
          className="agent-canvas-node__handle agent-canvas-node__handle--input nodrag"
          type="target"
          position={Position.Left}
          isConnectable={isConnectable}
          aria-label={`${label} node input`}
        />
      ) : null}
      <AgentCanvasNodeCard
        node={data.node}
        asset={data.asset}
        runtime={data.runtime}
        selected={selected}
        onOpenVideoPreview={data.onOpenVideoPreview}
        onMediaDimensionsResolved={validAgentCanvasMediaDimensions(data.asset)
          ? undefined
          : ({ width, height }) => setIntrinsicDimensions({
              assetId: data.asset?.asset_id ?? null,
              width,
              height,
            })}
      />
      {workbench ? (
        // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- The embedded form remains keyboard-accessible; this boundary only prevents node-level double-click focus.
        <div
          className="agent-canvas-node-workbench-anchor nodrag nopan nowheel"
          onDoubleClick={(event) => event.stopPropagation()}
        >
          {workbench}
        </div>
      ) : null}
      {data.showOutputHandle !== false ? (
        <Handle
          id="output"
          className="agent-canvas-node__handle agent-canvas-node__handle--output nodrag"
          type="source"
          position={Position.Right}
          isConnectable={isConnectable}
          aria-label={`${label} node output`}
        />
      ) : null}
    </div>
  );
}
