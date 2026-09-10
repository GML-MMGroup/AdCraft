import { useRef } from "react";
import type {
  AgentRoleMotionProgram,
  AgentRoleMotionState,
  AgentRoleMotionTrack,
} from "../types.ts";
import { useAgentRoleMotion } from "../useAgentRoleMotion.ts";

const LOOP_EASING = "linear";
const INTERVAL_EASING = "cubic-bezier(0.77, 0, 0.175, 1)";
const REEL_STYLE = {
  transformBox: "fill-box",
  transformOrigin: "center",
} as const;

interface FocusBracketDefinition {
  part: string;
  anchor: { x: number; y: number };
  translation: { x: number; y: number };
  path: string;
}

const FOCUS_BRACKETS: readonly FocusBracketDefinition[] = [
  {
    part: "focus-bracket-top-left",
    anchor: { x: 419, y: 305 },
    translation: { x: 12, y: 8 },
    path: "M434 305h-15v15",
  },
  {
    part: "focus-bracket-top-right",
    anchor: { x: 479, y: 305 },
    translation: { x: -12, y: 8 },
    path: "M464 305h15v15",
  },
  {
    part: "focus-bracket-bottom-left",
    anchor: { x: 419, y: 365 },
    translation: { x: 12, y: -8 },
    path: "M419 350v15h15",
  },
  {
    part: "focus-bracket-bottom-right",
    anchor: { x: 479, y: 365 },
    translation: { x: -12, y: -8 },
    path: "M479 350v15h-15",
  },
] as const;

function reelTrack(
  part: "left-reel" | "right-reel",
  rotation: -360 | 360,
  duration: number,
): AgentRoleMotionTrack {
  return {
    part,
    keyframes: [
      { offset: 0, transform: "rotate(0deg)" },
      { offset: 1, transform: `rotate(${rotation}deg)` },
    ],
    options: {
      duration,
      iterations: Infinity,
      easing: LOOP_EASING,
    },
  };
}

function focusBracketTrack(
  definition: FocusBracketDefinition,
): AgentRoleMotionTrack {
  const { x, y } = definition.translation;
  return {
    part: definition.part,
    keyframes: [
      { offset: 0, transform: "none" },
      { offset: 0.08, transform: "none", easing: INTERVAL_EASING },
      { offset: 0.28, transform: `translate(${x}px, ${y}px)` },
      {
        offset: 0.38,
        transform: `translate(${x}px, ${y}px)`,
        easing: INTERVAL_EASING,
      },
      { offset: 0.58, transform: "none" },
      { offset: 0.92, transform: "none" },
      { offset: 1, transform: "none" },
    ],
    options: {
      duration: 5_600,
      iterations: Infinity,
      easing: LOOP_EASING,
    },
  };
}

export const VIDEO_DIRECTOR_MOTION_PROGRAM: AgentRoleMotionProgram = {
  workingEntryTimeMs: 16,
  working: [
    reelTrack("left-reel", -360, 1_600),
    reelTrack("right-reel", 360, 1_600),
    ...FOCUS_BRACKETS.map(focusBracketTrack),
    {
      part: "lens-focus-pass",
      keyframes: [
        { offset: 0, opacity: 0 },
        { offset: 0.08, opacity: 0, easing: INTERVAL_EASING },
        { offset: 0.28, opacity: 0.62 },
        { offset: 0.38, opacity: 0.62, easing: INTERVAL_EASING },
        { offset: 0.58, opacity: 0 },
        { offset: 0.92, opacity: 0 },
        { offset: 1, opacity: 0 },
      ],
      options: {
        duration: 5_600,
        iterations: Infinity,
        easing: LOOP_EASING,
      },
    },
    {
      part: "record-dot",
      keyframes: [
        { offset: 0, opacity: 0.72 },
        { offset: 0.08, opacity: 0.72, easing: INTERVAL_EASING },
        { offset: 0.2, opacity: 1 },
        { offset: 0.3, opacity: 1, easing: INTERVAL_EASING },
        { offset: 0.44, opacity: 0.72 },
        { offset: 0.92, opacity: 0.72 },
        { offset: 1, opacity: 0.72 },
      ],
      options: {
        duration: 5_600,
        iterations: Infinity,
        easing: LOOP_EASING,
      },
    },
    {
      part: "directing-pen",
      keyframes: [
        { offset: 0, transform: "none" },
        { offset: 0.08, transform: "none", easing: INTERVAL_EASING },
        {
          offset: 0.3,
          transform: "translate(8px, -8px) rotate(-2deg)",
          easing: INTERVAL_EASING,
        },
        { offset: 0.46, transform: "translate(16px, -16px) rotate(-4deg)" },
        {
          offset: 0.56,
          transform: "translate(16px, -16px) rotate(-4deg)",
          easing: INTERVAL_EASING,
        },
        {
          offset: 0.78,
          transform: "translate(8px, -8px) rotate(-2deg)",
          easing: INTERVAL_EASING,
        },
        { offset: 0.92, transform: "none" },
        { offset: 1, transform: "none" },
      ],
      options: {
        duration: 2_800,
        iterations: Infinity,
        easing: LOOP_EASING,
      },
    },
  ],
  waiting: [
    reelTrack("left-reel", -360, 4_800),
    reelTrack("right-reel", 360, 4_800),
    {
      part: "record-dot",
      keyframes: [
        { offset: 0, opacity: 0.72 },
        { offset: 0.1, opacity: 0.72, easing: INTERVAL_EASING },
        { offset: 0.4, opacity: 0.9 },
        { offset: 0.6, opacity: 0.9, easing: INTERVAL_EASING },
        { offset: 0.9, opacity: 0.72 },
        { offset: 1, opacity: 0.72 },
      ],
      options: {
        duration: 4_800,
        iterations: Infinity,
        easing: LOOP_EASING,
      },
    },
  ],
};

