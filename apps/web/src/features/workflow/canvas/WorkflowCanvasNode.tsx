import { useEffect, useRef } from "react";
import { Handle, Position, useUpdateNodeInternals, type NodeProps } from "@xyflow/react";
import type { QualityReviewStatus, QualityReviewSummary } from "../../../types";
import type { CanvasNode, NodePort, NodePortType, WorkflowNodeData } from "../types";
import { isCanvasEntityAreaNode } from "../../../workflow/canvasEntityAreas.ts";
import { NodeCardPreview } from "./WorkflowCanvasNodePreview.tsx";

function statusClass(value: string) {
  return value.replace(/[^a-z0-9_-]/gi, "-").toLowerCase();
}
function normalizedQualityStatus(status?: QualityReviewStatus | string | null): QualityReviewStatus {
  const value = typeof status === "string" && status.trim() ? status.trim().toLowerCase() : "unchecked";
  if (value === "ok" || value === "success" || value === "succeeded") return "passed";
  if (value === "warn") return "warning";
  if (value === "error") return "failed";
  return value as QualityReviewStatus;
}

function qualityStatusLabel(status?: QualityReviewStatus | string | null) {
  const normalized = normalizedQualityStatus(status);
  if (normalized === "failed") return "Needs review";
  if (normalized === "warning") return "Warning";
  if (normalized === "passed") return "Passed";
  if (normalized === "unavailable") return "Unavailable";
  return "Not reviewed yet";
}

function qualityStatusClass(status?: QualityReviewStatus | string | null) {
  return statusClass(normalizedQualityStatus(status));
}

function shouldShowNodeQualityBadge(summary?: QualityReviewSummary | null) {
  return ["warning", "failed"].includes(normalizedQualityStatus(summary?.status ?? summary?.quality_status));
}

function dataTypeLabel(dataType: NodePortType) {
  const labels: Record<NodePortType, string> = {
    prompt: "Prompt",
    text: "Text",
    image: "Image",
    video: "Video",
    audio: "Audio",
    json: "JSON",
    resource: "Resource",
    data: "Data",
  };
  return labels[dataType] ?? dataType;
}

function formatPortLabel(port: NodePort) {
  return port.label || dataTypeLabel(port.dataType);
}

function getNodeInputPorts(_nodeType: string): NodePort[] {
  return [];
}

function getNodeOutputPorts(_nodeType: string): NodePort[] {
  return [];
}

function getNodeAccentType(kind: string, outputPorts: NodePort[], inputPorts: NodePort[]): NodePortType {
  const ports = [...outputPorts, ...inputPorts];
  const preferred = ports.find((port) => port.dataType === "video" || port.dataType === "image" || port.dataType === "audio" || port.dataType === "text");
  if (preferred) return preferred.dataType;
  const normalized = kind.toLowerCase();
  if (normalized.includes("video") || normalized.includes("composition")) return "video";
  if (normalized.includes("audio") || normalized.includes("bgm") || normalized.includes("music")) return "audio";
  if (normalized.includes("image") || normalized.includes("character") || normalized.includes("scene") || normalized.includes("storyboard")) return "image";
  if (normalized.includes("script") || normalized.includes("prompt") || normalized.includes("text")) return "text";
  return "data";
}

const NODE_TYPE_ICON_SOURCES = {
  image: "/imgs/image.webp",
  audio: "/imgs/audio.webp",
  text: "/imgs/text.webp",
  video: "/imgs/video.webp",
} as const;

type NodeTypeIcon = {
  src: string;
  label: string;
};

function getNodeTypeIcon(data: Pick<WorkflowNodeData, "family" | "kind" | "category">): NodeTypeIcon | null {
  const kind = `${data.kind} ${data.category}`.toLowerCase();
  const family = data.family;

  if (family === "Audio" || kind.includes("audio") || kind.includes("bgm") || kind.includes("music") || kind.includes("voice")) {
    return { src: NODE_TYPE_ICON_SOURCES.audio, label: "Audio" };
  }

  if (family === "Video" || family === "Preview" || kind.includes("video") || kind.includes("composition") || kind.includes("final")) {
    return { src: NODE_TYPE_ICON_SOURCES.video, label: "Video" };
  }

  if (family === "Image" || kind.includes("image") || kind.includes("frame") || kind.includes("character") || kind.includes("scene") || kind.includes("storyboard")) {
    return { src: NODE_TYPE_ICON_SOURCES.image, label: "Image" };
  }

  if (family === "Text" || kind.includes("text") || kind.includes("script") || kind.includes("prompt") || kind.includes("copy") || kind.includes("direction")) {
    return { src: NODE_TYPE_ICON_SOURCES.text, label: "Text" };
  }

  return null;
}

function visibleNodeStatus(status?: string | null) {
  const normalized = (status ?? "").toLowerCase();
  return normalized && normalized !== "idle" && normalized !== "stale" ? status : "";
}

