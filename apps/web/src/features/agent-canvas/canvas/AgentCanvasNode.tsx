import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import type { PointerEvent as ReactPointerEvent, MouseEvent as ReactMouseEvent, ReactNode } from "react";

import {
  DocumentIcon,
  EditIcon,
  ImageIcon,
  PlayIcon,
  PlusIcon,
  RunCurrentIcon,
  UnmuteIcon,
  UploadIcon,
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

const RUNNABLE_NODE_TYPES = new Set<CanvasNodeTypeV2>(["script", "image", "video", "audio"]);

export interface AgentCanvasNodeCallbacks {
  onRun?: (nodeId: string) => void;
  onRetry?: (nodeId: string) => void;
  onExport?: (nodeId: string) => void;
  onOpenMedia?: (nodeId: string, assetId: string) => void;
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

function typeIcon(nodeType: CanvasNodeTypeV2): ReactNode {
  if (nodeType === "text") return <EditIcon />;
  if (nodeType === "script") return <DocumentIcon />;
  if (nodeType === "image") return <ImageIcon />;
  if (nodeType === "video") return <VideoIcon />;
  if (nodeType === "audio") return <UnmuteIcon />;
  return <EditIcon />;
}

function actionIcon(action: "run" | "retry" | "export") {
  if (action === "retry") return <RunCurrentIcon />;
  if (action === "export") return <UploadIcon />;
  return <PlayIcon />;
}

function stopPointer(event: ReactPointerEvent<HTMLButtonElement>) {
  event.stopPropagation();
}

function stopMouse(event: ReactMouseEvent<HTMLButtonElement>) {
  event.stopPropagation();
}

function MediaSurface({
  node,
  asset,
  onOpenMedia,
}: {
  node: CanvasNodeV2;
  asset?: ProjectAssetSummaryV2 | null;
  onOpenMedia?: (nodeId: string, assetId: string) => void;
}) {
  const src = asset?.preview_url ?? (node.node_type === "image" ? asset?.media_url : null);
  const canOpen = Boolean(asset?.asset_id && onOpenMedia);
  const content = src ? (
    <img
      className="agent-canvas-node__media agent-canvas-node__media--cover"
      src={src}
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

  if (!canOpen) return content;
  return (
    <button
      type="button"
      className="agent-canvas-node__media-button nodrag nopan"
      aria-label={`Open ${asset?.display_name || NODE_TYPE_LABELS[node.node_type]} preview`}
      onPointerDown={stopPointer}
      onMouseDown={stopMouse}
      onClick={(event) => {
        event.stopPropagation();
        onOpenMedia?.(node.node_id, asset!.asset_id);
      }}
    >
      {content}
    </button>
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
  onOpenMedia,
}: Pick<AgentCanvasNodeCardProps, "node" | "asset" | "onOpenMedia">) {
  if (node.node_type === "text" || node.node_type === "script") {
    return (
      <div className={`agent-canvas-node__copy agent-canvas-node__copy--${node.node_type}`}>
        {node.node_type === "script" ? <span className="agent-canvas-node__script-rule" aria-hidden="true" /> : null}
        <p>{nodeCopy(node)}</p>
      </div>
    );
  }
  if (node.node_type === "audio") return <AudioSurface asset={asset} />;
  return <MediaSurface node={node} asset={asset} onOpenMedia={onOpenMedia} />;
}

function nodeAction(nodeType: CanvasNodeTypeV2, status: CanvasNodeStatusV2) {
  if (nodeType === "text") return null;
  if (nodeType === "editing") return "export" as const;
  if (status === "failed") return "retry" as const;
  if (status === "draft" && RUNNABLE_NODE_TYPES.has(nodeType)) return "run" as const;
  return null;
}

export function AgentCanvasNodeCard({
  node,
  asset,
  runtime,
  selected = false,
  disabled = false,
  onRun,
  onRetry,
  onExport,
  onOpenMedia,
}: AgentCanvasNodeCardProps) {
  const status = runtime?.visible_status ?? node.status;
  const action = nodeAction(node.node_type, status);
  const label = NODE_TYPE_LABELS[node.node_type];
  const actionCallback = action === "run" ? onRun : action === "retry" ? onRetry : onExport;
  const actionDisabled = disabled || status === "working" || !actionCallback;

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
        aria-label={`${node.node_type} node`}
        title={`${label} node`}
      >
        {typeIcon(node.node_type)}
      </span>

      <div className="agent-canvas-node__surface">
        <NodeSurface node={node} asset={asset} onOpenMedia={onOpenMedia} />
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

      <span className={`agent-canvas-node__status agent-canvas-node__status--${status}`}>
        <i aria-hidden="true" />
        {NODE_STATUS_LABELS[status]}
      </span>

      {action ? (
        <button
          type="button"
          className={`agent-canvas-node__action agent-canvas-node__action--${action} nodrag nopan nowheel`}
          aria-label={`${action === "run" ? "Run" : action === "retry" ? "Retry" : "Export"} ${node.node_type} node`}
          title={action === "run" ? "Run node" : action === "retry" ? "Retry node" : "Export"}
          disabled={actionDisabled}
          onPointerDown={stopPointer}
          onMouseDown={stopMouse}
          onClick={(event) => {
            event.stopPropagation();
            actionCallback?.(node.node_id);
          }}
        >
          {actionIcon(action)}
        </button>
      ) : null}
    </article>
  );
}

export function AgentCanvasNodeRenderer({
  data,
  selected,
  isConnectable,
}: NodeProps<AgentCanvasFlowNode>) {
  const label = NODE_TYPE_LABELS[data.node.node_type];
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
        disabled={data.disabled}
        onRun={data.onRun}
        onRetry={data.onRetry}
        onExport={data.onExport}
        onOpenMedia={data.onOpenMedia}
      />
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
