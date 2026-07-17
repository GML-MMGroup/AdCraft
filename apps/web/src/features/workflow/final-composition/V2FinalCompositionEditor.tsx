import { DndContext, PointerSensor, useDraggable, useDroppable, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { mediaUrl } from "../../../api/client.ts";
import { AssetsIcon, DocumentIcon, ImageIcon, PlayIcon, PlusIcon, SaveIcon, TrashIcon, VideoIcon } from "../../../icons.tsx";
import type { V2FinalCompositionTimeline, V2FinalTimelineClip, V2FinalTimelineSource, V2TimelineTrackType } from "../../../types-v2.ts";
import { versionedMediaPath } from "../../../workflow/mediaPreview.ts";
import { AssetLibraryPicker } from "../assets/AssetLibraryPanels.tsx";
import { v2TimelineDuration } from "./v2TimelineModel.ts";
import { useV2FinalCompositionEditor } from "./useV2FinalCompositionEditor.ts";

const PIXELS_PER_SECOND = 52;

export function V2FinalCompositionEditor({
  workflowId,
  active,
  onWorkflowRefresh,
}: {
  workflowId: string;
  active: boolean;
  onWorkflowRefresh: (workflowId: string) => Promise<unknown> | unknown;
}) {
  const editor = useV2FinalCompositionEditor({ workflowId, active, onWorkflowRefresh });
  const [libraryType, setLibraryType] = useState<"video" | "audio" | null>(null);
  const sources = useMemo(() => editor.sources.filter((source) => source.media_type !== "image" || source.public_url), [editor.sources]);

  if (!active) return null;
  return (
    <section className="v2-composition-editor" aria-label="Final Composition editor">
      <header className="v2-composition-editor-toolbar">
        <div>
          <strong>Final Composition</strong>
          <span>{editor.draft ? `${editor.draft.aspect_ratio} · ${editor.draft.resolution.width}x${editor.draft.resolution.height} · ${editor.draft.fps} fps` : "Loading timeline"}</span>
        </div>
        <div className="v2-composition-toolbar-actions">
          <IconButton label="Refresh timeline" onClick={() => void editor.load({ preserveDraft: true })} disabled={editor.loading}>↻</IconButton>
          <IconButton label="Save timeline" onClick={() => void editor.save()} disabled={!editor.isDirty || editor.saving}><SaveIcon /></IconButton>
          <IconButton label="Render final video" onClick={() => void editor.render()} disabled={!editor.draft || editor.saving || editor.rendering}><PlayIcon /></IconButton>
        </div>
      </header>
      {editor.error ? <p className="v2-composition-feedback is-error">{editor.error}</p> : null}
      {editor.externalUpdate ? <p className="v2-composition-feedback">A newer saved timeline is available. Your local edits remain unchanged until you refresh or save.</p> : null}
      {editor.loading && !editor.draft ? <p className="v2-composition-feedback">Loading Final Composition timeline...</p> : null}
      {editor.draft ? (
        <div className="v2-composition-editor-layout">
          <aside className="v2-composition-source-panel" aria-label="Timeline media">
            <div className="v2-composition-panel-heading"><strong>Media</strong><span>{sources.length}</span></div>
            <div className="v2-composition-source-actions">
              <IconButton label="Import a video from Asset Library" onClick={() => setLibraryType("video")}><VideoIcon /></IconButton>
              <IconButton label="Import BGM from Asset Library" onClick={() => setLibraryType("audio")}><AssetsIcon /></IconButton>
            </div>
            <div className="v2-composition-source-list">
              {sources.map((source) => <SourceCard key={`${source.asset_id}-${source.version_id}`} source={source} onAdd={() => editor.addSource(source)} />)}
              {!sources.length ? <span className="v2-composition-empty">No timeline-ready media yet.</span> : null}
            </div>
          </aside>
          <div className="v2-composition-editor-main">
            <V2CompositionPreview timeline={editor.draft} sources={editor.sources} playheadSeconds={editor.playheadSeconds} onPlayheadChange={editor.setPlayheadSeconds} selectedClipId={editor.selectedClipId} onSelectClip={editor.setSelectedClipId} />
            <V2TimelineTracks timeline={editor.draft} selectedClipId={editor.selectedClipId} playheadSeconds={editor.playheadSeconds} onSelectClip={editor.setSelectedClipId} onPlayheadChange={editor.setPlayheadSeconds} onMoveClip={editor.moveClip} onSplitClip={editor.splitClip} onUpdateTrack={editor.updateTrack} />
          </div>
          <V2ClipInspector clip={editor.selectedClip} onUpdateClip={editor.updateClip} onSetAudio={editor.setClipAudio} onSetColor={editor.setClipColor} onSplit={editor.splitClip} onRemove={editor.removeClip} onAddTrack={editor.addTrack} onAddSubtitle={editor.addSubtitle} />
        </div>
      ) : null}
      {libraryType ? (
        <AssetLibraryPicker
          selectedEntities={[]}
          lockedEntityType={libraryType === "audio" ? "bgm" : "video_clip"}
          selectionMode="single"
          onClose={() => setLibraryType(null)}
          onToggle={(entity) => {
            const assetId = entity.asset_ids?.[0] ?? entity.assets?.[0]?.asset_id;
            if (!assetId) return;
            void editor.importLibrarySource({ entityId: entity.entity_id, assetId, mediaType: libraryType }).then((source) => {
              if (source) setLibraryType(null);
            });
          }}
        />
      ) : null}
    </section>
  );
}

function V2CompositionPreview({ timeline, sources, playheadSeconds, onPlayheadChange, selectedClipId, onSelectClip }: { timeline: V2FinalCompositionTimeline; sources: V2FinalTimelineSource[]; playheadSeconds: number; onPlayheadChange: (value: number) => void; selectedClipId: string | null; onSelectClip: (value: string | null) => void }) {
  const videos = useRef(new Map<string, HTMLVideoElement>());
  const activeClips = useMemo(() => activeVisualClips(timeline, playheadSeconds), [playheadSeconds, timeline]);
  const activeClip = activeClips.at(-1) ?? null;
  const source = activeClip ? sources.find((item) => item.asset_id === activeClip.source_asset_id && item.version_id === activeClip.source_version_id) : null;
  const duration = Math.max(v2TimelineDuration(timeline), 0.01);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    activeClips.forEach((clip) => {
      const element = videos.current.get(clip.clip_id);
      if (!element) return;
      const localTime = Math.max(0, playheadSeconds - clip.start_time + (clip.trim_in ?? 0));
      if (Math.abs(element.currentTime - localTime) > 0.25) element.currentTime = localTime;
    });
  }, [activeClips, playheadSeconds]);

  useEffect(() => {
    if (!playing || activeClips.some((clip) => sources.some((item) => item.asset_id === clip.source_asset_id && item.version_id === clip.source_version_id && item.media_type === "video"))) return;
    const frame = window.setInterval(() => onPlayheadChange(Math.min(duration, playheadSeconds + 0.04)), 40);
    return () => window.clearInterval(frame);
  }, [activeClips, duration, onPlayheadChange, playheadSeconds, playing, sources]);

  useEffect(() => {
    if (playheadSeconds >= duration && playing) setPlaying(false);
  }, [duration, playheadSeconds, playing]);

  return (
    <section className="v2-composition-preview" aria-label="Composition preview">
      <div className="v2-composition-preview-stage" style={{ aspectRatio: timeline.aspect_ratio.replace(":", " / ") }}>
        {activeClips.map((clip) => {
          const clipSource = sources.find((item) => item.asset_id === clip.source_asset_id && item.version_id === clip.source_version_id);
          if (!clipSource?.public_url) return null;
          const mediaStyle = styleForVisualClip(clip);
          const sourceUrl = mediaUrl(versionedMediaPath(clipSource.public_url, clipSource));
          return clipSource.media_type === "video" ? <video key={clip.clip_id} ref={(element) => { if (element) videos.current.set(clip.clip_id, element); else videos.current.delete(clip.clip_id); }} src={sourceUrl} muted playsInline preload="metadata" style={mediaStyle} onTimeUpdate={(event) => { if (playing && clip.clip_id === activeClip?.clip_id) onPlayheadChange(Math.min(duration, clip.start_time + event.currentTarget.currentTime - (clip.trim_in ?? 0))); }} /> : <img key={clip.clip_id} src={sourceUrl} alt={clipSource.display_name} style={mediaStyle} />;
        })}
        {!activeClips.length ? <span className="v2-composition-preview-empty">Place a video or image on the timeline to preview it.</span> : null}
        {timeline.clips.filter((clip) => clip.clip_type === "subtitle" && clip.enabled && playheadSeconds >= clip.start_time && playheadSeconds <= clip.start_time + clip.duration).map((clip) => <span className="v2-composition-subtitle" key={clip.clip_id}>{clip.text}</span>)}
        <button className="v2-composition-preview-play" type="button" aria-label={playing ? "Pause preview" : "Play preview"} onClick={() => {
          const nextPlaying = !playing;
          videos.current.forEach((element) => {
            if (nextPlaying) void element.play().catch(() => setPlaying(false));
            else element.pause();
          });
          setPlaying(nextPlaying);
          onSelectClip(activeClip?.clip_id ?? selectedClipId);
        }}><PlayIcon /></button>
      </div>
      <div className="v2-composition-transport">
        <input aria-label="Preview playhead" type="range" min="0" max={duration} step="0.01" value={Math.min(playheadSeconds, duration)} onChange={(event) => onPlayheadChange(Number(event.target.value))} />
        <span>{formatTime(playheadSeconds)} / {formatTime(duration)}</span>
      </div>
    </section>
  );
}

