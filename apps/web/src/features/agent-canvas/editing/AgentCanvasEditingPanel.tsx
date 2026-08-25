import { useState } from "react";

import {
  CloseIcon,
  DownloadIcon,
  FastForwardIcon,
  PauseIcon,
  PlayIcon,
  PlusIcon,
  RewindIcon,
  UploadIcon,
  MuteIcon,
  UnmuteIcon,
} from "../../../icons.tsx";
import type {
  AgentCanvasWorkflowV2,
  CanvasNodePatchRequestV2,
  CanvasNodeV2,
} from "../../../types-v2.ts";
import { EditingPreviewStage } from "./EditingPreviewStage.tsx";
import { EditingTimeline } from "./EditingTimeline.tsx";
import { buildTimelineSegments } from "./editingTimelineMath.ts";
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
  onDownloadExport?: (assetId: string) => Promise<void> | void;
  onAddExportToCanvas?: (exportId: string) => Promise<void> | void;
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
  omittedNodeIds = [],
  patchNode,
  onClose,
  onDownloadExport,
  onAddExportToCanvas,
}: AgentCanvasEditingPanelProps) {
  const editing = useAgentCanvasEditing(workflow, node, patchNode);
  const [addingToCanvas, setAddingToCanvas] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [playheadSeconds, setPlayheadSeconds] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [selectedReferenceState, setSelectedReferenceState] = useState<string | null>(null);
  const activeExport = editing.content?.active_export;
  const exportRunning = activeExport?.status === "queued" || activeExport?.status === "exporting";
  const canReuseExport = editing.exportReadable && editing.terminalExport?.output_asset_id
    ? editing.terminalExport
    : null;
  const readyVideos = editing.inputs.videos.filter((input) =>
    input.entry.enabled
    && (input.node === null || input.node.status === "ready")
    && input.asset?.status === "ready",
  ).length;
  const previewSegments = buildTimelineSegments(editing.inputs.videos.map((input) => ({
    referenceId: input.referenceId,
    sourceDuration: input.asset?.duration_seconds
      ?? input.entry.trim_end_seconds
      ?? input.entry.trim_start_seconds + 0.5,
    trimStart: input.entry.trim_start_seconds,
    trimEnd: input.entry.trim_end_seconds,
  })));
  const sequenceDuration = previewSegments.at(-1)?.timelineEnd ?? 0;
  const timelineDuration = sequenceDuration > 0
    ? sequenceDuration
    : Math.max(editing.content?.preview.estimated_duration_seconds ?? 0, 1);
  const hasPlayableDraft = editing.inputs.videos.some((input) => (
    input.entry.enabled
    && input.asset?.status === "ready"
    && Boolean(input.asset.media_url)
  ));
  const selectedReferenceId = selectedReferenceState
    && (editing.inputs.videos.some((input) => input.referenceId === selectedReferenceState)
      || editing.inputs.bgm?.referenceId === selectedReferenceState)
    ? selectedReferenceState
    : editing.inputs.videos[0]?.referenceId ?? editing.inputs.bgm?.referenceId ?? null;

  const handleAddToCanvas = async () => {
    if (!canReuseExport || !onAddExportToCanvas || addingToCanvas) return;
    setAddingToCanvas(true);
    setActionError(null);
    try {
      await onAddExportToCanvas(canReuseExport.export_id);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Unable to add the exported video to canvas.");
    } finally {
      setAddingToCanvas(false);
    }
  };

  const seekPreview = (value: number) => {
    const next = Math.max(0, Math.min(timelineDuration, value));
    setPlayheadSeconds(next);
  };

  const togglePreview = () => {
    if (!hasPlayableDraft) return;
    if (!playing && playheadSeconds >= timelineDuration) setPlayheadSeconds(0);
    setPlaying((value) => !value);
  };

  const nudgePreview = (offset: number) => seekPreview(playheadSeconds + offset);

  return (
    <section className="agent-editing-panel" aria-label="Editing node">
      <header className="agent-editing-panel__header">
        <div>
          <span className="agent-editing-panel__eyebrow">Editing Node</span>
          <h2>{node.title || "Final composition"}</h2>
        </div>
        <div className="agent-editing-panel__header-actions">
          {editing.content?.dirty ? <span className="agent-editing-panel__dirty">Changes not exported</span> : null}
          {canReuseExport ? (
            <>
              <button
                type="button"
                aria-label="Download exported video"
                className="agent-editing-panel__toolbar-button"
                disabled={editing.downloading}
                onClick={() => {
                  const assetId = canReuseExport.output_asset_id;
                  if (!assetId) return;
                  if (onDownloadExport) void onDownloadExport(assetId);
                  else void editing.downloadExport(assetId);
                }}
                title="Download exported video"
              >
                <DownloadIcon />
                <span>{editing.downloading ? "Downloading" : "Download"}</span>
              </button>
              {onAddExportToCanvas ? (
                <button
                  type="button"
                  aria-label="Add exported video to canvas"
                  className="agent-editing-panel__toolbar-button"
                  disabled={addingToCanvas}
                  onClick={() => void handleAddToCanvas()}
                  title="Add exported video to canvas"
                >
                  <PlusIcon />
                  <span>{addingToCanvas ? "Adding" : "Add to Canvas"}</span>
                </button>
              ) : null}
            </>
          ) : null}
          <button type="button" className="agent-editing-panel__icon-button" aria-label="Close editor" title="Close editor" onClick={onClose}>
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
              <EditingPreviewStage
                inputs={editing.inputs}
                outputAspectRatio={editing.content.manifest.output.aspect_ratio}
                outputResolution={editing.content.manifest.output.resolution}
                exportedAsset={editing.outputAsset}
                playheadSeconds={playheadSeconds}
                playing={playing}
                muted={muted}
                onPlayheadChange={seekPreview}
                onPlayingChange={setPlaying}
              />
              {exportRunning ? (
                <div className="agent-editing-panel__export-overlay" role="status">
                  <span aria-hidden="true" />
                  {activeExport?.status === "queued" ? "Export queued" : "Exporting"}
                </div>
              ) : null}
            </div>
            <div className="agent-editing-panel__transport" aria-label="Preview controls">
              <button type="button" aria-label="Rewind preview" title="Rewind 5 seconds" onClick={() => nudgePreview(-5)}>
                <RewindIcon />
              </button>
              <button type="button" className="agent-editing-panel__transport-play" aria-label={playing ? "Pause preview" : "Play preview"} title={playing ? "Pause preview" : "Play preview"} disabled={!hasPlayableDraft} onClick={togglePreview}>
                {playing ? <PauseIcon /> : <PlayIcon />}
              </button>
              <button type="button" aria-label="Fast forward preview" title="Fast forward 5 seconds" onClick={() => nudgePreview(5)}>
                <FastForwardIcon />
              </button>
              <span className="agent-editing-panel__transport-time">{seconds(playheadSeconds)} / {seconds(timelineDuration)}</span>
              <button type="button" aria-label={muted ? "Unmute preview" : "Mute preview"} title={muted ? "Unmute preview" : "Mute preview"} onClick={() => setMuted((value) => !value)}>
                {muted ? <MuteIcon /> : <UnmuteIcon />}
              </button>
            </div>
            <div className="agent-editing-panel__output">
              <label>
                <span>Resolution</span>
                <select value={editing.content.manifest.output.resolution ?? ""} disabled={exportRunning} onChange={(event) => editing.setOutput({ resolution: event.currentTarget.value || null })}>
                  <option value="">Source</option>
                  <option value="1280x720">1280 x 720</option>
                  <option value="1920x1080">1920 x 1080</option>
                  <option value="1080x1920">1080 x 1920</option>
                </select>
              </label>
              <label>
                <span>Aspect ratio</span>
                <select value={editing.content.manifest.output.aspect_ratio ?? ""} disabled={exportRunning} onChange={(event) => editing.setOutput({ aspect_ratio: event.currentTarget.value || null })}>
                  <option value="">Source</option>
                  <option value="16:9">16:9</option>
                  <option value="9:16">9:16</option>
                  <option value="1:1">1:1</option>
                </select>
              </label>
              <label>
                <span>FPS</span>
                <input type="number" min="1" max="120" step="1" value={editing.content.manifest.output.fps ?? ""} disabled={exportRunning} onChange={(event) => editing.setOutput({ fps: event.currentTarget.value ? Number(event.currentTarget.value) : null })} />
              </label>
            </div>
          </div>

          <div className="agent-editing-panel__timeline-column">
            <div className="agent-editing-panel__timeline-heading">
              <div>
                <h3>Timeline</h3>
                <span>{editing.inputs.videos.length} clips · {seconds(editing.content.preview.estimated_duration_seconds)}</span>
              </div>
              <div className="agent-editing-panel__export-actions">
                {exportRunning ? (
                  <button type="button" className="agent-editing-panel__cancel-export" disabled={editing.exporting} onClick={() => void editing.cancelExport()}>
                    <CloseIcon />
                    <span>Cancel</span>
                  </button>
                ) : (
                  <button type="button" className="agent-editing-panel__export" disabled={editing.exporting || editing.saving || readyVideos === 0} onClick={() => void editing.exportComposition()}>
                    <UploadIcon />
                    <span>{editing.exporting ? "Starting" : "Export"}</span>
                  </button>
                )}
              </div>
            </div>

            <EditingTimeline
              inputs={editing.inputs}
              timelineDuration={timelineDuration}
              playheadSeconds={playheadSeconds}
              selectedReferenceId={selectedReferenceId}
              exportRunning={exportRunning}
              onPlayheadChange={seekPreview}
              onSelectReference={setSelectedReferenceState}
              onMoveVideo={editing.moveVideo}
              onUpdateVideo={editing.updateVideo}
              onStageVideo={editing.stageVideoUpdate}
              onCommitStagedManifest={editing.commitStagedManifest}
              onDiscardStagedManifest={editing.discardStagedManifest}
              onSetBgm={editing.setBgm}
              onSetBgmVolume={editing.setBgmVolume}
            />

            {omittedNodeIds.length ? (
              <section className="agent-editing-panel__omitted" aria-labelledby="agent-editing-omitted-heading">
                <div>
                  <h3 id="agent-editing-omitted-heading">Omitted planned inputs</h3>
                  <p>These planned nodes were not included in the prepared composition.</p>
                </div>
                <ul>
                  {omittedNodeIds.map((nodeId) => {
                    const omittedNode = workflow.nodes.find((candidate) => candidate.node_id === nodeId);
                    return <li key={nodeId}><strong>{omittedNode?.title || nodeId}</strong><span>{omittedNode ? `${omittedNode.node_type} · ${omittedNode.status}` : "Not materialized"}</span></li>;
                  })}
                </ul>
              </section>
            ) : null}
            {editing.content.preview.warnings.length ? <ul className="agent-editing-panel__warnings">{editing.content.preview.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}
            {editing.error ? <button type="button" className="agent-editing-panel__error" onClick={editing.clearError}>{editing.error}</button> : null}
            {actionError ? <button type="button" className="agent-editing-panel__error" onClick={() => setActionError(null)}>{actionError}</button> : null}
          </div>
        </div>
      )}
    </section>
  );
}
