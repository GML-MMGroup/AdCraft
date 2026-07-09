import { LocalRevisionCandidateCard } from "../assets/AssetRevisionPanels.tsx";
import { NodeAttachmentPreview } from "../components/NodeAttachmentPreview.tsx";
import { dedupeAssets } from "../../../workflow/assets.ts";
import { pendingVisibleRevisionCandidates } from "../../../workflow/localRevision.ts";
import type {
  FinalCompositionAvailableSource,
  FinalCompositionTimeline,
  FinalCompositionTimelineClip,
  FinalCompositionTimelineTrack,
  UploadedAsset,
  WorkflowRevisionState,
} from "../../../types";
import type { LocalRevisionCardState } from "../assets/useWorkflowAssetOperations.ts";
import type { FinalCompositionTimelineViewState } from "./useFinalCompositionPageController.ts";

const LOCAL_REVISION_HISTORY_PREVIEW_LIMIT = 12;

function statusClass(value: string) {
  return value.replace(/[^a-z0-9_-]/gi, "-").toLowerCase();
}

function isLocalRevisionRunningStatus(status?: string | null) {
  const normalized = (status ?? "").toLowerCase();
  return normalized === "queued" || normalized === "running" || normalized === "waiting" || normalized === "pending";
}

function localRevisionPendingCandidatesForState(state?: LocalRevisionCardState) {
  return pendingVisibleRevisionCandidates(dedupeRevisionStates([...(state?.revisions ?? []), ...(state?.candidates ?? [])]));
}

