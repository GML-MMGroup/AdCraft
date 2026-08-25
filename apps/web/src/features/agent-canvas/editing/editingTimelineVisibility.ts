import type { TimelineSegment } from "./editingTimelineMath.ts";

export function frameStripActiveIndices(
  segments: readonly TimelineSegment[],
  visibleStartSeconds: number,
  visibleEndSeconds: number,
): Set<number> {
  const visible = segments
    .map((segment, index) => ({ index, segment }))
    .filter(({ segment }) => (
      segment.timelineEnd > visibleStartSeconds
      && segment.timelineStart < visibleEndSeconds
    ));
  if (!visible.length) return new Set();

  const first = Math.max(0, visible[0]!.index - 1);
  const last = Math.min(segments.length - 1, visible.at(-1)!.index + 1);
  return new Set(Array.from({ length: last - first + 1 }, (_, offset) => first + offset));
}
