import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import type { ReactNode } from "react";

import {
  DocumentIcon,
  EditIcon,
  ImageIcon,
  PlusIcon,
  UnmuteIcon,
  VideoIcon,
} from "../../../icons.tsx";
import type {
  CanvasNodeStatusV2,
  CanvasNodeTypeV2,
  CanvasNodeV2,
  NodeRuntimeV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
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
}

function firstString(record: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function nodeCopy(node: CanvasNodeV2) {
  const structured = node.structured_content;
  if (node.node_type === "script") {
    return firstString(structured, ["script_text", "content", "text", "body"])
      ?? node.generation_prompt
      ?? node.summary_prompt
      ?? "Script draft";
  }
  return firstString(structured, ["text", "content", "body", "brief"])
    ?? node.summary_prompt
    ?? node.generation_prompt
    ?? "Text draft";
}

function semanticNodeLabel(node: CanvasNodeV2): string {
  if (node.node_type !== "image") return NODE_TYPE_LABELS[node.node_type];
  return IMAGE_ROLE_LABELS[node.creative_role] ?? NODE_TYPE_LABELS.image;
}

function typeMarkerLabel(node: CanvasNodeV2, label: string): string {
  return node.node_type === "image" && IMAGE_ROLE_LABELS[node.creative_role]
    ? `${label} image node`
    : `${node.node_type} node`;
}

function typeIcon(nodeType: CanvasNodeTypeV2): ReactNode {
  if (nodeType === "text") return <EditIcon />;
  if (nodeType === "script") return <DocumentIcon />;
  if (nodeType === "image") return <ImageIcon />;
  if (nodeType === "video") return <VideoIcon />;
  if (nodeType === "audio") return <UnmuteIcon />;
  return <EditIcon />;
}

function typeMarkerImage(nodeType: CanvasNodeTypeV2): string {
  if (nodeType === "image") return "/imgs/image.webp";
  if (nodeType === "video" || nodeType === "editing") return "/imgs/video.webp";
  if (nodeType === "audio") return "/imgs/audio.webp";
  return "/imgs/text.webp";
}

function MediaSurface({
  node,
  asset,
}: {
  node: CanvasNodeV2;
  asset?: ProjectAssetSummaryV2 | null;
}) {
  const mediaUrl = asset?.media_url ?? asset?.preview_url ?? null;
  if (node.node_type === "video" && mediaUrl) {
    return (
      <video
        className="agent-canvas-node__media agent-canvas-node__media--cover"
        src={mediaUrl}
        poster={asset?.preview_url ?? undefined}
        aria-label={asset?.display_name || "Video output"}
        muted
        loop
        playsInline
        preload="metadata"
      />
    );
  }

  return mediaUrl ? (
    <img
      className="agent-canvas-node__media agent-canvas-node__media--cover"
      src={mediaUrl}
      alt={asset?.display_name || `${NODE_TYPE_LABELS[node.node_type]} output`}
      draggable={false}
      loading="lazy"
      decoding="async"
    />
  ) : (
    <div className="agent-canvas-node__media-placeholder" aria-label={`${NODE_TYPE_LABELS[node.node_type]} preview unavailable`}>
      {typeIcon(node.node_type)}
    </div>
  );
}

function AudioSurface({ asset }: { asset?: ProjectAssetSummaryV2 | null }) {
  return (
    <div className="agent-canvas-node__audio" role="img" aria-label={asset?.display_name || "Audio output"}>
      <span className="agent-canvas-node__audio-disc" aria-hidden="true">
        <span />
      </span>
      <span className="agent-canvas-node__waveform" aria-hidden="true">
        {Array.from({ length: 23 }, (_, index) => <i key={index} />)}
      </span>
      {asset?.duration_seconds != null ? (
        <span className="agent-canvas-node__duration">{Math.round(asset.duration_seconds)}s</span>
      ) : null}
    </div>
  );
}

function NodeSurface({
  node,
  asset,
}: Pick<AgentCanvasNodeCardProps, "node" | "asset">) {
  if (node.node_type === "text" || node.node_type === "script") {
    return (
      <div className={`agent-canvas-node__copy agent-canvas-node__copy--${node.node_type}`}>
        {node.node_type === "script" ? <span className="agent-canvas-node__script-rule" aria-hidden="true" /> : null}
        <p>{nodeCopy(node)}</p>
      </div>
    );
  }
  if (node.node_type === "audio") return <AudioSurface asset={asset} />;
  return <MediaSurface node={node} asset={asset} />;
}

export function AgentCanvasNodeCard({
  node,
  asset,
  runtime,
  selected = false,
}: AgentCanvasNodeCardProps) {
  const status = runtime?.visible_status ?? node.status;
  const label = semanticNodeLabel(node);
  const blockedByUpstream = runtime?.waiting_reason === "blocked_by_upstream"
    || Boolean(runtime?.blocked_by_node_ids.length);

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
      <span
        className="agent-canvas-node__type-marker"
        role="img"
        aria-label={typeMarkerLabel(node, label)}
        title={`${label} node`}
      >
        <img src={typeMarkerImage(node.node_type)} alt="" draggable={false} />
      </span>

      <div className="agent-canvas-node__surface">
        <NodeSurface node={node} asset={asset} />
        {status === "working" ? (
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

      <span
        className={`agent-canvas-node__status agent-canvas-node__status--${status}${blockedByUpstream ? " agent-canvas-node__status--blocked" : ""}`}
        title={blockedByUpstream ? "Waiting for required upstream nodes." : undefined}
      >
        <i aria-hidden="true" />
        {blockedByUpstream ? "Waiting for upstream" : NODE_STATUS_LABELS[status]}
      </span>

    </article>
  );
}

export function AgentCanvasNodeRenderer({
  data,
  selected,
  isConnectable,
}: NodeProps<AgentCanvasFlowNode>) {
  const label = semanticNodeLabel(data.node);
  const workbench = data.renderWorkbench?.(data.node);
  return (
    <div className="agent-canvas-node-shell">
      {data.showInputHandle !== false ? (
        <Handle
          id="input"
          className="agent-canvas-node__handle agent-canvas-node__handle--input nodrag"
          type="target"
          position={Position.Left}
          isConnectable={isConnectable}
          aria-label={`${label} node input`}
        >
          <span
            className="agent-canvas-node__handle-plus"
            role="button"
            tabIndex={0}
            aria-label={`Add an upstream node to ${label}`}
            onClick={(event) => {
              event.stopPropagation();
              data.onOpenConnectedNodeMenu?.(
                data.node.node_id,
                "upstream",
                { x: event.clientX, y: event.clientY },
              );
            }}
            onKeyDown={(event) => {
              if (event.key !== "Enter" && event.key !== " ") return;
              event.preventDefault();
              event.stopPropagation();
              const bounds = event.currentTarget.getBoundingClientRect();
              data.onOpenConnectedNodeMenu?.(
                data.node.node_id,
                "upstream",
                { x: bounds.left, y: bounds.top },
              );
            }}
          >
            <PlusIcon />
          </span>
        </Handle>
      ) : null}
      <AgentCanvasNodeCard
        node={data.node}
        asset={data.asset}
        runtime={data.runtime}
        selected={selected}
      />
      {workbench ? <div className="agent-canvas-node-workbench-anchor nodrag nopan nowheel">{workbench}</div> : null}
      {data.showOutputHandle !== false ? (
        <Handle
          id="output"
          className="agent-canvas-node__handle agent-canvas-node__handle--output nodrag"
          type="source"
          position={Position.Right}
          isConnectable={isConnectable}
          aria-label={`${label} node output`}
        >
          <span
            className="agent-canvas-node__handle-plus"
            role="button"
            tabIndex={0}
            aria-label={`Add a downstream node to ${label}`}
            onClick={(event) => {
              event.stopPropagation();
              data.onOpenConnectedNodeMenu?.(
                data.node.node_id,
                "downstream",
                { x: event.clientX, y: event.clientY },
              );
            }}
            onKeyDown={(event) => {
              if (event.key !== "Enter" && event.key !== " ") return;
              event.preventDefault();
              event.stopPropagation();
              const bounds = event.currentTarget.getBoundingClientRect();
              data.onOpenConnectedNodeMenu?.(
                data.node.node_id,
                "downstream",
                { x: bounds.right, y: bounds.top },
              );
            }}
          >
            <PlusIcon />
          </span>
        </Handle>
      ) : null}
    </div>
  );
}
