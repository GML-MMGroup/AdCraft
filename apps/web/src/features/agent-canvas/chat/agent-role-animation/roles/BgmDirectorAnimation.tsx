import { useId, useRef } from "react";
import type {
  AgentRoleMotionProgram,
  AgentRoleMotionState,
  AgentRoleMotionTrack,
} from "../types.ts";
import { useAgentRoleMotion } from "../useAgentRoleMotion.ts";

const NOTE_PARTS = [
  "score-note-1",
  "score-note-2",
  "score-note-3",
  "score-note-4",
  "score-note-5",
] as const;
const WAVEFORM_START_X = 168;
const WAVEFORM_BASELINE_Y = 220;
const WAVEFORM_TILE_WIDTH = 176;
const WAVEFORM_COPY_COUNT = 3;
const WAVEFORM_CURVES = [
  [179, 220, 184, 217, 192, 220],
  [198, 223, 202, 218, 208, 220],
  [214, 219, 217, 240, 226, 232],
  [234, 225, 236, 180, 246, 220],
  [252, 188, 256, 251, 265, 244],
  [274, 237, 275, 145, 285, 220],
  [292, 170, 298, 263, 307, 249],
  [316, 235, 319, 190, 326, 220],
  [332, 215, 337, 220, 344, 220],
] as const;
const WAVEFORM_PULSE_SAMPLE_COUNT = 24;
const WAVEFORM_PULSE_AMPLITUDE = 0.38;
const WAVEFORM_PULSES = [
  { part: "waveform-pulse-1", startCurve: 0, endCurve: 2, peakSample: 0 },
  { part: "waveform-pulse-2", startCurve: 2, endCurve: 4, peakSample: 5 },
  { part: "waveform-pulse-3", startCurve: 4, endCurve: 6, peakSample: 10 },
  { part: "waveform-pulse-4", startCurve: 6, endCurve: 8, peakSample: 16 },
  { part: "waveform-pulse-5", startCurve: 8, endCurve: 9, peakSample: 20 },
] as const;

function buildWaveformPulsePath(
  startCurve: number,
  endCurve: number,
): string {
  const startX = startCurve === 0
    ? WAVEFORM_START_X
    : WAVEFORM_CURVES[startCurve - 1]![4];
  return Array.from({ length: WAVEFORM_COPY_COUNT }, (_, copyIndex) => {
    const offsetX = copyIndex * WAVEFORM_TILE_WIDTH;
    const curves = WAVEFORM_CURVES.slice(startCurve, endCurve).map((curve) => {
      const [c1x, c1y, c2x, c2y, x, y] = curve;
      return `C${c1x + offsetX} ${c1y} ${c2x + offsetX} ${c2y} ${x + offsetX} ${y}`;
    }).join(" ");
    return `M${startX + offsetX} ${WAVEFORM_BASELINE_Y} ${curves}`;
  }).join(" ");
}

function waveformPulseScale(sample: number, peakSample: number): number {
  const phase = (2 * Math.PI * (sample - peakSample))
    / WAVEFORM_PULSE_SAMPLE_COUNT;
  return Number((1 + WAVEFORM_PULSE_AMPLITUDE * Math.cos(phase)).toFixed(3));
}

function waveformPulseTransform(sample: number, peakSample: number): string {
  return `scaleY(${waveformPulseScale(sample, peakSample)})`;
}

const WAVEFORM_PULSE_ARTWORK = WAVEFORM_PULSES.map((pulse) => ({
  ...pulse,
  path: buildWaveformPulsePath(pulse.startCurve, pulse.endCurve),
  initialTransform: waveformPulseTransform(0, pulse.peakSample),
}));

const MOTION_OPTIONS = {
  duration: 3_000,
  iterations: Infinity,
  easing: "linear",
} as const;
const NOTE_STYLE = {
  transformBox: "fill-box",
  transformOrigin: "center",
  opacity: 0.78,
} as const;
const WAVEFORM_LAYER_STYLE = {
  transform: `translateX(-${WAVEFORM_TILE_WIDTH}px)`,
  transformBox: "view-box",
  transformOrigin: "0 0",
} as const;
const WAVEFORM_PULSE_STYLE = {
  transformBox: "view-box",
  transformOrigin: `0px ${WAVEFORM_BASELINE_Y}px`,
} as const;