function V2TimelineTracks({ timeline, selectedClipId, playheadSeconds, onSelectClip, onPlayheadChange, onMoveClip, onSplitClip, onUpdateTrack }: { timeline: V2FinalCompositionTimeline; selectedClipId: string | null; playheadSeconds: number; onSelectClip: (id: string) => void; onPlayheadChange: (seconds: number) => void; onMoveClip: (clipId: string, trackId: string, startTime: number) => void; onSplitClip: (clipId: string, at: number) => void; onUpdateTrack: (trackId: string, update: { enabled?: boolean }) => void }) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));
  const duration = Math.max(v2TimelineDuration(timeline), 12);
  const sortedTracks = [...timeline.tracks].sort((a, b) => a.order - b.order);
  const handleDragEnd = (event: DragEndEvent) => {
    const source = event.active.data.current;
    const trackId = event.over?.id;
    const targetTrackType = event.over?.data.current?.trackType;
    const targetLocked = event.over?.data.current?.locked;
    if (!source || typeof source.clipId !== "string" || typeof trackId !== "string" || source.clipType !== targetTrackType || targetLocked) return;
    onMoveClip(source.clipId, trackId, Math.max(0, source.startTime + event.delta.x / PIXELS_PER_SECOND));
  };
  return (
    <section className="v2-composition-timeline" aria-label="Timeline editor">
      <div className="v2-composition-timeline-ruler" style={{ width: `${duration * PIXELS_PER_SECOND}px` }} onPointerDown={(event) => { const bounds = event.currentTarget.getBoundingClientRect(); onPlayheadChange(Math.max(0, Math.min(duration, (event.clientX - bounds.left) / PIXELS_PER_SECOND))); }}>
        {Array.from({ length: Math.ceil(duration) + 1 }, (_, second) => <span key={second} style={{ left: `${second * PIXELS_PER_SECOND}px` }}>{second}s</span>)}
      </div>
      <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
        <div className="v2-composition-track-list">
          {sortedTracks.map((track) => <TimelineTrack key={track.track_id} track={track} clips={timeline.clips.filter((clip) => clip.track_id === track.track_id)} selectedClipId={selectedClipId} playheadSeconds={playheadSeconds} duration={duration} onSelectClip={onSelectClip} onSplitClip={onSplitClip} onUpdateTrack={onUpdateTrack} />)}
        </div>
      </DndContext>
    </section>
  );
}

