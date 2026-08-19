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
  omittedNodeIds?: string[];
  patchNode: PatchNode;
  onClose: () => void;
}

function seconds(value: number | null | undefined): string {
  if (!value || value < 0) return "--";
  const minutes = Math.floor(value / 60);
  const remainder = Math.round(value % 60);
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function numericValue(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function AgentCanvasEditingPanel({
  workflow,
  node,
  omittedNodeIds = [],
  patchNode,
  onClose,
}: AgentCanvasEditingPanelProps) {
  const editing = useAgentCanvasEditing(workflow, node, patchNode);
  const activeExport = editing.content?.active_export;
  const exportRunning = activeExport?.status === "queued" || activeExport?.status === "exporting";
  const readyVideos = editing.inputs.videos.filter((input) =>
    input.entry.enabled
    && (input.node === null || input.node.status === "ready")
    && input.asset?.status === "ready",
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
                  key={input.referenceId}
                  className={`agent-editing-track agent-editing-track--${input.node?.status ?? input.asset?.status ?? "failed"}`}
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
                    <strong>{input.node?.title || input.asset?.display_name || `Shot ${index + 1}`}</strong>
                    <span>{input.node?.status ?? input.asset?.status ?? "Unavailable"} · {seconds(input.asset?.duration_seconds)}</span>
                  </div>
                  <div className="agent-editing-track__order">
                    <button
                      type="button"
                      aria-label={`Move ${input.node?.title || `clip ${index + 1}`} earlier`}
                      title="Move earlier"
                      disabled={exportRunning || index === 0}
                      onClick={() => editing.moveVideo(input.referenceId, -1)}
                    >
                      <ChevronUpIcon />
                    </button>
                    <button
                      type="button"
                      aria-label={`Move ${input.node?.title || `clip ${index + 1}`} later`}
                      title="Move later"
                      disabled={exportRunning || index === editing.inputs.videos.length - 1}
                      onClick={() => editing.moveVideo(input.referenceId, 1)}
                    >
                      <ChevronDownIcon />
                    </button>
                  </div>
                  <div className="agent-editing-track__settings">
                    <label className="agent-editing-track__toggle">
                      <input
                        type="checkbox"
                        checked={input.entry.enabled}
                        disabled={exportRunning}
                        onChange={(event) => editing.updateVideo(input.referenceId, {
                          enabled: event.currentTarget.checked,
                        })}
                      />
                      <span>Enabled</span>
                    </label>
                    <label>
                      <span>Trim start</span>
                      <input
                        type="number"
                        min="0"
                        step="0.1"
                        value={input.entry.trim_start_seconds}
                        disabled={exportRunning}
                        onChange={(event) => editing.updateVideo(input.referenceId, {
                          trim_start_seconds: Math.max(0, numericValue(event.currentTarget.value) ?? 0),
                        })}
                      />
                    </label>
                    <label>
                      <span>Trim end</span>
                      <input
                        type="number"
                        min="0.01"
                        step="0.1"
                        value={input.entry.trim_end_seconds ?? ""}
                        placeholder="Source"
                        disabled={exportRunning}
                        onChange={(event) => editing.updateVideo(input.referenceId, {
                          trim_end_seconds: numericValue(event.currentTarget.value),
                        })}
                      />
                    </label>
                    <label>
                      <span>Volume</span>
                      <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.05"
                        value={input.entry.volume}
                        disabled={exportRunning}
                        onChange={(event) => editing.updateVideo(input.referenceId, {
                          volume: Number(event.currentTarget.value),
                        })}
                      />
                    </label>
                    <label className="agent-editing-track__toggle">
                      <input
                        type="checkbox"
                        checked={input.entry.preserve_native_audio}
                        disabled={exportRunning}
                        onChange={(event) => editing.updateVideo(input.referenceId, {
                          preserve_native_audio: event.currentTarget.checked,
                        })}
                      />
                      <span>Source audio</span>
                    </label>
                    <label>
                      <span>Transition</span>
                      <select
                        value={input.entry.transition}
                        disabled={exportRunning}
                        onChange={(event) => {
                          const transition = event.currentTarget.value as "cut" | "fade";
                          editing.updateVideo(input.referenceId, {
                            transition,
                            ...(transition === "cut" ? { transition_duration_seconds: 0 } : {}),
                          });
                        }}
                      >
                        <option value="cut">Cut</option>
                        <option value="fade">Fade</option>
                      </select>
                    </label>
                    <label>
                      <span>Transition duration</span>
                      <input
                        type="number"
                        min="0"
                        max="5"
                        step="0.1"
                        value={input.entry.transition_duration_seconds}
                        disabled={exportRunning || input.entry.transition === "cut"}
                        onChange={(event) => editing.updateVideo(input.referenceId, {
                          transition_duration_seconds: Math.min(
                            5,
                            Math.max(0, numericValue(event.currentTarget.value) ?? 0),
                          ),
                        })}
                      />
                    </label>
                    <label>
                      <span>Fit</span>
                      <select
                        value={input.entry.fit_mode}
                        disabled={exportRunning}
                        onChange={(event) => editing.updateVideo(input.referenceId, {
                          fit_mode: event.currentTarget.value as "fit" | "fill",
                        })}
                      >
                        <option value="fill">Fill</option>
                        <option value="fit">Fit</option>
                      </select>
                    </label>
                  </div>
                </div>
              ))}

              <div className="agent-editing-track agent-editing-track--bgm">
                <span className="agent-editing-track__index"><MuteIcon /></span>
                <div className="agent-editing-track__identity">
                  <strong>{editing.inputs.bgm?.node?.title || editing.inputs.bgm?.asset?.display_name || "No BGM connected"}</strong>
                  <span>{editing.inputs.bgm ? seconds(editing.inputs.bgm.asset?.duration_seconds) : "Optional audio input"}</span>
                </div>
                {editing.content.manifest.bgm ? (
                  <div className="agent-editing-track__settings agent-editing-track__settings--bgm">
                    <label className="agent-editing-track__toggle">
                      <input
                        type="checkbox"
                        checked={editing.content.manifest.bgm.enabled}
                        disabled={exportRunning}
                        onChange={(event) => editing.setBgm({ enabled: event.currentTarget.checked })}
                      />
                      <span>Enabled</span>
                    </label>
                    <label>
                      <span>Trim start</span>
                      <input
                        type="number"
                        min="0"
                        step="0.1"
                        value={editing.content.manifest.bgm.trim_start_seconds}
                        disabled={exportRunning}
                        onChange={(event) => editing.setBgm({
                          trim_start_seconds: Math.max(0, numericValue(event.currentTarget.value) ?? 0),
                        })}
                      />
                    </label>
                    <label>
                      <span>Trim end</span>
                      <input
                        type="number"
                        min="0.01"
                        step="0.1"
                        value={editing.content.manifest.bgm.trim_end_seconds ?? ""}
                        placeholder="Source"
                        disabled={exportRunning}
                        onChange={(event) => editing.setBgm({
                          trim_end_seconds: numericValue(event.currentTarget.value),
                        })}
                      />
                    </label>
                    <label className="agent-editing-track__volume">
                      <span>Volume {Math.round(editing.content.manifest.bgm.volume * 100)}%</span>
                      <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.05"
                        aria-label="BGM volume"
                        value={editing.content.manifest.bgm.volume}
                        disabled={exportRunning}
                        onChange={(event) => editing.setBgmVolume(Number(event.currentTarget.value))}
                      />
                    </label>
                    <label>
                      <span>Fade in</span>
                      <input
                        type="number"
                        min="0"
                        max="30"
                        step="0.1"
                        value={editing.content.manifest.bgm.fade_in_seconds}
                        disabled={exportRunning}
                        onChange={(event) => editing.setBgm({
                          fade_in_seconds: Math.min(30, Math.max(0, numericValue(event.currentTarget.value) ?? 0)),
                        })}
                      />
                    </label>
                    <label>
                      <span>Fade out</span>
                      <input
                        type="number"
                        min="0"
                        max="30"
                        step="0.1"
                        value={editing.content.manifest.bgm.fade_out_seconds}
                        disabled={exportRunning}
                        onChange={(event) => editing.setBgm({
                          fade_out_seconds: Math.min(30, Math.max(0, numericValue(event.currentTarget.value) ?? 0)),
                        })}
                      />
                    </label>
                  </div>
                ) : null}
              </div>
            </div>

            {omittedNodeIds.length ? (
              <section
                className="agent-editing-panel__omitted"
                aria-labelledby="agent-editing-omitted-heading"
              >
                <div>
                  <h3 id="agent-editing-omitted-heading">Omitted planned inputs</h3>
                  <p>These planned nodes were not included in the prepared composition.</p>
                </div>
                <ul>
                  {omittedNodeIds.map((nodeId) => {
                    const omittedNode = workflow.nodes.find((candidate) => candidate.node_id === nodeId);
                    return (
                      <li key={nodeId}>
                        <strong>{omittedNode?.title || nodeId}</strong>
                        <span>{omittedNode ? `${omittedNode.node_type} · ${omittedNode.status}` : "Not materialized"}</span>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ) : null}

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
