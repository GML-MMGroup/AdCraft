import type { AgentRoleMotionProgram, AgentRoleMotionTrack } from "../types.ts";
import { CHARACTER_PARK, CHARACTER_ROUTES, type Point } from "./characterDesignerGeometry.ts";

const DURATION = 4800;
const rounded = (n: number) => Number(n.toFixed(4));
export const characterPenTransform = (point: Point, angle: number) => `translate(${rounded(point[0])}px, ${rounded(point[1])}px) rotate(${rounded(angle)}deg)`;

function createTracks(intro: boolean): AgentRoleMotionTrack[] {
  const tracks = new Map<string, Keyframe[]>();
  const add = (part: string, time: number, frame: Keyframe) => {
    const frames = tracks.get(part) ?? [];
    frames.push({ offset: time / DURATION, ...frame });
    tracks.set(part, frames);
  };
  const pen = (time: number, point: Point, angle: number) => add("design-pencil", time, { transform: characterPenTransform(point, angle), opacity: 1 });
  const reveal = (id: string, axis: number, time: number, coordinate: number, opacity: number) => add(`reveal-${id}`, time, {
    transform: `translate${axis === 0 ? "X" : "Y"}(${rounded(coordinate)}px)`, opacity,
  });
  const highlight = (phase: string, region: string, time: number, opacity: number) => add(`ink-${phase}-${region}`, time, { opacity });
  pen(0, CHARACTER_PARK.point, CHARACTER_PARK.angle);
  for (const route of CHARACTER_ROUTES) {
    const complete = !intro && route.phase === "construction";
    reveal(route.id, route.axis, 0, complete ? 512 : 0, complete ? 1 : 0);
  }
  for (const phase of ["construction", "refinement"]) for (const region of ["hair", "face", "collar"]) highlight(phase, region, 0, 0);

  let current = CHARACTER_PARK;
  if (intro) {
    // A small preparatory lift gives immediate Working feedback while retaining
    // the parked silhouette; the first long travel still starts after 200ms.
    current = { point: [CHARACTER_PARK.point[0], CHARACTER_PARK.point[1] - 3], angle: -2 };
    pen(160, current.point, current.angle);
  }
  // One timing curve over the entire arc: x controls time, y controls travel.
  const travel = (start: number, end: number, point: Point, angle: number) => {
    pen(start, current.point, current.angle);
    for (let step = 1; step <= 16; step++) {
      const s = step / 16, u = 1 - s;
      const time = 3 * u ** 2 * s * 0.77 + 3 * u * s ** 2 * 0.175 + s ** 3;
      const progress = 3 * u * s ** 2 + s ** 3;
      const lift = 12 * Math.sin(Math.PI * progress);
      pen(start + time * (end - start), [
        current.point[0] + (point[0] - current.point[0]) * progress,
        current.point[1] + (point[1] - current.point[1]) * progress - lift,
      ], current.angle + (angle - current.angle) * progress);
    }
    current = { point, angle };
  };

  const phase = intro ? "construction" : "refinement";
  const windows = [
    { region: "hair", lift: intro ? 200 : 0, start: intro ? 450 : 200, end: 1300 },
    { region: "face", lift: 1300, start: 1550, end: 2650 },
    { region: "collar", lift: 2650, start: 2900, end: 4000 },
  ];
  for (const { region, lift, start, end } of windows) {
    const routes = CHARACTER_ROUTES.filter((r) => r.phase === phase && r.region === region);
    const first = routes[0];
    travel(lift, start, first.samples[0].point, first.angles[0]);
    highlight(phase, region, start, 0);
    highlight(phase, region, start, 1);
    const lengths = routes.map((r) => r.samples.reduce((sum, sample, i, samples) => i === 0 ? 0 : sum
      + Math.hypot(sample.point[0] - samples[i - 1].point[0], sample.point[1] - samples[i - 1].point[1]), 0));
    const total = lengths.reduce((a, b) => a + b, 0);
    let elapsed = 0;
    routes.forEach((route, index) => {
      const from = start + (end - start) * elapsed / total;
      const to = start + (end - start) * (elapsed + lengths[index]) / total;
      reveal(route.id, route.axis, from, 0, 0);
      for (const sample of route.samples) {
        const time = from + (to - from) * sample.progress;
        pen(time, sample.point, sample.angle);
        reveal(route.id, route.axis, time, sample.point[route.axis], 1);
      }
      // Extend the mask beyond the finished round cap only once the tip has
      // completed the contour; never expose an unwritten cap before contact.
      reveal(route.id, route.axis, to + 0.01, 512, 1);
      current = { point: route.samples.at(-1)!.point, angle: route.angles[1] };
      elapsed += lengths[index];
    });
    highlight(phase, region, end, 1);
    highlight(phase, region, end + 100, 0);
    if (!intro) for (const route of routes) {
      reveal(route.id, route.axis, end + 100, 512, 1);
      reveal(route.id, route.axis, end + 100, 0, 0);
    }
  }
  travel(4000, 4250, CHARACTER_PARK.point, CHARACTER_PARK.angle);
  return [...tracks].map(([part, keyframes]) => {
    if (keyframes.at(-1)!.offset !== 1) keyframes.push({ ...keyframes.at(-1)!, offset: 1 });
    return { part, keyframes, options: { duration: DURATION, iterations: intro ? 1 : Infinity, easing: "linear", fill: "both" } };
  });
}

export const CHARACTER_DESIGNER_MOTION_PROGRAM: AgentRoleMotionProgram = {
  workingEntryTimeMs: 160,
  workingIntro: createTracks(true),
  working: createTracks(false),
  waiting: [],
};