interface VideoDirectorAnimationProps {
  motionState: AgentRoleMotionState;
}

interface ReelProps {
  part: "left-reel" | "right-reel";
  cx: number;
  cy: number;
  markerAngle: number;
}

function Reel({ part, cx, cy, markerAngle }: ReelProps) {
  const markerRadians = markerAngle * Math.PI / 180;
  const marker = {
    x: cx + Math.cos(markerRadians) * 33,
    y: cy + Math.sin(markerRadians) * 33,
  };
  return (
    <g
      data-part={part}
      data-reel-center-x={cx}
      data-reel-center-y={cy}
      style={REEL_STYLE}
    >
      <circle
        data-reel-rim="true"
        cx={cx}
        cy={cy}
        r="51"
        fill="#17202C"
        fillOpacity="0.2"
        stroke="#FAFBFF"
        strokeWidth="7"
      />
      {[0, 120, 240].map((angle) => {
        const radians = angle * Math.PI / 180;
        return (
          <line
            key={angle}
            data-reel-spoke="true"
            x1={cx + Math.cos(radians) * 13}
            y1={cy + Math.sin(radians) * 13}
            x2={cx + Math.cos(radians) * 38}
            y2={cy + Math.sin(radians) * 38}
            stroke="#7899E2"
            strokeLinecap="round"
            strokeWidth="7"
          />
        );
      })}
      <circle
        cx={cx}
        cy={cy}
        r="13"
        fill="#17202C"
        stroke="#FAFBFF"
        strokeWidth="6"
      />
      <circle
        data-reel-marker="true"
        cx={marker.x}
        cy={marker.y}
        r="7"
        fill="#FFB323"
      />
    </g>
  );
}