function NodeQualityBadge({ summary }: { summary?: QualityReviewSummary | null }) {
  if (!shouldShowNodeQualityBadge(summary)) return null;
  const status = normalizedQualityStatus(summary?.status ?? summary?.quality_status);
  const failedCount = summary?.failed_count ?? 0;
  const warningCount = summary?.warning_count ?? 0;
  const count = status === "failed" ? failedCount : warningCount;
  return (
    <span className={`node-quality-badge status-${qualityStatusClass(status)}`} title="Quality review status">
      {qualityStatusLabel(status)}{count ? ` · ${count}` : ""}
    </span>
  );
}

function isNodeRunning(status?: string | null) {
  const normalized = (status ?? "").toLowerCase();
  return ["running", "waiting", "processing", "in_progress"].includes(normalized);
}

export function WorkflowCanvasNode({ id, data, selected }: NodeProps<CanvasNode>) {
  const cardRef = useRef<HTMLDivElement | null>(null);
  const inputPorts = data.inputPorts?.length ? data.inputPorts : getNodeInputPorts(data.kind);
  const outputPorts = data.outputPorts?.length ? data.outputPorts : getNodeOutputPorts(data.kind);
  const accentType = getNodeAccentType(data.kind, outputPorts, inputPorts);
  const nodeTypeIcon = getNodeTypeIcon(data);
  const nodeRunning = isNodeRunning(data.status);
  const entityAreaClassName = isCanvasEntityAreaNode(data.kind) ? " is-entity-area-node" : "";
  const v2RegionClassName = data.isV2Region ? " is-v2-region-node" : "";
  const updateNodeInternals = useUpdateNodeInternals();

  useEffect(() => {
    if (!data.isV2Region) return;
    const frame = window.requestAnimationFrame(() => updateNodeInternals(id));
    return () => window.cancelAnimationFrame(frame);
  }, [data.isV2Region, data.v2Items?.length, data.v2Slots?.length, data.v2OpenSlotId, id, updateNodeInternals]);

  useEffect(() => {
    if (!data.isV2Region || !cardRef.current || typeof ResizeObserver === "undefined") return;
    let frame: number | null = null;
    const observer = new ResizeObserver(() => {
      if (frame !== null) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        frame = null;
        updateNodeInternals(id);
      });
    });
    observer.observe(cardRef.current);
    return () => {
      observer.disconnect();
      if (frame !== null) window.cancelAnimationFrame(frame);
    };
  }, [data.isV2Region, id, updateNodeInternals]);

  return (
    <div ref={cardRef} className={`workflow-card planned${entityAreaClassName}${v2RegionClassName} ${selected ? "is-selected" : ""} type-${statusClass(data.kind)} family-${data.family.toLowerCase()}`}>
      <div className="workflow-port-stack workflow-port-stack-left">
        {inputPorts.map((port) => (
          <div className="workflow-port-row input" key={port.id}>
            <Handle
              id={port.id}
              className={`workflow-handle workflow-handle-input nodrag type-${port.dataType}`}
              type="target"
              position={Position.Left}
              isConnectableStart={false}
              isConnectableEnd
            />
            <span className={`workflow-port-label type-${port.dataType}`}>{formatPortLabel(port)}</span>
          </div>
        ))}
      </div>
      <div className="workflow-card-identity">
        <div className="workflow-card-top">
          {nodeTypeIcon ? (
            <span className="workflow-node-type-icon" aria-label={`${nodeTypeIcon.label} node type`} title={`${nodeTypeIcon.label} node type`}>
              <img src={nodeTypeIcon.src} alt="" />
            </span>
          ) : (
            <span className={`workflow-node-type-fallback type-${accentType}`}>{data.category}</span>
          )}
        </div>
        <h3>{data.title}</h3>
      </div>
      <span className="workflow-card-identity-divider" aria-hidden="true" />
      <NodeCardPreview data={data} onOpenMedia={data.onOpenMedia} onSelectDynamicItem={data.onSelectDynamicItem} isRunning={nodeRunning} runningById={data.runningDynamicItemById} />
      <div className="node-status-row">
        {visibleNodeStatus(data.status) ? <span className={`status-pill ${visibleNodeStatus(data.status)}`}>{visibleNodeStatus(data.status)}</span> : null}
        <NodeQualityBadge summary={data.qualitySummary} />
        {data.candidateCount ? <span className="state-chip candidate">candidate {data.candidateCount}</span> : null}
        {data.candidateWarningCount ? <span className="state-chip warning">review {data.candidateWarningCount}</span> : null}
        {data.version ? <span className="state-chip">v{data.version}</span> : null}
        {data.locked ? <span className="state-chip locked">lock</span> : null}
      </div>
      <div className="workflow-port-stack workflow-port-stack-right">
        {outputPorts.map((port) => (
          <div className="workflow-port-row output" key={port.id}>
            <span className={`workflow-port-label type-${port.dataType}`}>{formatPortLabel(port)}</span>
            <Handle
              id={port.id}
              className={`workflow-handle workflow-handle-output nodrag type-${port.dataType}`}
              type="source"
              position={Position.Right}
              isConnectableStart
              isConnectableEnd={false}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
