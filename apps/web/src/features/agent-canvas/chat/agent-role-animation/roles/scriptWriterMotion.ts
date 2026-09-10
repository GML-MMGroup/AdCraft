import type { AgentRoleMotionProgram, AgentRoleMotionTrack } from "../types.ts";

const MOVE_EASING = "cubic-bezier(0.77, 0, 0.175, 1)";
const INTRO_MS = 3_200;
const ROW_CYCLE_MS = 1_600;
const LOOP_MS = ROW_CYCLE_MS * 4;

const PATTERNS = [
  [[0, 26], [37, 68], [79, 108]],
  [[0, 34], [45, 84], [95, 126]],
  [[0, 22], [33, 58], [69, 96]],
] as const;

export const SCRIPT_WRITING_ROWS = [0, 1, 2, 0].map((pattern, index) => ({
  index,
  y: 230 + index * 40,
  words: PATTERNS[pattern],
  width: PATTERNS[pattern][2][1],
  color: pattern === 1 ? "#F8FAFF" : "#7899E2",
}));

function penTransform(x: number, y: number, angle = 0): string {
  return `translate(${Number(x.toFixed(3))}px, ${Number(y.toFixed(3))}px) rotate(${Number(angle.toFixed(3))}deg)`;
}

function createChoreography(duration: number, intro: boolean): AgentRoleMotionTrack[] {
  const tracks = new Map<string, Keyframe[]>();
  const add = (part: string, time: number, frame: Keyframe): void => {
    const frames = tracks.get(part) ?? [];
    frames.push({ offset: time / duration, ...frame });
    tracks.set(part, frames);
  };
  const pen = (time: number, x: number, y: number, angle = 0): void => {
    add("writing-pen", time, { transform: penTransform(x, y, angle), opacity: 1 });
  };
  const rowPosition = (slot: number, time: number, position: number, easing?: string): void => {
    add(`row-position-${slot}`, time, {
      transform: `translateY(${230 + position * 40}px)`,
      ...(easing ? { easing } : {}),
    });
  };
  const reveal = (slot: number, time: number, x: number, opacity = 1): void => {
    add(`writing-row-${slot + 1}`, time, { transform: `translateX(${x}px)`, opacity });
  };
  const highlight = (slot: number, time: number, opacity: number): void => {
    add(`row-highlight-${slot}`, time, { opacity });
  };

  // All geometry and time points are shared by the pen and ink reveal. Phrase
  // pauses stop both, while travel across whitespace leaves no stray marks.
  const write = (slot: number, start: number, end: number, y: number): void => {
    const words = SCRIPT_WRITING_ROWS[slot].words;
    const xs = [0, words[0][1], words[0][1], words[1][0], words[1][1], words[1][1], words[2][0], words[2][1]];
    const progress = [0, 0.24, 0.30, 0.38, 0.64, 0.70, 0.78, 1];
    // The white mask stays fully transparent until contact: rounded line caps
    // must not leak as bullets at the beginning of unwritten rows.
    reveal(slot, start, 0, 0);
    highlight(slot, start, 1);
    progress.forEach((fraction, index) => {
      const time = start + (end - start) * fraction;
      pen(time, xs[index], y, index === 0 || index === 7 ? 0 : index % 2 ? -1 : 1);
      reveal(slot, time, xs[index]);
    });
    highlight(slot, end, 1);
    highlight(slot, end + 100, 0);
  };

  const returnPen = (start: number, fromX: number, fromY: number, toY: number): void => {
    pen(start, fromX, fromY);
    pen(start + 60, fromX + 2, fromY - 10, -6);
    // Sample both the shallow return arc and MOVE_EASING once. Parameterizing
    // time by the timing curve's x and distance by its y preserves easing
    // across the whole arc, rather than stopping at each sampled segment.
    for (let sample = 1; sample <= 8; sample++) {
      const phase = sample / 8, remaining = 1 - phase;
      const timeProgress = 3 * remaining ** 2 * phase * 0.77 + 3 * remaining * phase ** 2 * 0.175 + phase ** 3;
      const t = 3 * remaining * phase ** 2 + phase ** 3, u = 1 - t;
      const x = u ** 3 * (fromX + 2) + 3 * u ** 2 * t * fromX * 0.65 + 3 * u * t ** 2 * 8;
      const y = u ** 3 * (fromY - 10) + 3 * u ** 2 * t * (fromY - 24)
        + 3 * u * t ** 2 * (toY - 22) + t ** 3 * (toY - 8);
      pen(start + 60 + timeProgress * 180, x, y, -6 + t * 2);
    }
    pen(start + 300, 0, toY);
  };

  pen(0, intro ? 0 : SCRIPT_WRITING_ROWS[2].width, intro ? 0 : 80);
  SCRIPT_WRITING_ROWS.forEach((row) => {
    rowPosition(row.index, 0, row.index);
    reveal(row.index, 0, intro || row.index === 3 ? 0 : row.width, intro || row.index === 3 ? 0 : 1);
    highlight(row.index, 0, 0);
  });

  if (intro) {
    for (let slot = 0; slot < 3; slot++) {
      const start = 100 + slot * 1_020;
      write(slot, start, start + 720, slot * 40);
      if (slot < 2) returnPen(start + 720, SCRIPT_WRITING_ROWS[slot].width, slot * 40, (slot + 1) * 40);
    }
  } else {
    const positions = [0, 1, 2, 3];
    for (let step = 0; step < 4; step++) {
      const start = step * ROW_CYCLE_MS;
      const slot = (step + 3) % 4;
      const previous = (slot + 3) % 4;
      if (positions[slot] === -1) {
        // Duplicate offsets make the offscreen recycle instantaneous. There is
        // no interpolated path through the visible manuscript.
        rowPosition(slot, start, -1);
        rowPosition(slot, start, 3);
        reveal(slot, start, SCRIPT_WRITING_ROWS[slot].width);
        reveal(slot, start, 0, 0);
        positions[slot] = 3;
      }
      positions.forEach((position, index) => {
        rowPosition(index, start + 60, position, MOVE_EASING);
        rowPosition(index, start + 260, position - 1);
        positions[index] = position - 1;
      });
      returnPen(start, SCRIPT_WRITING_ROWS[previous].width, 80, 80);
      write(slot, start + 300, start + 1_300, 80);
      pen(start + ROW_CYCLE_MS, SCRIPT_WRITING_ROWS[slot].width, 80);
    }
    rowPosition(3, duration, -1);
    rowPosition(3, duration, 3);
    reveal(3, duration, SCRIPT_WRITING_ROWS[3].width);
    reveal(3, duration, 0, 0);
  }

  return [...tracks].map(([part, keyframes]) => {
    const last = keyframes.at(-1)!;
    if (last.offset !== 1) keyframes.push({ ...last, offset: 1 });
    return { part, keyframes, options: { duration, iterations: intro ? 1 : Infinity, easing: "linear", fill: "both" } };
  });
}

export const SCRIPT_WRITER_MOTION_PROGRAM: AgentRoleMotionProgram = {
  workingEntryTimeMs: 160,
  workingIntro: createChoreography(INTRO_MS, true),
  working: createChoreography(LOOP_MS, false),
  waiting: [],
};