function scoreNoteTrack(
  part: typeof NOTE_PARTS[number],
  start: number,
): AgentRoleMotionTrack {
  const peak = Number((start + 0.06).toFixed(2));
  const end = Number((start + 0.12).toFixed(2));
  return {
    part,
    keyframes: [
      { offset: 0, opacity: 0.78, transform: "translateY(0px)" },
      {
        offset: start,
        opacity: 0.78,
        transform: "translateY(0px)",
      },
      {
        offset: peak,
        opacity: 1,
        transform: "translateY(-12px)",
        easing: "cubic-bezier(0.22, 1, 0.36, 1)",
      },
      {
        offset: end,
        opacity: 0.78,
        transform: "translateY(0px)",
        easing: "cubic-bezier(0.4, 0, 0.2, 1)",
      },
      { offset: 1, opacity: 0.78, transform: "translateY(0px)" },
    ],
    options: MOTION_OPTIONS,
  };
}

const waveformStaticTrack: AgentRoleMotionTrack = {
  part: "waveform-static",
  keyframes: [
    { offset: 0, opacity: 0 },
    { offset: 1, opacity: 0 },
  ],
  options: MOTION_OPTIONS,
};

const waveformStripTrack: AgentRoleMotionTrack = {
  part: "waveform-strip",
  keyframes: [
    { offset: 0, opacity: 1, transform: "translateX(-176px)" },
    { offset: 1, opacity: 1, transform: "translateX(0px)" },
  ],
  options: MOTION_OPTIONS,
};

function waveformPulseTrack(
  pulse: typeof WAVEFORM_PULSES[number],
): AgentRoleMotionTrack {
  return {
    part: pulse.part,
    keyframes: Array.from(
      { length: WAVEFORM_PULSE_SAMPLE_COUNT + 1 },
      (_, sample) => ({
        offset: sample / WAVEFORM_PULSE_SAMPLE_COUNT,
        transform: waveformPulseTransform(sample, pulse.peakSample),
      }),
    ),
    options: MOTION_OPTIONS,
  };
}

export const BGM_DIRECTOR_MOTION_PROGRAM: AgentRoleMotionProgram = {
  workingEntryTimeMs: 0,
  working: [
    waveformStaticTrack,
    waveformStripTrack,
    ...WAVEFORM_PULSES.map(waveformPulseTrack),
    scoreNoteTrack("score-note-1", 0.12),
    scoreNoteTrack("score-note-2", 0.27),
    scoreNoteTrack("score-note-3", 0.42),
    scoreNoteTrack("score-note-4", 0.57),
    scoreNoteTrack("score-note-5", 0.72),
  ],
  waiting: [],
};

interface BgmDirectorAnimationProps {
  motionState: AgentRoleMotionState;
}

interface ScoreNoteProps {
  part: typeof NOTE_PARTS[number];
  cx: number;
  cy: number;
  stem: "up" | "down";
}

function ScoreNote({ part, cx, cy, stem }: ScoreNoteProps) {
  const stemX = stem === "up" ? cx + 12 : cx - 12;
  const stemEnd = stem === "up" ? cy - 62 : cy + 62;
  const flag = stem === "up"
    ? `M${stemX} ${stemEnd}c23 7 24 24 4 34`
    : `M${stemX} ${stemEnd}c-23-7-24-24-4-34`;

  return (
    <g data-part={part} style={NOTE_STYLE}>
      <ellipse
        data-note-head="true"
        cx={cx}
        cy={cy}
        rx="15"
        ry="10"
        fill="#7899E2"
        stroke="#FAFBFF"
        strokeWidth="3"
        transform={`rotate(-18 ${cx} ${cy})`}
      />
      <line
        data-note-stem="true"
        x1={stemX}
        y1={cy}
        x2={stemX}
        y2={stemEnd}
        stroke="#FAFBFF"
        strokeLinecap="round"
        strokeWidth="6"
      />
      <path
        data-note-flag="true"
        d={flag}
        fill="none"
        stroke="#FAFBFF"
        strokeLinecap="round"
        strokeWidth="6"
      />
    </g>
  );
}

