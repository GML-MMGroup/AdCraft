import {
  ChevronDownIcon,
  ChevronUpIcon,
  CloseIcon,
  MuteIcon,
  UploadIcon,
  VideoIcon,
} from "../../../icons.tsx";
import type {
  AgentCanvasWorkflowV2,
  CanvasNodePatchRequestV2,
  CanvasNodeV2,
} from "../../../types-v2.ts";
import { useAgentCanvasEditing } from "./useAgentCanvasEditing.ts";
import "./agent-canvas-editing.css";

type PatchNode = (
  nodeId: string,
  patch: CanvasNodePatchRequestV2,
  options?: { coalesce?: boolean; optimistic?: boolean },
) => Promise<void>;

export interface AgentCanvasEditingPanelProps {
  workflow: AgentCanvasWorkflowV2;
  node: CanvasNodeV2;
  patchNode: PatchNode;
  onClose: () => void;
}

function seconds(value: number | null | undefined): string {
  if (!value || value < 0) return "--";
  const minutes = Math.floor(value / 60);
  const remainder = Math.round(value % 60);
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

export function AgentCanvasEditingPanel({
  workflow,
  node,
  patchNode,
  onClose,
}: AgentCanvasEditingPanelProps) {
  const editing = useAgentCanvasEditing(workflow, node, patchNode);
  const activeExport = editing.content?.active_export;
  const exportRunning = activeExport?.status === "queued" || activeExport?.status === "exporting";
  const readyVideos = editing.inputs.videos.filter((input) =>
    input.node.status === "ready" && input.asset?.status === "ready",
  ).length;

  return (
    <section className="agent-editing-panel" aria-label="Editing node">
      <header className="agent-editing-panel__header">
        <div>
          <span className="agent-editing-panel__eyebrow">Editing Node</span>
          <h2>{node.title || "Final composition"}</h2>
        </div>
        <div className="agent-editing-panel__header-actions">
          {editing.content?.dirty ? (
            <span className="agent-editing-panel__dirty">Changes not exported</span>
          ) : null}
          <button
            type="button"
            className="agent-editing-panel__icon-button"
            aria-label="Close editor"
            title="Close editor"
            onClick={onClose}
          >
            <CloseIcon />
          </button>
        </div>
      </header>

      {!editing.content ? (
        <div className="agent-editing-panel__unavailable" role="alert">
          This Editing node does not yet contain a valid composition manifest.
        </div>
      ) : (
        <div className="agent-editing-panel__workspace">
          <div className="agent-editing-panel__preview-column">
            <div className="agent-editing-panel__preview">
              {editing.outputAsset?.media_url ? (
                <video
                  key={editing.outputAsset.asset_id}
                  src={editing.outputAsset.media_url}
                  poster={editing.outputAsset.preview_url ?? undefined}
                  controls
                  playsInline
                  preload="metadata"
                />
              ) : (
                <div className="agent-editing-panel__preview-empty">
                  <VideoIcon aria-hidden="true" />
                  <span>No exported video</span>
                </div>
              )}
              {exportRunning ? (
                <div className="agent-editing-panel__export-overlay" role="status">
                  <span aria-hidden="true" />
                  {activeExport?.status === "queued" ? "Export queued" : "Exporting"}
                </div>
              ) : null}
            </div>

            <div className="agent-editing-panel__output">
              <label>
                <span>Resolution</span>
                <select
                  value={editing.content.manifest.output.resolution ?? ""}
                  disabled={exportRunning}
                  onChange={(event) => editing.setOutput({
                    resolution: event.currentTarget.value || null,
                  })}
                >
                  <option value="">Source</option>
                  <option value="1280x720">1280 x 720</option>
                  <option value="1920x1080">1920 x 1080</option>
                  <option value="1080x1920">1080 x 1920</option>
                </select>
              </label>
              <label>
                <span>Aspect ratio</span>
                <select
                  value={editing.content.manifest.output.aspect_ratio ?? ""}
                  disabled={exportRunning}
                  onChange={(event) => editing.setOutput({
                    aspect_ratio: event.currentTarget.value || null,
                  })}
                >
                  <option value="">Source</option>
                  <option value="16:9">16:9</option>
                  <option value="9:16">9:16</option>
                  <option value="1:1">1:1</option>
                </select>
              </label>
              <label>
                <span>FPS</span>
                <input
                  type="number"
                  min="1"
                  max="120"
                  step="1"
                  value={editing.content.manifest.output.fps ?? ""}
                  disabled={exportRunning}
                  onChange={(event) => editing.setOutput({
                    fps: event.currentTarget.value
                      ? Number(event.currentTarget.value)
                      : null,
                  })}
                />
              </label>
            </div>
          </div>

          <div className="agent-editing-panel__timeline-column">
            <div className="agent-editing-panel__timeline-heading">
              <div>
                <h3>Sequence</h3>
                <span>{editing.inputs.videos.length} clips · {seconds(editing.content.preview.estimated_duration_seconds)}</span>
              </div>
              <div className="agent-editing-panel__export-actions">
                {exportRunning ? (
                  <button
                    type="button"
                    className="agent-editing-panel__cancel-export"
                    disabled={editing.exporting}
                    onClick={() => void editing.cancelExport()}
                  >
                    <CloseIcon />
                    <span>Cancel</span>
                  </button>
                ) : (
                  <button
                    type="button"
                    className="agent-editing-panel__export"
                    disabled={editing.exporting || editing.saving || readyVideos === 0}
                    onClick={() => void editing.exportComposition()}
                  >
                    <UploadIcon />
                    <span>{editing.exporting ? "Starting" : "Export"}</span>
                  </button>
                )}
              </div>
            </div>

            <div className="agent-editing-panel__tracks">
              {editing.inputs.videos.length === 0 ? (
                <div className="agent-editing-panel__empty-track">
                  Connect Video nodes to add clips.
                </div>
              ) : editing.inputs.videos.map((input, index) => (
                <div
                  key={input.binding.binding_id}
                  className={`agent-editing-track agent-editing-track--${input.node.status}`}
                >
                  <span className="agent-editing-track__index">{String(index + 1).padStart(2, "0")}</span>
                  <div className="agent-editing-track__thumbnail">
                    {input.asset?.preview_url ? (
                      <img src={input.asset.preview_url} alt="" />
                    ) : (
                      <VideoIcon aria-hidden="true" />
                    )}
                  </div>
                  <div className="agent-editing-track__identity">
                    <strong>{input.node.title || `Shot ${index + 1}`}</strong>
                    <span>{input.node.status} · {seconds(input.asset?.duration_seconds)}</span>
                  </div>
                  <div className="agent-editing-track__order">
                    <button
                      type="button"
                      aria-label={`Move ${input.node.title || `clip ${index + 1}`} earlier`}
                      title="Move earlier"
                      disabled={exportRunning || index === 0}
                      onClick={() => editing.moveVideo(input.binding.binding_id, -1)}
                    >
                      <ChevronUpIcon />
                    </button>
                    <button
                      type="button"
                      aria-label={`Move ${input.node.title || `clip ${index + 1}`} later`}
                      title="Move later"
                      disabled={exportRunning || index === editing.inputs.videos.length - 1}
                      onClick={() => editing.moveVideo(input.binding.binding_id, 1)}
                    >
                      <ChevronDownIcon />
                    </button>
                  </div>
                </div>
              ))}

              <div className="agent-editing-track agent-editing-track--bgm">
                <span className="agent-editing-track__index"><MuteIcon /></span>
                <div className="agent-editing-track__identity">
                  <strong>{editing.inputs.bgm?.node.title || "No BGM connected"}</strong>
                  <span>{editing.inputs.bgm ? seconds(editing.inputs.bgm.asset?.duration_seconds) : "Optional audio input"}</span>
                </div>
                <label className="agent-editing-track__volume">
                  <span>{Math.round(editing.content.manifest.bgm_volume * 100)}%</span>
                  <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.05"
                    aria-label="BGM volume"
                    value={editing.content.manifest.bgm_volume}
                    disabled={!editing.inputs.bgm || exportRunning}
                    onChange={(event) => editing.setBgmVolume(Number(event.currentTarget.value))}
                  />
                </label>
              </div>
            </div>

            {editing.content.preview.warnings.length ? (
              <ul className="agent-editing-panel__warnings">
                {editing.content.preview.warnings.map((warning) => <li key={warning}>{warning}</li>)}
              </ul>
            ) : null}
            {editing.error ? (
              <button
                type="button"
                className="agent-editing-panel__error"
                onClick={editing.clearError}
              >
                {editing.error}
              </button>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}