function dedupeRevisionStates(revisions: WorkflowRevisionState[]) {
  const seen = new Set<string>();
  return revisions.filter((revision) => {
    const key = revision.revision_id || JSON.stringify([revision.status, revision.updated_at, revision.created_at, revision.target_asset_id, revision.semantic_type]);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
export function FinalCompositionTimelinePanel({
  state,
  timeline,
  activeAsset,
  revisionState,
  busyByRevisionId,
  qualityOverrideRevisionId,
  renderDisabledReason,
  onRefresh,
  onSave,
  onRender,
  onMoveClip,
  onToggleClip,
  onChangeClipNumber,
  onChangeSubtitleText,
  onSelectAudioSource,
  onAddSourceAsImageClip,
  onRemoveClip,
  onOpenAsset,
  onAcceptCandidate,
  onRejectCandidate,
  onUseVersion,
  onCancelQualityOverride,
}: {
  state: FinalCompositionTimelineViewState;
  timeline: FinalCompositionTimeline | null;
  activeAsset: UploadedAsset | null;
  revisionState?: LocalRevisionCardState;
  busyByRevisionId: Record<string, "accept" | "reject" | undefined>;
  qualityOverrideRevisionId: string | null;
  renderDisabledReason: string;
  onRefresh: () => void;
  onSave: () => void;
  onRender: () => void;
  onMoveClip: (trackId: string, clipId: string, direction: -1 | 1) => void;
  onToggleClip: (trackId: string, clipId: string, enabled: boolean) => void;
  onChangeClipNumber: (trackId: string, clipId: string, field: "start_time" | "duration" | "trim_start" | "trim_end", value: number) => void;
  onChangeSubtitleText: (trackId: string, clipId: string, text: string) => void;
  onSelectAudioSource: (trackId: string, clipId: string, sourceAssetId: string) => void;
  onAddSourceAsImageClip: (source: FinalCompositionAvailableSource) => void;
  onRemoveClip: (trackId: string, clipId: string) => void;
  onOpenAsset: (asset: UploadedAsset) => void;
  onAcceptCandidate: (revision: WorkflowRevisionState, overrideQualityFailure?: boolean) => void;
  onRejectCandidate: (revision: WorkflowRevisionState) => void;
  onUseVersion: (asset: UploadedAsset) => void;
  onCancelQualityOverride: () => void;
}) {
  const orderedTrackIds = ["video_main", "image_overlay", "subtitle", "audio_bgm"];
  const tracks = timeline
    ? [
        ...orderedTrackIds.flatMap((trackId) => timeline.tracks.find((track) => track.track_id === trackId) ?? []),
        ...timeline.tracks.filter((track) => !orderedTrackIds.includes(track.track_id)),
      ]
    : [];
  const available_sources = state.availableSources;
  const stale_clip_ids = state.staleClipIds;
  const missing_source_clip_ids = state.missingSourceClipIds;
  const imageSources = available_sources.filter((source) => finalCompositionSourceTrack(source) === "image_overlay" || finalCompositionSourceAsset(source)?.asset_type === "image");
  const audioSources = available_sources.filter((source) => finalCompositionSourceTrack(source) === "audio_bgm" || finalCompositionSourceAsset(source)?.asset_type === "audio");
  const pendingFinalCandidates = localRevisionPendingCandidatesForState(revisionState);
  const historyAssets = dedupeAssets([...(revisionState?.history ?? []), ...(revisionState?.assets ?? [])]);
  const activeAssetId = activeAsset?.asset_id ?? revisionState?.activeAsset?.asset_id ?? "";
  const finalVideoHistory = historyAssets.filter((asset) => asset.asset_id !== activeAssetId).slice(0, LOCAL_REVISION_HISTORY_PREVIEW_LIMIT);

  return (
    <section className="final-composition-timeline-panel">
      <div className="final-composition-timeline-heading">
        <span>
          <strong>Final Composition Timeline</strong>
          <em>{timeline ? `v${timeline.version} · ${timeline.duration_seconds}s` : "Not loaded"}</em>
        </span>
        <div className="final-composition-timeline-actions">
          <button className="small-action" type="button" disabled={state.loading} onClick={onRefresh}>
            {state.loading ? "Loading..." : "Refresh"}
          </button>
          <button className="small-action" type="button" disabled={!timeline || !state.dirty || state.saving} onClick={onSave}>
            {state.saving ? "Saving..." : "Save timeline"}
          </button>
          <button className="small-action" type="button" disabled={!timeline || Boolean(renderDisabledReason) || state.rendering} onClick={onRender}>
            {state.rendering ? "Rendering..." : "Render candidate"}
          </button>
        </div>
      </div>
      <div className="final-composition-timeline-meta">
        <span>available_sources: {available_sources.length}</span>
        <span>stale_clip_ids: {stale_clip_ids.length}</span>
        <span>missing_source_clip_ids: {missing_source_clip_ids.length}</span>
        {state.dirty ? <b>Unsaved changes</b> : null}
        {state.eventDirty ? <b>Backend updated timeline</b> : null}
      </div>
      {state.error ? (
        <span className="final-composition-timeline-error">
          {state.error} Current active final video remains available.
        </span>
      ) : null}
      {state.conflict ? <span className="final-composition-timeline-error">{state.conflict}</span> : null}
      {state.renderError ? (
        <span className="final-composition-timeline-error">
          {state.renderError} Current active final video remains available.
        </span>
      ) : null}
      {renderDisabledReason ? <span className="final-composition-timeline-warning">{renderDisabledReason}</span> : null}

      {tracks.length ? (
        <div className="final-composition-track-list">
          {tracks.map((track) => (
            <section key={track.track_id} className={`final-composition-track track-${statusClass(track.track_id)}`}>
              <div className="final-composition-track-heading">
                <span>{finalCompositionTrackLabel(track)}</span>
                <em>{track.clips.length} clip{track.clips.length === 1 ? "" : "s"}</em>
              </div>
              <div className="final-composition-clip-list">
                {track.clips.map((clip, index) => {
                  const clipAsset = finalCompositionClipAsset(clip, available_sources);
                  const clipStale = Boolean(clip.stale) || stale_clip_ids.includes(clip.clip_id);
                  const clipMissing = Boolean(clip.missing_source) || missing_source_clip_ids.includes(clip.clip_id);
                  return (
                    <article key={clip.clip_id} className={`final-composition-clip ${clipStale ? "is-stale" : ""} ${clipMissing ? "is-missing" : ""}`}>
                      <div className="final-composition-clip-preview">
                        {clipAsset ? <NodeAttachmentPreview asset={clipAsset} onOpen={() => onOpenAsset(clipAsset)} /> : <span>{clip.clip_type}</span>}
                      </div>
                      <div className="final-composition-clip-body">
                        <div className="final-composition-clip-title">
                          <strong>{finalCompositionClipLabel(clip, clipAsset)}</strong>
                          <em>{clip.clip_type} · {clip.clip_id}</em>
                        </div>
                        <label className="final-composition-toggle">
                          <input type="checkbox" checked={clip.enabled !== false} onChange={(event) => onToggleClip(track.track_id, clip.clip_id, event.target.checked)} />
                          <span>Enabled</span>
                        </label>
                        <div className="final-composition-number-grid">
                          <label>
                            <span>Start</span>
                            <input type="number" step="0.1" value={clip.start_time ?? 0} onChange={(event) => onChangeClipNumber(track.track_id, clip.clip_id, "start_time", event.currentTarget.valueAsNumber)} />
                          </label>
                          <label>
                            <span>Duration</span>
                            <input type="number" step="0.1" min="0" value={clip.duration ?? 0} onChange={(event) => onChangeClipNumber(track.track_id, clip.clip_id, "duration", event.currentTarget.valueAsNumber)} />
                          </label>
                          <label>
                            <span>Trim in</span>
                            <input type="number" step="0.1" min="0" value={clip.trim_start ?? 0} onChange={(event) => onChangeClipNumber(track.track_id, clip.clip_id, "trim_start", event.currentTarget.valueAsNumber)} />
                          </label>
                          <label>
                            <span>Trim out</span>
                            <input type="number" step="0.1" min="0" value={clip.trim_end ?? 0} onChange={(event) => onChangeClipNumber(track.track_id, clip.clip_id, "trim_end", event.currentTarget.valueAsNumber)} />
                          </label>
                        </div>
                        {track.track_id === "subtitle" || clip.clip_type === "subtitle" ? (
                          <label className="final-composition-subtitle-field">
                            <span>Subtitle text</span>
                            <textarea value={clip.text ?? ""} onChange={(event) => onChangeSubtitleText(track.track_id, clip.clip_id, event.currentTarget.value)} />
                          </label>
                        ) : null}
                        {track.track_id === "audio_bgm" || clip.clip_type === "audio" ? (
                          <label className="final-composition-audio-field">
                            <span>BGM source</span>
                            <select value={clip.source_asset_id ?? ""} onChange={(event) => onSelectAudioSource(track.track_id, clip.clip_id, event.currentTarget.value)}>
                              <option value="">Use backend default</option>
                              {audioSources.map((source) => (
                                <option key={source.source_id || source.asset_id} value={source.asset_id}>
                                  {finalCompositionSourceLabel(source)}
                                </option>
                              ))}
                            </select>
                          </label>
                        ) : null}
                        {clipStale || clipMissing ? (
                          <span className="final-composition-clip-warning">
                            {clipStale ? state.staleReasons[clip.clip_id] ?? clip.stale_reason ?? "stale clip" : ""}
                            {clipStale && clipMissing ? " · " : ""}
                            {clipMissing ? state.missingSourceReasons[clip.clip_id] ?? clip.missing_reason ?? "missing source" : ""}
                          </span>
                        ) : null}
                      </div>
                      <div className="final-composition-clip-actions">
                        <button className="asset-revision-trigger" type="button" disabled={index === 0} onClick={() => onMoveClip(track.track_id, clip.clip_id, -1)}>
                          Up
                        </button>
                        <button className="asset-revision-trigger" type="button" disabled={index === track.clips.length - 1} onClick={() => onMoveClip(track.track_id, clip.clip_id, 1)}>
                          Down
                        </button>
                        {track.track_id === "image_overlay" || clip.clip_type === "image" ? (
                          <button className="asset-revision-trigger" type="button" onClick={() => onRemoveClip(track.track_id, clip.clip_id)}>
                            Remove
                          </button>
                        ) : null}
                      </div>
                    </article>
                  );
                })}
                {!track.clips.length ? <em>No clips on this track.</em> : null}
              </div>
            </section>
          ))}
        </div>
      ) : state.loading ? (
        <span className="empty-output">Loading timeline...</span>
      ) : (
        <span className="empty-output">No backend timeline is available yet.</span>
      )}

      <section className="final-composition-source-panel">
        <div className="asset-revision-section-heading">Product / Image Sources</div>
        <div className="final-composition-source-list">
          {imageSources.map((source) => {
            const sourcePayload = { ...source, source_asset_id: source.asset_id };
            const asset = finalCompositionSourceAsset(source);
            return (
              <div key={source.source_id || source.asset_id} className="final-composition-source-item">
                {asset ? <NodeAttachmentPreview asset={asset} onOpen={() => onOpenAsset(asset)} /> : null}
                <span>
                  <strong>{finalCompositionSourceLabel(source)}</strong>
                  <em>{source.semantic_type ?? source.source_type ?? "source"} · {source.asset_id}</em>
                </span>
                <button className="asset-revision-trigger" type="button" onClick={() => onAddSourceAsImageClip(sourcePayload)}>
                  Add overlay
                </button>
              </div>
            );
          })}
          {!imageSources.length ? <em>No product or image source from backend.</em> : null}
        </div>
      </section>

      <section className="asset-revision-section final-composition-versioning">
        <div className="asset-revision-section-heading">Current Active</div>
        {activeAsset ? (
          <div className="asset-revision-history-item active">
            <NodeAttachmentPreview asset={activeAsset} onOpen={() => onOpenAsset(activeAsset)} />
            <span>{activeAsset.filename}</span>
            <span>{[activeAsset.version ? `v${activeAsset.version}` : "", activeAsset.semantic_type ?? "final_video", activeAsset.run_id ? `run ${activeAsset.run_id}` : ""].filter(Boolean).join(" · ")}</span>
          </div>
        ) : (
          <em>No active final video yet.</em>
        )}
        <div className="asset-revision-section-heading">Pending Final Candidates</div>
        <div className="asset-revision-candidate-list">
          {pendingFinalCandidates.map((revision) => (
            <LocalRevisionCandidateCard
              key={revision.revision_id || `${revision.updated_at ?? revision.created_at ?? ""}-${revision.status}`}
              revision={revision}
              busy={busyByRevisionId[revision.revision_id]}
              qualityOverrideRevisionId={qualityOverrideRevisionId}
              onAccept={(overrideQualityFailure) => onAcceptCandidate(revision, overrideQualityFailure)}
              onReject={() => onRejectCandidate(revision)}
              onCancelQualityOverride={onCancelQualityOverride}
            />
          ))}
          {!pendingFinalCandidates.length ? <em>No pending final candidates.</em> : null}
        </div>
        <div className="asset-revision-section-heading">Final Video History</div>
        <div className="asset-revision-history-list">
          {finalVideoHistory.map((asset) => (
            <div key={asset.asset_id} className="asset-revision-history-item">
              <NodeAttachmentPreview asset={asset} onOpen={() => onOpenAsset(asset)} />
              <span>{asset.filename}</span>
              <span>{[asset.version ? `v${asset.version}` : "", asset.semantic_type ?? "final_video", asset.run_id ? `run ${asset.run_id}` : ""].filter(Boolean).join(" · ")}</span>
              <button className="asset-revision-trigger" type="button" disabled={isLocalRevisionRunningStatus(revisionState?.status)} onClick={() => onUseVersion(asset)}>
                Use this version
              </button>
            </div>
          ))}
          {!finalVideoHistory.length ? <em>No previous final video versions.</em> : null}
        </div>
      </section>
    </section>
  );
}

function finalCompositionSourceTrack(source: FinalCompositionAvailableSource) {
  const track = source.track_id ?? source.metadata?.track_id;
  return typeof track === "string" ? track : "";
}

function finalCompositionSourceAsset(source: FinalCompositionAvailableSource): UploadedAsset | null {
  if (source.asset) return source.asset;
  return null;
}

function finalCompositionClipAsset(clip: FinalCompositionTimelineClip, sources: FinalCompositionAvailableSource[]) {
  const source = sources.find((item) => item.asset_id === clip.source_asset_id || item.source_id === clip.source_item_id);
  return source ? finalCompositionSourceAsset(source) : null;
}

function finalCompositionTrackLabel(track: FinalCompositionTimelineTrack) {
  if (track.track_id === "video_main") return "video_main";
  if (track.track_id === "image_overlay") return "image_overlay";
  if (track.track_id === "subtitle") return "subtitle";
  if (track.track_id === "audio_bgm") return "audio_bgm";
  return track.track_id;
}

function finalCompositionClipLabel(clip: FinalCompositionTimelineClip, asset: UploadedAsset | null) {
  return asset?.filename || clip.text || clip.source_item_id || clip.source_asset_id || clip.clip_id;
}

function finalCompositionSourceLabel(source: FinalCompositionAvailableSource) {
  return source.display_name || source.asset?.filename || source.source_item_id || source.source_id || source.asset_id;
}