export default function BgmDirectorAnimation({
  motionState,
}: BgmDirectorAnimationProps) {
  const rootRef = useRef<SVGSVGElement>(null);
  const instanceId = useId().replaceAll(":", "");
  const waveformClipId = `${instanceId}-bgm-waveform-window`;
  useAgentRoleMotion(rootRef, motionState, BGM_DIRECTOR_MOTION_PROGRAM);

  return (
    <svg
      ref={rootRef}
      viewBox="0 0 512 512"
      aria-hidden="true"
      data-agent-role="bgm-director"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <clipPath id={waveformClipId} clipPathUnits="userSpaceOnUse">
          <rect
            data-waveform-window="true"
            x="168"
            y="156"
            width="176"
            height="128"
          />
        </clipPath>
      </defs>

      <g data-part="base">
        <path
          d="M60 369h423M60 492h423"
          fill="none"
          stroke="#17202C"
          strokeLinecap="round"
          strokeOpacity="0.22"
          strokeWidth="10"
        />
      </g>

      <g data-part="headphones">
        <path
          d="M109 211C109 114 173 46 256 46s147 68 147 165M128 211c0-79 54-139 128-139s128 60 128 139"
          fill="none"
          stroke="#FAFBFF"
          strokeLinecap="round"
          strokeWidth="8"
        />
        <path
          d="M130 130c5-15 12-28 20-40M362 90c9 13 16 27 21 42"
          fill="none"
          stroke="#7899E2"
          strokeLinecap="round"
          strokeWidth="8"
        />
        <path
          d="M111 204h-5c-20 0-36 17-36 39v9c0 23 16 41 36 41h5M401 204h5c20 0 36 17 36 39v9c0 23-16 41-36 41h-5"
          fill="#17202C"
          fillOpacity="0.16"
          stroke="#FAFBFF"
          strokeWidth="7"
        />
        <rect x="108" y="181" width="43" height="124" rx="20" fill="#17202C" fillOpacity="0.2" stroke="#FAFBFF" strokeWidth="8" />
        <rect x="361" y="181" width="43" height="124" rx="20" fill="#17202C" fillOpacity="0.2" stroke="#FAFBFF" strokeWidth="8" />
        <path d="M119 202v82M393 202v82" fill="none" stroke="#7899E2" strokeLinecap="round" strokeWidth="7" />
      </g>

      <g
        data-part="central-waveform"
        clipPath={`url(#${waveformClipId})`}
      >
        {(["waveform-static", "waveform-strip"] as const).map((part) => (
          <g
            key={part}
            data-part={part}
            data-waveform-tile-width={WAVEFORM_TILE_WIDTH}
            data-waveform-copy-count={WAVEFORM_COPY_COUNT}
            opacity={part === "waveform-static" ? 1 : 0}
            style={WAVEFORM_LAYER_STYLE}
          >
            {WAVEFORM_PULSE_ARTWORK.map((pulse) => (
              <g
                key={pulse.part}
                data-part={part === "waveform-strip" ? pulse.part : undefined}
                data-waveform-pulse="true"
                style={{
                  ...WAVEFORM_PULSE_STYLE,
                  transform: pulse.initialTransform,
                }}
              >
                <path
                  d={pulse.path}
                  fill="none"
                  stroke="#FFB323"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="6"
                />
              </g>
            ))}
          </g>
        ))}
      </g>

      <g data-part="staff">
        {[374, 398, 422, 446, 470].map((y) => (
          <line
            key={y}
            data-staff-line="true"
            x1="58"
            y1={y}
            x2="478"
            y2={y}
            stroke="#7899E2"
            strokeLinecap="square"
            strokeWidth="6"
          />
        ))}
      </g>

      <g data-part="score-notes">
        <ScoreNote part="score-note-1" cx={96} cy={446} stem="up" />
        <ScoreNote part="score-note-2" cx={178} cy={422} stem="down" />
        <ScoreNote part="score-note-3" cx={260} cy={434} stem="up" />
        <ScoreNote part="score-note-4" cx={342} cy={458} stem="up" />
        <ScoreNote part="score-note-5" cx={424} cy={438} stem="up" />
      </g>

      <g
        data-part="baton"
        data-baton-pivot-x="438"
        data-baton-pivot-y="340"
      >
        <line data-baton-axis="true" x1="443" y1="320" x2="494" y2="153" stroke="#FAFBFF" strokeLinecap="round" strokeWidth="8" />
        <line data-baton-handle="true" x1="438" y1="340" x2="447" y2="309" stroke="#FFB323" strokeLinecap="round" strokeWidth="17" />
        <line x1="441" y1="330" x2="447" y2="309" stroke="#7899E2" strokeLinecap="round" strokeWidth="6" />
      </g>
    </svg>
  );
}
