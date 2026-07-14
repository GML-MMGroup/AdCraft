import { useCallback, useEffect, useState } from "react";
import { v2Api } from "../../../api/v2Client.ts";
import { ChevronDownIcon, ChevronUpIcon, PlayIcon, SaveIcon, UndoIcon } from "../../../icons.tsx";
import type { V2FinalCompositionTimeline } from "../../../types-v2.ts";

export function V2FinalCompositionTimelineEditor({ workflowId }: { workflowId?: string | null }) {
  const [timeline, setTimeline] = useState<V2FinalCompositionTimeline | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [outputUrl, setOutputUrl] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!workflowId) return;
    setBusy(true);
    try {
      const { timeline: next } = await v2Api.finalCompositionTimeline(workflowId);
      setTimeline(next);
      setDirty(false);
    } finally {
      setBusy(false);
    }
  }, [workflowId]);

  useEffect(() => { void load(); }, [load]);

  const clips = timeline ? [...timeline.clips].filter((clip) => clip.clip_type === "video").sort((a, b) => a.start_time - b.start_time) : [];
  async function save(render = false) {
    if (!workflowId || !timeline || !clips.length) return;
    setBusy(true);
    try {
      const next = dirty
        ? (await v2Api.saveFinalCompositionTimeline(workflowId, { expected_version: timeline.version, timeline })).timeline
        : timeline;
      setTimeline(next);
      setDirty(false);
      if (render) setOutputUrl((await v2Api.renderFinalCompositionTimeline(workflowId, { timeline_id: next.timeline_id, timeline_version: next.version })).public_url ?? null);
    } finally {
      setBusy(false);
    }
  }

  function move(index: number, direction: -1 | 1) {
    if (!timeline || index + direction < 0 || index + direction >= clips.length) return;
    const ordered = [...clips];
    [ordered[index], ordered[index + direction]] = [ordered[index + direction], ordered[index]];
    let start = 0;
    const starts = new Map(ordered.map((clip) => {
      const pair = [clip.clip_id, start] as const;
      start += clip.duration;
      return pair;
    }));
    setTimeline({ ...timeline, clips: timeline.clips.map((clip) => starts.has(clip.clip_id) ? { ...clip, start_time: starts.get(clip.clip_id) ?? 0 } : clip) });
    setDirty(true);
  }

  if (!workflowId) return null;
  return <section className="v2-final-timeline-editor nodrag" aria-label="Final composition editor" onPointerDown={(event) => event.stopPropagation()}>
    <header className="v2-final-timeline-editor-heading">
      <div><strong>Final cut</strong><span>{timeline ? `${clips.length} shots` : "Timeline"}</span></div>
      <div className="v2-final-timeline-editor-actions">
        <Action label="Reload timeline" disabled={busy} onClick={() => void load()}><UndoIcon /></Action>
        <Action label="Save timeline" disabled={busy || !dirty || !clips.length} onClick={() => void save()}><SaveIcon /></Action>
        <Action label="Render final video" disabled={busy || !clips.length} onClick={() => void save(true)}><PlayIcon /></Action>
      </div>
    </header>
    {!timeline ? <span className="v2-final-timeline-state">Loading timeline…</span> : <div className="v2-final-timeline-clip-list">
      {clips.map((clip, index) => <article className="v2-final-timeline-clip" key={clip.clip_id}>
        <span className="v2-final-timeline-clip-index">{index + 1}</span>
        <div className="v2-final-timeline-clip-copy"><strong>{typeof clip.metadata?.shot_index === "number" ? `Shot ${clip.metadata.shot_index}` : `Shot ${index + 1}`}</strong><span>{clip.duration.toFixed(0)}s</span></div>
        <div className="v2-final-timeline-clip-actions">
          <Action label="Move shot earlier" disabled={busy || index === 0} onClick={() => move(index, -1)}><ChevronUpIcon /></Action>
          <Action label="Move shot later" disabled={busy || index === clips.length - 1} onClick={() => move(index, 1)}><ChevronDownIcon /></Action>
        </div>
      </article>)}
      {!clips.length ? <span className="v2-final-timeline-state">Storyboard videos are required before rendering.</span> : null}
    </div>}
    {outputUrl ? <video className="v2-final-timeline-output" src={outputUrl} controls playsInline preload="metadata" /> : null}
  </section>;
}

function Action({ label, disabled, onClick, children }: { label: string; disabled: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button className="v2-final-timeline-icon-button" type="button" aria-label={label} title={label} disabled={disabled} onClick={(event) => { event.stopPropagation(); onClick(); }}>{children}</button>;
}
