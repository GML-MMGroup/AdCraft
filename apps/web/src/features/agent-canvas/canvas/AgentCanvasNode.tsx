import {
  Handle,
  NodeToolbar,
  Position,
  useUpdateNodeInternals,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { memo, useCallback, useLayoutEffect, useState, type ReactNode } from "react";

import { PlayIcon } from "../../../icons.tsx";
import type {
  CanvasNodeStatusV2,
  CanvasNodeTypeV2,
  CanvasNodeV2,
  NodeRuntimeV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import { AgentCanvasAudioPlayer } from "./AgentCanvasAudioPlayer.tsx";
import { AgentCanvasMediaGenerationLoader } from "./AgentCanvasMediaGenerationLoader.tsx";
import { AgentCanvasNodeContent } from "./AgentCanvasNodeContent.tsx";
import { AgentCanvasNodeHeader } from "./AgentCanvasNodeHeader.tsx";
import { EditingNodeSurface } from "./EditingNodeSurface.tsx";
import { creativeRoleDisplayName } from "./creativeRoleDisplayName.ts";
import { areAgentCanvasNodePropsEqual } from "./agentCanvasNodeRenderModel.ts";
import {
  mediaAssetPosterRenditionPath,
  mediaAssetPreviewRenditionPath,
} from "../../../workflow/mediaPreview.ts";
import { StableMediaPreview } from "../../../workflow/StableMediaPreview.tsx";
import {
  agentCanvasNodeSize,
  scriptNodeHeightForContent,
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

export interface AgentCanvasNodeCallbacks {
  onRun?: (nodeId: string) => void;
  onRetry?: (nodeId: string) => void;
  onExport?: (nodeId: string) => void;
  onOpenEditing?: (nodeId: string) => void;
  onOpenVideoPreview?: (nodeId: string, asset: ProjectAssetSummaryV2) => void;
  renderWorkbench?: (node: CanvasNodeV2, runtime: NodeRuntimeV2 | null) => ReactNode;
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
  workbenchActive?: boolean;
  disabled?: boolean;
  showInputHandle?: boolean;
  showOutputHandle?: boolean;
}

export type AgentCanvasFlowNode = Node<AgentCanvasNodeData, "agentCanvas">;

type AgentCanvasNodeRendererProps = NodeProps<AgentCanvasFlowNode>;

interface AgentCanvasNodeCardProps extends AgentCanvasNodeCallbacks {
  node: CanvasNodeV2;
  asset?: ProjectAssetSummaryV2 | null;
  runtime?: NodeRuntimeV2 | null;
  selected?: boolean;
  disabled?: boolean;
  onMediaDimensionsResolved?: (dimensions: { width: number; height: number }) => void;
  onScriptContentHeightResolved?: (height: number) => void;
  mediaDimensions?: { width: number; height: number } | null;
}

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
  const mediaUrl = asset
    ? node.node_type === "image"
      ? mediaAssetPreviewRenditionPath(asset)
      : node.node_type === "video"
        ? mediaAssetPosterRenditionPath(asset)
        : ""
    : "";
  if (node.node_type === "video" && asset) {
    return (
      <div className="agent-canvas-node__video-stage">
        {mediaUrl ? (
          <StableMediaPreview
            className="agent-canvas-node__media agent-canvas-node__media--cover"
            src={mediaUrl}
            alt={asset.display_name || "Video output"}
            draggable={false}
            loading="lazy"
            decoding="async"
            deferMs={200}
            onLoad={(event) => {
              const { naturalWidth, naturalHeight } = event.currentTarget;
              if (naturalWidth > 0 && naturalHeight > 0) {
                onMediaDimensionsResolved?.({ width: naturalWidth, height: naturalHeight });
              }
            }}
          />
        ) : (
          <div className="agent-canvas-node__media-placeholder" aria-hidden="true" />
        )}
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

  if (!mediaUrl) {
    return <div className="agent-canvas-node__media-placeholder" aria-hidden="true" />;
  }

  return (
    <StableMediaPreview
      className={`agent-canvas-node__media agent-canvas-node__media--${node.node_type === "image" ? "contain" : "cover"}`}
      src={mediaUrl}
      alt={asset?.display_name || `${NODE_TYPE_LABELS[node.node_type]} output`}
      draggable={false}
      loading="lazy"
      decoding="async"
      deferMs={200}
      onLoad={(event) => {
        const { naturalWidth, naturalHeight } = event.currentTarget;
        if (naturalWidth > 0 && naturalHeight > 0) {
          onMediaDimensionsResolved?.({ width: naturalWidth, height: naturalHeight });
        }
      }}
    />
  );
}
function NodeSurface({
  node,
  asset,
  status,
  onOpenVideoPreview,
  onOpenEditing,
  onMediaDimensionsResolved,
  onScriptContentHeightResolved,
  label,
}: Pick<AgentCanvasNodeCardProps, "node" | "asset" | "onOpenVideoPreview" | "onOpenEditing" | "onMediaDimensionsResolved" | "onScriptContentHeightResolved"> & { status: CanvasNodeStatusV2; label: string }) {
  if (node.node_type === "text" || node.node_type === "script") {
    return (
      <AgentCanvasNodeContent
        node={node}
        onScriptContentHeightResolved={onScriptContentHeightResolved}
      />
    );
  }
  if (node.node_type === "audio") {
    return <AgentCanvasAudioPlayer node={node} status={status} asset={asset} />;
  }
  if (node.node_type === "editing") {
    return <EditingNodeSurface onOpenEditing={onOpenEditing ? () => onOpenEditing(node.node_id) : undefined} />;
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
  onOpenEditing,
  onMediaDimensionsResolved,
  onScriptContentHeightResolved,
  mediaDimensions,
}: AgentCanvasNodeCardProps) {
  const status = node.status;
  const label = creativeRoleDisplayName(node.creative_role);
  const resolvedMediaDimensions = mediaDimensions
    ?? (validAgentCanvasMediaDimensions(asset)
      ? { width: asset.width, height: asset.height }
      : null);
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
      <AgentCanvasNodeHeader node={node} status={status} dimensions={resolvedMediaDimensions} />
      <div className="agent-canvas-node__surface">
        <NodeSurface
          node={node}
          asset={asset}
          status={status}
          label={label}
          onOpenVideoPreview={onOpenVideoPreview}
          onOpenEditing={onOpenEditing}
          onMediaDimensionsResolved={onMediaDimensionsResolved}
          onScriptContentHeightResolved={onScriptContentHeightResolved}
        />
        {status === "working" && (node.node_type === "image" || node.node_type === "video") ? (
          <AgentCanvasMediaGenerationLoader mediaType={node.node_type} />
        ) : status === "working" && node.node_type !== "audio" ? (
          <div className="agent-canvas-node__working" aria-label={`${node.node_type} node is working`}>
            <span className="agent-canvas-node__working-orbit" aria-hidden="true" />
            <span className="agent-canvas-node__working-sheen" aria-hidden="true" />
          </div>
        ) : null}
      </div>

      {usedDeterministicFallback ? (
        <span className="agent-canvas-node__fallback-warning" role="status">
          Created with a simplified fallback
        </span>
      ) : null}

    </article>
  );
}

function AgentCanvasNodeRendererComponent({
  id,
  data,
  selected,
  isConnectable,
}: AgentCanvasNodeRendererProps) {
  const updateNodeInternals = useUpdateNodeInternals();
  const [intrinsicDimensions, setIntrinsicDimensions] = useState<(
    AgentCanvasMediaDimensions & { assetId: string | null }
  ) | null>(null);
  const [scriptContentHeight, setScriptContentHeight] = useState(0);
  const label = creativeRoleDisplayName(data.node.creative_role);
  const workbench = data.node.node_type === "editing"
    ? null
    : data.renderWorkbench?.(data.node, data.runtime ?? null);
  const assetDimensions = validAgentCanvasMediaDimensions(data.asset)
    ? { width: data.asset.width, height: data.asset.height }
    : intrinsicDimensions?.assetId === (data.asset?.asset_id ?? null)
      ? intrinsicDimensions
      : null;
  const baseNodeSize = agentCanvasNodeSize(data.node.node_type, assetDimensions);
  const nodeSize = data.node.node_type === "script"
    ? { ...baseNodeSize, height: scriptNodeHeightForContent(scriptContentHeight) }
    : baseNodeSize;
  const handleScriptContentHeightResolved = useCallback((height: number) => {
    setScriptContentHeight((current) => current === height ? current : height);
  }, []);

  useLayoutEffect(() => {
    updateNodeInternals(id);
  }, [id, nodeSize.height, nodeSize.width, updateNodeInternals]);

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
        onOpenEditing={data.onOpenEditing}
        onMediaDimensionsResolved={validAgentCanvasMediaDimensions(data.asset)
          ? undefined
          : ({ width, height }) => setIntrinsicDimensions({
              assetId: data.asset?.asset_id ?? null,
              width,
              height,
            })}
        onScriptContentHeightResolved={data.node.node_type === "script"
          ? handleScriptContentHeightResolved
          : undefined}
        mediaDimensions={validAgentCanvasMediaDimensions(assetDimensions) ? assetDimensions : null}
      />
      {workbench ? (
        <NodeToolbar
          nodeId={id}
          isVisible
          position={Position.Bottom}
          offset={18}
          align="center"
          className="agent-canvas-node-workbench-toolbar nodrag nopan nowheel"
          onDoubleClick={(event) => event.stopPropagation()}
        >
          {workbench}
        </NodeToolbar>
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

export const AgentCanvasNodeRenderer = memo(
  AgentCanvasNodeRendererComponent,
  areAgentCanvasNodePropsEqual,
);
