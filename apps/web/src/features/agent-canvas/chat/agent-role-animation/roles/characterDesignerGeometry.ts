export type Point = readonly [number, number];
type Cubic = readonly [Point, Point, Point, Point];
type Region = "hair" | "face" | "collar";
export interface CharacterStroke {
  id: string;
  region: Region;
  phase: "construction" | "refinement";
  axis: 0 | 1;
  color: string;
  strokeWidth: number;
  curves: readonly Cubic[];
  angles: readonly [number, number];
}

export const CHARACTER_PARK = { point: [345, 396] as Point, angle: 0 };
export const CHARACTER_STROKES: readonly CharacterStroke[] = [
  { id: "hair", region: "hair", phase: "construction", axis: 0, color: "#FAFBFF", strokeWidth: 8, angles: [35, 65], curves: [
    [[153, 142], [159, 111], [182, 88], [219, 98]],
    [[219, 98], [254, 108], [299, 99], [309, 133]],
  ] },
  { id: "forehead", region: "face", phase: "construction", axis: 1, color: "#FAFBFF", strokeWidth: 8, angles: [-70, -70], curves: [
    [[179, 177], [177, 196], [180, 215], [165, 236]],
    [[165, 236], [163, 240], [160, 243], [159, 246]],
    [[159, 246], [160, 250], [169, 252], [175, 252]],
  ] },
  { id: "chin", region: "face", phase: "construction", axis: 1, color: "#FAFBFF", strokeWidth: 8, angles: [-70, -40], curves: [
    [[175, 252], [178, 261], [172, 272], [180, 283]],
    [[180, 283], [190, 299], [203, 303], [213, 303]],
  ] },
  { id: "jaw", region: "face", phase: "construction", axis: 0, color: "#FAFBFF", strokeWidth: 8, angles: [-40, 10], curves: [
    [[213, 303], [240, 302], [263, 280], [273, 257]],
  ] },
  { id: "left-lapel", region: "collar", phase: "construction", axis: 1, color: "#FAFBFF", strokeWidth: 8, angles: [-65, -40], curves: [
    [[180, 327], [177, 334], [176, 342], [180, 348]],
    [[180, 348], [191, 358], [206, 378], [225, 385]],
  ] },
  { id: "right-lapel", region: "collar", phase: "construction", axis: 0, color: "#FFB323", strokeWidth: 5, angles: [-40, 10], curves: [
    [[225, 385], [246, 380], [275, 362], [286, 347]],
  ] },
  { id: "hair-detail", region: "hair", phase: "refinement", axis: 0, color: "#7899E2", strokeWidth: 6, angles: [0, 15], curves: [
    [[177, 152], [199, 151], [224, 127], [246, 133]],
  ] },
  { id: "jaw-detail", region: "face", phase: "refinement", axis: 0, color: "#7899E2", strokeWidth: 6, angles: [0, 10], curves: [
    [[229, 287], [244, 281], [256, 264], [258, 250]],
  ] },
  { id: "collar-detail", region: "collar", phase: "refinement", axis: 0, color: "#7899E2", strokeWidth: 6, angles: [-60, -60], curves: [
    [[132, 348], [148, 350], [164, 349], [180, 348]],
  ] },
];

export function strokePath(stroke: CharacterStroke): string {
  return `M${stroke.curves[0][0].join(" ")} ${stroke.curves.map(([, a, b, c]) => `C${a.join(" ")} ${b.join(" ")} ${c.join(" ")}`).join(" ")}`;
}

export function sampleStroke(stroke: CharacterStroke): { point: Point; progress: number; angle: number }[] {
  const points: Point[] = [stroke.curves[0][0]];
  for (const [a, b, c, d] of stroke.curves) for (let step = 1; step <= 24; step++) {
    const t = step / 24, u = 1 - t;
    points.push([0, 1].map((axis) => u ** 3 * a[axis] + 3 * u ** 2 * t * b[axis]
      + 3 * u * t ** 2 * c[axis] + t ** 3 * d[axis]) as unknown as Point);
  }
  const distances = [0];
  for (let i = 1; i < points.length; i++) {
    distances.push(distances[i - 1] + Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]));
  }
  const length = distances.at(-1)!;
  return points.map((point, index) => ({
    point, progress: distances[index] / length,
    angle: stroke.angles[0] + (stroke.angles[1] - stroke.angles[0]) * distances[index] / length,
  }));
}

export const CHARACTER_ROUTES = CHARACTER_STROKES.map((stroke) => ({ ...stroke, path: strokePath(stroke), samples: sampleStroke(stroke) }));

// The top edge stays open: the two lapel routes define the neckline without a
// hidden shoulder-to-shoulder segment underneath them.
export const CHARACTER_JACKET_OUTLINE = "M180 327Q153 331 132 348L106 378Q102 389 104 402L110 444C182 449 282 448 350 443L352 399Q354 388 348 378L322 349C310 339 293 330 276 327";
