import { useState } from "react";
import type { EditingVideoEntryV2 } from "../../../types-v2.ts";
import { hasTimelineOverlap, MIN_EDITED_CLIP_SECONDS, roundTimeline, type TimelineSegment } from "./editingTimelineMath.ts";
import { useEditingText } from "./editingMessages.ts";

export function EditingClipTiming({ segment, segments, sourceDuration, timelineDuration, fps, disabled, onUpdate }: {
  segment: TimelineSegment; segments: TimelineSegment[]; sourceDuration: number; timelineDuration: number; fps: number; disabled: boolean;
  onUpdate: (patch: Partial<EditingVideoEntryV2>) => void;
}) {
  const t = useEditingText();
  const [start, setStart] = useState(String(segment.sourceStart));
  const [end, setEnd] = useState(String(segment.sourceEnd));
  const [position, setPosition] = useState(String(segment.timelineStart));
  const [issue, setIssue] = useState<string | null>(null);
  const changed = Number(start) !== segment.sourceStart || Number(end) !== segment.sourceEnd || Number(position) !== segment.timelineStart;
  return <form className="editing-timing" onSubmit={event => {
    event.preventDefault();
    const sourceStart = roundTimeline(Number(start));
    const sourceEnd = roundTimeline(Number(end));
    const timelineStart = roundTimeline(Number(position));
    const duration = sourceEnd - sourceStart;
    const proposed = { ...segment, sourceStart, sourceEnd, timelineStart, timelineEnd: timelineStart + duration };
    if ([start, end, position].some(value => !value.trim() || !Number.isFinite(Number(value))) || sourceStart < 0 || sourceEnd > sourceDuration || duration < Math.min(MIN_EDITED_CLIP_SECONDS, sourceDuration) || timelineStart < 0 || proposed.timelineEnd > timelineDuration + .001 || hasTimelineOverlap([...segments.filter(item => item.referenceId !== segment.referenceId), proposed])) {
      setIssue(t("Keep the range inside the source and timeline, without overlapping another clip.")); return;
    }
    setIssue(null);
    onUpdate({ trim_start_seconds: sourceStart, trim_end_seconds: sourceEnd, timeline_start_seconds: timelineStart });
  }}>
    <h4>{t("Timing")} <span>{t("seconds")}</span></h4>
    <div className="editing-timing__range">
      <label><span>{t("Source in")}</span><input type="number" min="0" max={sourceDuration} step="any" value={start} disabled={disabled} onChange={event => setStart(event.target.value)}/></label>
      <label><span>{t("Source out")}</span><input type="number" min={Math.min(MIN_EDITED_CLIP_SECONDS, sourceDuration)} max={sourceDuration} step="any" value={end} disabled={disabled} onChange={event => setEnd(event.target.value)}/></label>
    </div>
    <label><span>{t("Timeline position")}</span><input type="number" min="0" max={timelineDuration} step={1 / fps} value={position} disabled={disabled} onChange={event => setPosition(event.target.value)}/></label>
    {issue ? <p role="alert">{issue}</p> : null}
    <button type="submit" disabled={disabled || !changed}>{t("Apply timing")}</button>
  </form>;
}