function TimelineTrack({ track, clips, selectedClipId, playheadSeconds, duration, onSelectClip, onSplitClip, onUpdateTrack }: { track: V2FinalCompositionTimeline["tracks"][number]; clips: V2FinalTimelineClip[]; selectedClipId: string | null; playheadSeconds: number; duration: number; onSelectClip: (id: string) => void; onSplitClip: (id: string, at: number) => void; onUpdateTrack: (trackId: string, update: { enabled?: boolean }) => void }) {
  const { setNodeRef, isOver } = useDroppable({ id: track.track_id, data: { trackType: track.track_type, locked: false } });
  return <div className={`v2-composition-timeline-track ${isOver ? "is-over" : ""} ${track.enabled ? "" : "is-disabled"}`}><span className="v2-composition-track-label"><span>{track.track_type}</span><button type="button" title={track.enabled ? "Disable track" : "Enable track"} aria-label={track.enabled ? "Disable track" : "Enable track"} onClick={() => onUpdateTrack(track.track_id, { enabled: !track.enabled })}>{track.enabled ? "◉" : "○"}</button></span><div ref={setNodeRef} className="v2-composition-track-lane" style={{ width: `${duration * PIXELS_PER_SECOND}px` }}><i className="v2-composition-playhead" style={{ left: `${playheadSeconds * PIXELS_PER_SECOND}px` }} />{clips.map((clip) => <TimelineClip key={clip.clip_id} clip={clip} disabled={false} selected={clip.clip_id === selectedClipId} onSelect={onSelectClip} onSplit={onSplitClip} />)}</div></div>;
}

