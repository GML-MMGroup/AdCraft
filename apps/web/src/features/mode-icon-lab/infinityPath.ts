// Shared shape parameters keep the GPU flow on the exact authored silhouette.
const shape = { width: 0.77, asymmetry: 0.14, offset: 0.075, height: 0.34, fullness: 0.16, lift: 0.025, tilt: 0.18 };

export function infinityPoint(t: number) {
  const side = Math.sin(t);
  const x = shape.width * side * (1 + shape.asymmetry * side) - shape.offset;
  const y = shape.height * Math.sin(2 * t) * (1 + shape.fullness * side) + shape.lift * side * side;
  return [x * Math.cos(shape.tilt) - y * Math.sin(shape.tilt),
    x * Math.sin(shape.tilt) + y * Math.cos(shape.tilt)];
}

export const infinityPathShader = `
vec2 infinityPoint(float t) {
  float side = sin(t);
  float x = ${shape.width} * side * (1.0 + ${shape.asymmetry} * side) - ${shape.offset};
  float y = ${shape.height} * sin(2.0 * t) * (1.0 + ${shape.fullness} * side) + ${shape.lift} * side * side;
  return vec2(x * cos(${shape.tilt}) - y * sin(${shape.tilt}),
    x * sin(${shape.tilt}) + y * cos(${shape.tilt}));
}`;