export default function VideoDirectorAnimation({
  motionState,
}: VideoDirectorAnimationProps) {
  const rootRef = useRef<SVGSVGElement>(null);
  useAgentRoleMotion(
    rootRef,
    motionState,
    VIDEO_DIRECTOR_MOTION_PROGRAM,
  );

  return (
    <svg
      ref={rootRef}
      viewBox="0 0 512 512"
      aria-hidden="true"
      data-agent-role="video-director"
      xmlns="http://www.w3.org/2000/svg"
    >
      <g data-part="base">
        <path
          d="M70 162V92c0-14 10-24 24-24h62M442 162V92c0-14-10-24-24-24h-62M70 410v34c0 14 10 24 24 24h62M442 410v34c0 14-10 24-24 24h-62"
          fill="none"
          stroke="#FFB323"
          strokeLinecap="square"
          strokeWidth="8"
        />
        <g data-camera-body="true">
          <rect
            x="157"
            y="270"
            width="220"
            height="134"
            rx="4"
            fill="#17202C"
            fillOpacity="0.22"
            stroke="#FAFBFF"
            strokeWidth="8"
          />
          <rect
            x="197"
            y="292"
            width="122"
            height="72"
            fill="none"
            stroke="#7899E2"
            strokeWidth="7"
          />
          <path
            d="M216 313h68M216 342h68"
            fill="none"
            stroke="#FAFBFF"
            strokeLinecap="round"
            strokeWidth="6"
          />
          <path
            d="M305 312h25M305 342h25"
            fill="none"
            stroke="#7899E2"
            strokeDasharray="8 9"
            strokeLinecap="round"
            strokeWidth="7"
          />
          <path
            d="M157 283 145 277v111l12-7M145 291l-20-10v100l20-10M125 298l-25-11v86l25-11"
            fill="#17202C"
            fillOpacity="0.18"
            stroke="#FAFBFF"
            strokeLinejoin="round"
            strokeWidth="7"
          />
          <rect
            x="210"
            y="404"
            width="114"
            height="27"
            rx="3"
            fill="#17202C"
            stroke="#FAFBFF"
            strokeWidth="7"
          />
          <path
            d="m230 431-31 56m48-56v56m39-56v56m18-56 31 56M161 487h212"
            fill="none"
            stroke="#FFB323"
            strokeLinecap="square"
            strokeWidth="7"
          />
        </g>
      </g>

      <Reel part="left-reel" cx={218} cy={203} markerAngle={210} />
      <Reel part="right-reel" cx={315} cy={203} markerAngle={28} />

      <g data-part="lens">
        <path
          d="M377 289 505 260v144l-128-32Z"
          fill="#17202C"
          fillOpacity="0.2"
          stroke="#FAFBFF"
          strokeLinejoin="round"
          strokeWidth="8"
        />
        <polygon
          data-lens-aperture="true"
          points="419,315 479,301 479,369 419,355"
          fill="#17202C"
          stroke="#7899E2"
          strokeLinejoin="round"
          strokeWidth="7"
        />
        <g data-part="lens-focus-pass" opacity="0">
          <polygon
            points="427,319 471,309 471,361 427,351"
            fill="none"
            stroke="#AFC7F8"
            strokeLinejoin="round"
            strokeWidth="6"
          />
        </g>
      </g>

      <g data-part="focus-brackets">
        {FOCUS_BRACKETS.map(({ part, anchor, path }) => (
          <g
            key={part}
            data-part={part}
            data-focus-anchor-x={anchor.x}
            data-focus-anchor-y={anchor.y}
            style={{
              transformBox: "view-box",
              transformOrigin: `${anchor.x}px ${anchor.y}px`,
            }}
          >
            <path
              d={path}
              fill="none"
              stroke="#FAFBFF"
              strokeLinecap="square"
              strokeLinejoin="round"
              strokeWidth="6"
            />
          </g>
        ))}
      </g>

      <g data-part="record-indicator">
        <circle
          data-record-housing="true"
          cx="475"
          cy="132"
          r="24"
          fill="#17202C"
          fillOpacity="0.18"
          stroke="#FAFBFF"
          strokeOpacity="0.42"
          strokeWidth="5"
        />
        <g data-part="record-dot" opacity="0.72">
          <circle cx="475" cy="132" r="15" fill="#FFB323" />
        </g>
      </g>

      <g data-part="directing-path">
        <polyline
          data-directing-route="true"
          points="360,245 368,237 376,229 384,221 392,213"
          fill="none"
          stroke="#7899E2"
          strokeDasharray="4 12"
          strokeLinecap="round"
          strokeWidth="7"
        />
      </g>
      <g
        data-part="directing-pen"
        data-pen-tip-x="360"
        data-pen-tip-y="245"
        style={{
          transformBox: "view-box",
          transformOrigin: "360px 245px",
        }}
      >
        <path
          d="m360 245 7-18 31-31 14 14-31 31-21 4Z"
          fill="#FAFBFF"
          stroke="#17202C"
          strokeLinejoin="round"
          strokeWidth="4"
        />
        <path
          d="m388 206 14-14 14 14-14 14Z"
          fill="#FFB323"
          stroke="#FAFBFF"
          strokeLinejoin="round"
          strokeWidth="4"
        />
        <path
          d="m360 245 10-4-7-7Z"
          fill="#FFB323"
        />
      </g>
    </svg>
  );
}