function TimelineClip({ clip, disabled, selected, onSelect, onSplit }: { clip: V2FinalTimelineClip; disabled: boolean; selected: boolean; onSelect: (id: string) => void; onSplit: (id: string, at: number) => void }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: clip.clip_id, disabled, data: { clipId: clip.clip_id, clipType: clip.clip_type, startTime: clip.start_time } });
  const style: CSSProperties = { left: `${clip.start_time * PIXELS_PER_SECOND}px`, width: `${Math.max(36, clip.duration * PIXELS_PER_SECOND)}px`, transform: transform ? `translate3d(${transform.x}px, ${transform.y}px, 0)` : undefined };
  return <button ref={setNodeRef} className={`v2-composition-timeline-clip is-${clip.clip_type} ${selected ? "is-selected" : ""} ${isDragging ? "is-dragging" : ""}`} type="button" style={style} {...listeners} {...attributes} onClick={() => onSelect(clip.clip_id)} onDoubleClick={() => onSplit(clip.clip_id, clip.start_time + clip.duration / 2)} title="Drag to move. Double-click to split."><span>{clip.text || clip.clip_type}</span></button>;
}

function V2ClipInspector({ clip, onUpdateClip, onSetAudio, onSetColor, onSplit, onRemove, onAddTrack, onAddSubtitle }: { clip: V2FinalTimelineClip | null; onUpdateClip: (clipId: string, updater: (clip: V2FinalTimelineClip) => V2FinalTimelineClip) => void; onSetAudio: (clipId: string, update: Record<string, number | boolean>) => void; onSetColor: (clipId: string, update: Record<string, number | string>) => void; onSplit: (clipId: string, at: number) => void; onRemove: (clipId: string) => void; onAddTrack: (type: V2TimelineTrackType) => void; onAddSubtitle: () => void }) {
  return <aside className="v2-composition-inspector" aria-label="Clip inspector"><div className="v2-composition-panel-heading"><strong>Inspector</strong>{clip ? <span>{clip.clip_type}</span> : null}</div>{!clip ? <><p className="v2-composition-empty">Select a clip to edit timing, color, audio, and transforms.</p><TrackButtons onAdd={onAddTrack} onAddSubtitle={onAddSubtitle} /></> : <div className="v2-composition-inspector-fields"><NumericField label="Start" value={clip.start_time} min={0} onChange={(value) => onUpdateClip(clip.clip_id, (current) => ({ ...current, start_time: value }))} /><NumericField label="Duration" value={clip.duration} min={0.01} onChange={(value) => onUpdateClip(clip.clip_id, (current) => ({ ...current, duration: value }))} /><NumericField label="Trim in" value={clip.trim_in ?? 0} min={0} onChange={(value) => onUpdateClip(clip.clip_id, (current) => ({ ...current, trim_in: value }))} /><NumericField label="Trim out" value={clip.trim_out ?? clip.duration} min={0.01} onChange={(value) => onUpdateClip(clip.clip_id, (current) => ({ ...current, trim_out: value }))} />{clip.clip_type === "subtitle" ? <><label className="v2-composition-text-field"><span>Subtitle</span><textarea value={clip.text ?? ""} onChange={(event) => onUpdateClip(clip.clip_id, (current) => ({ ...current, text: event.target.value }))} /></label><SubtitleStyleFields clip={clip} onUpdate={onUpdateClip} /></> : null}{clip.clip_type !== "audio" && clip.clip_type !== "subtitle" ? <ColorFields clip={clip} onSetColor={onSetColor} /> : null}{clip.clip_type === "video" || clip.clip_type === "audio" ? <AudioFields clip={clip} onSetAudio={onSetAudio} /> : null}{clip.clip_type !== "audio" && clip.clip_type !== "subtitle" ? <TransformFields clip={clip} onUpdate={onUpdateClip} /> : null}<div className="v2-composition-inspector-actions"><IconButton label="Split selected clip" onClick={() => onSplit(clip.clip_id, clip.start_time + clip.duration / 2)}><span aria-hidden="true">✂</span></IconButton><IconButton label="Delete selected clip" onClick={() => onRemove(clip.clip_id)}><TrashIcon /></IconButton></div><TrackButtons onAdd={onAddTrack} onAddSubtitle={onAddSubtitle} /></div>}</aside>;
}

