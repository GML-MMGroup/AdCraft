import { CloseIcon, VideoIcon } from "../../../icons.tsx";
import { mediaUrl } from "../../../api/client.ts";
import type {
  AssetVersionV2,
  V2FinalCompositionTimeline,
  V2FinalTimelineSource,
  V2FinalTimelineRenderStateResponse,
} from "../../../types-v2.ts";
import { usableAssetVersionUrl } from "../../../workflow-v2/selectors.ts";
import { versionedMediaPath } from "../../../workflow/mediaPreview.ts";
import type { V2FinalCompositionIssue } from "./v2FinalCompositionPolicy.ts";

type V2SimpleSequenceCompositionProps = {
  timeline: V2FinalCompositionTimeline;
  sources: V2FinalTimelineSource[];
  staleClipIds: string[];
  missingSourceClipIds: string[];
  finalVideo: AssetVersionV2 | null;
  autoPlayFinalVideo: boolean;
  renderStatus: V2FinalTimelineRenderStateResponse["status"] | null;
  renderProgressPercent: number | null;
  renderIssue: V2FinalCompositionIssue | null;
  rendering: boolean;
  cancellingRender: boolean;
  onExport: () => void;
  onCancel: () => void;
};

export function V2SimpleSequenceComposition({
  timeline,
  sources,
  staleClipIds,
  missingSourceClipIds,
  finalVideo,
  autoPlayFinalVideo,
  renderStatus,
  renderProgressPercent,
  renderIssue,
  rendering,
  cancellingRender,
  onExport,
  onCancel,
}: V2SimpleSequenceCompositionProps) {
  const sourcesByVersion = new Map(sources.map((source) => [source.version_id, source]));
  const stale = new Set(staleClipIds);
  const missing = new Set(missingSourceClipIds);
  const shots = timeline.clips
    .filter((clip) => clip.clip_type === "video" && clip.enabled)
    .sort((left, right) => left.start_time - right.start_time || left.clip_id.localeCompare(right.clip_id));
  const finalVideoUrl = usableAssetVersionUrl(finalVideo);
  const boundedProgress = typeof renderProgressPercent === "number"
    ? Math.min(100, Math.max(0, renderProgressPercent))
    : null;

  return (
    <div className="v2-simple-composition">
      <section className="v2-simple-composition-preview" aria-label="Final video output">
        <div className="v2-simple-composition-preview-stage">
          {finalVideoUrl ? (
            <video
              key={finalVideo?.version_id}
              aria-label="Final video preview"
              src={mediaUrl(finalVideoUrl)}
              poster={finalVideo?.thumbnail_path ? mediaUrl(versionedMediaPath(finalVideo.thumbnail_path, finalVideo)) : undefined}
              controls
              autoPlay={autoPlayFinalVideo}
              playsInline
              preload="metadata"
            />
          ) : (
            <div className="v2-simple-composition-output-empty">
              <VideoIcon />
              <strong>No final video yet</strong>
              <span>Export becomes available when the required shot videos are ready.</span>
            </div>
          )}
        </div>
        <div className="v2-simple-composition-export-row">
          <div className="v2-simple-composition-render-state" role="status" aria-live="polite">
            <strong>{renderIssue?.message ?? renderStatusLabel(renderStatus)}</strong>
            {boundedProgress !== null && rendering ? (
              <>
                <span>{Math.round(boundedProgress)}%</span>
                <progress aria-label="Final video export progress" max={100} value={boundedProgress} />
              </>
            ) : null}
          </div>
          <div className="v2-simple-composition-export-actions">
            {rendering ? (
              <button
                type="button"
                className="v2-simple-composition-cancel"
                aria-label="Cancel export"
                title="Cancel export"
                disabled={cancellingRender || renderStatus === "cancellation_requested"}
                onClick={onCancel}
              >
                <CloseIcon />
              </button>
            ) : null}
            <button
              type="button"
              className="v2-simple-composition-export"
              aria-label="Export video"
              disabled={rendering}
              onClick={onExport}
            >
              <VideoIcon />
              <span>Export video</span>
            </button>
          </div>
        </div>
      </section>

      <section className="v2-simple-composition-sequence" aria-label="Composition inputs">
        <header>
          <div>
            <strong>Shot sequence</strong>
            <span>{shots.length} video{shots.length === 1 ? "" : "s"}</span>
          </div>
          <span>{formatTime(timeline.duration_seconds)}</span>
        </header>
        <ol aria-label="Final video shot order">
          {shots.map((clip, index) => {
            const source = clip.source_version_id ? sourcesByVersion.get(clip.source_version_id) : undefined;
            const health = clipHealth(clip.clip_id, source, stale, missing);
            const previewPath = source?.thumbnail_url ?? source?.public_url;
            return (
              <li key={clip.clip_id}>
                <span className="v2-simple-composition-shot-number">{String(index + 1).padStart(2, "0")}</span>
                <span className="v2-simple-composition-shot-preview">
                  {previewPath ? (
                    source?.thumbnail_url ? (
                      <img
                        src={mediaUrl(versionedMediaPath(previewPath, source))}
                        alt=""
                        loading="lazy"
                        decoding="async"
                      />
                    ) : (
                      <video
                        src={mediaUrl(versionedMediaPath(previewPath, source))}
                        muted
                        playsInline
                        preload="metadata"
                      />
                    )
                  ) : <VideoIcon />}
                </span>
                <span className="v2-simple-composition-shot-copy">
                  <strong>{source?.display_name || `Shot ${index + 1}`}</strong>
                  <span>{formatTime(clip.duration)}</span>
                </span>
                <span className={`v2-simple-composition-health is-${health.toLowerCase()}`}>{health}</span>
              </li>
            );
          })}
          {!shots.length ? (
            <li className="is-empty">
              <span>No successful video segments are available yet.</span>
            </li>
          ) : null}
        </ol>
      </section>
    </div>
  );
}

function clipHealth(
  clipId: string,
  source: V2FinalTimelineSource | undefined,
  stale: Set<string>,
  missing: Set<string>,
) {
  if (missing.has(clipId)) return "Missing";
  if (stale.has(clipId)) return "Updated source";
  if (!source?.public_url) return "Waiting";
  return "Ready";
}

function renderStatusLabel(status: V2FinalTimelineRenderStateResponse["status"] | null) {
  if (status === "queued") return "Export queued";
  if (status === "running") return "Exporting final video";
  if (status === "cancellation_requested") return "Cancellation requested";
  if (status === "completed") return "Final video ready";
  if (status === "failed") return "Export failed";
  if (status === "cancelled") return "Export cancelled";
  return "Ready to export";
}

function formatTime(seconds: number) {
  const safeSeconds = Math.max(0, Number.isFinite(seconds) ? seconds : 0);
  const minutes = Math.floor(safeSeconds / 60);
  const remainder = Math.floor(safeSeconds % 60);
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}
