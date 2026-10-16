import { infinityPathShader } from "./infinityPath";

export const vertexSource = `
attribute vec2 a_position;
attribute float a_size;
attribute vec4 a_color;
attribute float a_phase;
attribute vec2 a_flow;
uniform vec2 u_scale;
uniform float u_dpr;
uniform float u_time;
uniform float u_intro;
uniform float u_hover;
uniform float u_shape;
uniform float u_motion;
uniform float u_accent;
varying vec4 v_color;
${infinityPathShader}
void main() {
  vec2 p = a_position;
  float entry = 1.0 - pow(1.0 - u_intro, 3.0);
  float light = 1.0;
  vec3 pigment = a_color.rgb;
  float glint = 0.0;
  float accent = 0.0;
  if (u_shape < 0.5) {
    float wing = smoothstep(0.025, 0.22, abs(p.x));
    float angle = (0.16 + 0.10 * sin(u_time * 1.35)
      + u_hover * 0.30 * (0.5 + 0.5 * sin(u_time * 3.2))) * u_motion;
    angle += (1.0 - entry) * 0.48;
    p.x *= mix(1.0, cos(angle), wing);
    p.y += wing * abs(p.x) * sin(angle) * 0.065;
    light += u_hover * 0.18;
    // Sparse cobalt dust follows the wings, leaving the silver structure visible.
    float seed = fract(sin(dot(a_position, vec2(127.1, 311.7))) * 43758.5453);
    float dust = smoothstep(0.55, 0.82, seed);
    float wingLight = 0.5 + 0.5 * sin(abs(a_position.x) * 12.0
      - a_position.y * 7.0 - u_time * 2.2);
    accent = u_accent * wing * dust;
    glint = accent * u_hover * pow(wingLight, 6.0);
    pigment = mix(pigment, vec3(0.025, 0.10, 0.86),
      accent * (0.66 + 0.30 * u_hover));
    pigment = mix(pigment, vec3(0.24, 0.38, 1.0), glint * 0.55);
    light += accent * 0.40 + glint * 1.8;
  } else {
    if (a_flow.x >= 0.0) {
      // Actual point movement, one orbit per six seconds, rather than a light sweep.
      float t = a_flow.x + u_time * 1.04719755;
      vec2 center = infinityPoint(t);
      vec2 tangent = normalize(infinityPoint(t + 0.001) - infinityPoint(t - 0.001));
      float width = (0.014 + 0.019 * pow(sin(t), 2.0)) * (1.0 + 0.28 * sin(t + 0.7));
      vec2 moving = center + vec2(-tangent.y, tangent.x) * a_flow.y * width;
      p = mix(p, moving, u_motion);
      // Gold belongs to the flowing filament; its supporting silhouette stays silver.
      accent = u_accent;
      pigment = mix(a_color.rgb, vec3(0.86, 0.57, 0.18), 0.82 * accent);
      float packet = fract(a_phase * 2.0) - 0.5;
      float pulse = exp(-packet * packet / 0.012);
      glint = accent * pulse * u_hover;
      pigment = mix(pigment, vec3(1.0, 0.86, 0.53), glint * 0.85);
      light = mix(1.0, 1.25 + pulse * (2.0 + u_hover), u_motion);
      vec2 crossing = mix(infinityPoint(a_flow.x), center, u_motion) - infinityPoint(0.0);
      float behind = mix(1.0 - step(0.0, cos(a_flow.x)), 1.0 - step(0.0, cos(t)), u_motion);
      light *= 1.0 - behind * exp(-dot(crossing, crossing) / 0.008) * 0.8;
    } else {
      light = mix(1.0, 0.72, u_motion);
    }
  }
  p *= 0.95 + 0.05 * entry;
  gl_Position = vec4(p * u_scale, 0.0, 1.0);
  gl_PointSize = a_size * (1.0 + accent * 0.25 + glint * 0.75) * u_dpr;
  v_color = vec4(pigment, a_color.a * entry * light);
}`;

export const fragmentSource = `
precision mediump float;
varying vec4 v_color;
void main() {
  float distance = length(gl_PointCoord - vec2(0.5)) * 2.0;
  float alpha = (1.0 - smoothstep(0.15, 1.0, distance)) * v_color.a;
  gl_FragColor = vec4(v_color.rgb, alpha);
}`;