function ColorFields({ clip, onSetColor }: { clip: V2FinalTimelineClip; onSetColor: (clipId: string, update: Record<string, number | string>) => void }) { const color = clip.color ?? { preset_id: "none", brightness: 0, contrast: 1, saturation: 1, exposure: 0, temperature: 0, tint: 0, hue: 0 }; return <fieldset className="v2-composition-fieldset"><legend>Color</legend><select value={color.preset_id} onChange={(event) => onSetColor(clip.clip_id, { preset_id: event.target.value })}><option value="none">Neutral</option><option value="warm">Warm</option><option value="cool">Cool</option><option value="high_contrast">High contrast</option><option value="muted">Muted</option></select><RangeField label="Brightness" value={color.brightness} min={-1} max={1} step={0.05} onChange={(value) => onSetColor(clip.clip_id, { brightness: value })} /><RangeField label="Contrast" value={color.contrast} min={0} max={3} step={0.05} onChange={(value) => onSetColor(clip.clip_id, { contrast: value })} /><RangeField label="Saturation" value={color.saturation} min={0} max={3} step={0.05} onChange={(value) => onSetColor(clip.clip_id, { saturation: value })} /><RangeField label="Exposure" value={color.exposure} min={-4} max={4} step={0.1} onChange={(value) => onSetColor(clip.clip_id, { exposure: value })} /><RangeField label="Temperature" value={color.temperature} min={-100} max={100} step={1} onChange={(value) => onSetColor(clip.clip_id, { temperature: value })} /><RangeField label="Tint" value={color.tint} min={-100} max={100} step={1} onChange={(value) => onSetColor(clip.clip_id, { tint: value })} /><RangeField label="Hue" value={color.hue} min={-180} max={180} step={1} onChange={(value) => onSetColor(clip.clip_id, { hue: value })} /></fieldset>; }
function AudioFields({ clip, onSetAudio }: { clip: V2FinalTimelineClip; onSetAudio: (clipId: string, update: Record<string, number | boolean>) => void }) { const audio = clip.audio ?? { volume: 1, muted: false, fade_in_seconds: 0, fade_out_seconds: 0 }; return <fieldset className="v2-composition-fieldset"><legend>Audio</legend><RangeField label="Volume" value={audio.volume} min={0} max={4} step={0.05} onChange={(value) => onSetAudio(clip.clip_id, { volume: value })} /><label className="v2-composition-checkbox"><input type="checkbox" checked={audio.muted} onChange={(event) => onSetAudio(clip.clip_id, { muted: event.target.checked })} /> Mute</label><NumericField label="Fade in" value={audio.fade_in_seconds} min={0} onChange={(value) => onSetAudio(clip.clip_id, { fade_in_seconds: value })} /><NumericField label="Fade out" value={audio.fade_out_seconds} min={0} onChange={(value) => onSetAudio(clip.clip_id, { fade_out_seconds: value })} /></fieldset>; }
function SubtitleStyleFields({ clip, onUpdate }: { clip: V2FinalTimelineClip; onUpdate: (clipId: string, updater: (clip: V2FinalTimelineClip) => V2FinalTimelineClip) => void }) { const subtitleStyle = clip.subtitle_style ?? { font_size: 42, color: "#FFFFFF", position: "bottom_center" as const }; const update = (patch: Partial<typeof subtitleStyle>) => onUpdate(clip.clip_id, (current) => ({ ...current, subtitle_style: { ...subtitleStyle, ...patch } })); return <fieldset className="v2-composition-fieldset"><legend>Subtitle style</legend><NumericField label="Font size" value={subtitleStyle.font_size} min={12} onChange={(value) => update({ font_size: Math.min(96, value) })} /><label className="v2-composition-color-field"><span>Color</span><input type="color" value={subtitleStyle.color} onChange={(event) => update({ color: event.target.value })} /></label><select value={subtitleStyle.position} onChange={(event) => update({ position: event.target.value === "top_center" || event.target.value === "center" ? event.target.value : "bottom_center" })}><option value="bottom_center">Bottom</option><option value="center">Center</option><option value="top_center">Top</option></select></fieldset>; }
function TransformFields({ clip, onUpdate }: { clip: V2FinalTimelineClip; onUpdate: (clipId: string, updater: (clip: V2FinalTimelineClip) => V2FinalTimelineClip) => void }) { const transform = clip.transform ?? { x: 0, y: 0, scale_x: 1, scale_y: 1, rotation_degrees: 0, opacity: 1, fit: "contain" as const }; const update = (patch: Partial<typeof transform>) => onUpdate(clip.clip_id, (current) => ({ ...current, transform: { ...transform, ...patch } })); return <fieldset className="v2-composition-fieldset"><legend>Transform</legend><RangeField label="Scale" value={transform.scale_x} min={0.1} max={4} step={0.05} onChange={(value) => update({ scale_x: value, scale_y: value })} /><RangeField label="X" value={transform.x} min={-1} max={1} step={0.05} onChange={(value) => update({ x: value })} /><RangeField label="Y" value={transform.y} min={-1} max={1} step={0.05} onChange={(value) => update({ y: value })} /><RangeField label="Rotation" value={transform.rotation_degrees} min={-360} max={360} step={1} onChange={(value) => update({ rotation_degrees: value })} /><RangeField label="Opacity" value={transform.opacity} min={0} max={1} step={0.05} onChange={(value) => update({ opacity: value })} /><select value={transform.fit} onChange={(event) => update({ fit: event.target.value === "cover" ? "cover" : "contain" })}><option value="contain">Contain</option><option value="cover">Cover</option></select></fieldset>; }
function SourceCard({ source, onAdd }: { source: V2FinalTimelineSource; onAdd: () => void }) { return <button className="v2-composition-source" type="button" onClick={onAdd}><span className="v2-composition-source-thumb">{source.thumbnail_url || source.public_url ? <img src={mediaUrl(versionedMediaPath(source.thumbnail_url ?? source.public_url, source))} alt="" loading="lazy" decoding="async" /> : source.media_type === "audio" ? <AssetsIcon /> : source.media_type === "image" ? <ImageIcon /> : <VideoIcon />}</span><span><strong>{source.display_name}</strong><em>{source.media_type}{source.duration_seconds ? ` · ${formatTime(source.duration_seconds)}` : ""}</em></span><PlusIcon /></button>; }
function TrackButtons({ onAdd, onAddSubtitle }: { onAdd: (type: V2TimelineTrackType) => void; onAddSubtitle: () => void }) { return <div className="v2-composition-add-track"><span>Add</span><IconButton label="Add video track" onClick={() => onAdd("video")}><VideoIcon /></IconButton><IconButton label="Add audio track" onClick={() => onAdd("audio")}><AssetsIcon /></IconButton><IconButton label="Add image track" onClick={() => onAdd("image")}><ImageIcon /></IconButton><IconButton label="Add subtitle clip" onClick={onAddSubtitle}><DocumentIcon /></IconButton></div>; }
function IconButton({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: React.ReactNode }) { return <button className="v2-composition-icon-button" type="button" aria-label={label} title={label} onClick={onClick} disabled={disabled}>{children}</button>; }
function NumericField({ label, value, min, onChange }: { label: string; value: number; min: number; onChange: (value: number) => void }) { return <label className="v2-composition-number-field"><span>{label}</span><input type="number" min={min} step="0.01" value={Number.isFinite(value) ? value : 0} onChange={(event) => onChange(Math.max(min, Number(event.target.value) || 0))} /></label>; }
function RangeField({ label, value, min, max, step, onChange }: { label: string; value: number; min: number; max: number; step: number; onChange: (value: number) => void }) { return <label className="v2-composition-range-field"><span>{label}<b>{value.toFixed(2)}</b></span><input type="range" min={min} max={max} step={step} value={value} onChange={(event) => onChange(Number(event.target.value))} /></label>; }
function activeVisualClips(timeline: V2FinalCompositionTimeline, time: number) { return [...timeline.clips].filter((clip) => clip.enabled && timeline.tracks.find((track) => track.track_id === clip.track_id)?.enabled !== false && (clip.clip_type === "video" || clip.clip_type === "image") && time >= clip.start_time && time <= clip.start_time + clip.duration).sort((left, right) => trackOrder(timeline, left.track_id) - trackOrder(timeline, right.track_id)); }
function trackOrder(timeline: V2FinalCompositionTimeline, trackId: string) { return timeline.tracks.find((track) => track.track_id === trackId)?.order ?? 0; }
function styleForVisualClip(clip: V2FinalTimelineClip): CSSProperties { const color = clip.color; const transform = clip.transform; return { filter: color ? `brightness(${Math.max(0, 1 + color.brightness + color.exposure / 4)}) contrast(${color.contrast}) saturate(${color.saturation}) hue-rotate(${color.hue}deg)` : undefined, opacity: transform?.opacity ?? 1, objectFit: transform?.fit ?? "contain", transform: `translate(${(transform?.x ?? 0) * 50}%, ${(transform?.y ?? 0) * 50}%) scale(${transform?.scale_x ?? 1}, ${transform?.scale_y ?? 1}) rotate(${transform?.rotation_degrees ?? 0}deg)` }; }
function formatTime(value: number) { const minutes = Math.floor(Math.max(0, value) / 60); const seconds = Math.floor(Math.max(0, value) % 60); return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`; }
