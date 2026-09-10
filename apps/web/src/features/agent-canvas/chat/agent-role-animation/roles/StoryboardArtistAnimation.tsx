import { useId, useRef, type ReactNode } from "react";
import type {
  AgentRoleMotionProgram,
  AgentRoleMotionState,
  AgentRoleMotionTrack,
} from "../types.ts";
import { useAgentRoleMotion } from "../useAgentRoleMotion.ts";

const LOOP_EASING = "linear";
const LOCAL_TARGET_STYLE = {
  transformBox: "fill-box",
  transformOrigin: "center",
} as const;

const PANEL_PLACEMENTS = [
  { id: "panel-1", x: 68, y: 62 },
  { id: "panel-2", x: 208, y: 62 },
  { id: "panel-3", x: 348, y: 62 },
  { id: "panel-4", x: 68, y: 200 },
  { id: "panel-5", x: 208, y: 200 },
  { id: "panel-6", x: 348, y: 200 },
  { id: "panel-7", x: 68, y: 338 },
  { id: "panel-8", x: 208, y: 338 },
  { id: "panel-9", x: 348, y: 338 },
] as const;

const PANEL_WINDOWS = [
  { start: 0.020, peakStart: 0.040, peakEnd: 0.100, end: 0.135 },
  { start: 0.125, peakStart: 0.145, peakEnd: 0.205, end: 0.240 },
  { start: 0.230, peakStart: 0.250, peakEnd: 0.310, end: 0.345 },
  { start: 0.335, peakStart: 0.355, peakEnd: 0.415, end: 0.450 },
  { start: 0.440, peakStart: 0.460, peakEnd: 0.520, end: 0.555 },
  { start: 0.545, peakStart: 0.565, peakEnd: 0.625, end: 0.660 },
  { start: 0.650, peakStart: 0.670, peakEnd: 0.730, end: 0.765 },
  { start: 0.755, peakStart: 0.775, peakEnd: 0.835, end: 0.870 },
  { start: 0.860, peakStart: 0.880, peakEnd: 0.940, end: 0.975 },
] as const;

const ACTION_GESTURES = [
  { panel: "panel-2", index: 1, transform: "translate(0px, -14px) rotate(-5deg)" },
  { panel: "panel-3", index: 2, transform: "translate(12px, -9px) rotate(-5deg)" },
  { panel: "panel-6", index: 5, transform: "translate(14px, -6px) rotate(-5deg)" },
  { panel: "panel-9", index: 8, transform: "translate(12px, -10px) rotate(5deg)" },
] as const;

function panelEmphasisTrack(
  part: string,
  index: number,
): AgentRoleMotionTrack {
  const window = PANEL_WINDOWS[index];
  const peakOpacity = 0.88;
  if (index === PANEL_WINDOWS.length - 1) {
    return {
      part,
      keyframes: [
        { offset: 0, opacity: peakOpacity },
        { offset: 0.02, opacity: peakOpacity },
        { offset: 0.04, opacity: 0 },
        { offset: window.start, opacity: 0 },
        { offset: window.peakStart, opacity: peakOpacity },
        { offset: window.peakEnd, opacity: peakOpacity },
        { offset: window.end, opacity: peakOpacity },
        { offset: 0.98, opacity: peakOpacity },
        { offset: 1, opacity: peakOpacity },
      ],
      options: {
        duration: 3_600,
        iterations: Infinity,
        easing: LOOP_EASING,
      },
    };
  }
  return {
    part,
    keyframes: [
      { offset: 0, opacity: 0 },
      { offset: 0.02, opacity: 0 },
      { offset: window.start, opacity: 0 },
      { offset: window.peakStart, opacity: peakOpacity },
      { offset: window.peakEnd, opacity: peakOpacity },
      { offset: window.end, opacity: 0 },
      { offset: 0.98, opacity: 0 },
      { offset: 1, opacity: 0 },
    ],
    options: {
      duration: 3_600,
      iterations: Infinity,
      easing: LOOP_EASING,
    },
  };
}

function actionStrokeTrack(
  part: string,
  index: number,
  transform: string,
): AgentRoleMotionTrack {
  const window = PANEL_WINDOWS[index];
  return {
    part,
    keyframes: [
      { offset: 0, opacity: 1, transform: "none" },
      { offset: 0.02, opacity: 1, transform: "none" },
      { offset: window.start, opacity: 1, transform: "none" },
      { offset: window.peakStart, opacity: 1, transform },
      { offset: window.peakEnd, opacity: 1, transform },
      { offset: window.end, opacity: 1, transform: "none" },
      { offset: 0.98, opacity: 1, transform: "none" },
      { offset: 1, opacity: 1, transform: "none" },
    ],
    options: {
      duration: 3_600,
      iterations: Infinity,
      easing: LOOP_EASING,
    },
  };
}

export const STORYBOARD_ARTIST_MOTION_PROGRAM: AgentRoleMotionProgram = {
  workingEntryTimeMs: 216,
  working: [
    ...PANEL_PLACEMENTS.map(({ id }, index) => (
      panelEmphasisTrack(`${id}-emphasis`, index)
    )),
    ...ACTION_GESTURES.map(({ panel, index, transform }) => (
      actionStrokeTrack(`${panel}-action-stroke`, index, transform)
    )),
    ...ACTION_GESTURES.map(({ panel, index, transform }) => (
      actionStrokeTrack(`${panel}-active-action-stroke`, index, transform)
    )),
  ],
  waiting: [],
};

interface PanelContentProps {
  panel: number;
  tone: "base" | "active";
}

function PanelContent({ panel, tone }: PanelContentProps): ReactNode {
  const color = tone === "active" ? "#FFB323" : "#7899E2";
  const contentAttribute = tone === "active"
    ? { "data-active-panel-content": `panel-${panel}` }
    : { "data-panel-content": `panel-${panel}` };
  const actionPart = tone === "active"
    ? `panel-${panel}-active-action-stroke`
    : `panel-${panel}-action-stroke`;
  const common = {
    fill: "none",
    stroke: color,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    strokeWidth: 7,
  };

  switch (panel) {
    case 1:
      return (
        <g {...contentAttribute} data-content-kind="establishing-mountains">
          <circle cx="31" cy="28" r="10" {...common} />
          <polyline points="8,91 35,61 55,80 77,51 109,87" {...common} />
        </g>
      );
    case 2:
      return (
        <g {...contentAttribute} data-content-kind="seated-conversation">
          <circle cx="39" cy="32" r="11" {...common} />
          <path d="M35 45c-6 5-8 15-8 27" {...common} />
          <g
            data-part={actionPart}
            style={LOCAL_TARGET_STYLE}
          >
            <polyline
              data-action-geometry="true"
              points="30,53 48,60 51,83"
              {...common}
            />
            <polyline
              data-action-geometry="true"
              points="48,60 66,73 87,73"
              {...common}
            />
          </g>
        </g>
      );
    case 3:
      return (
        <g {...contentAttribute} data-content-kind="running-action">
          <circle cx="71" cy="23" r="8" fill={color} />
          <path d="M55 65l17 13-7 22M72 78l20 9" {...common} />
          <g
            data-part={actionPart}
            style={LOCAL_TARGET_STYLE}
          >
            <polyline
              data-action-geometry="true"
              points="64,45 54,66 36,71"
              {...common}
            />
            <polyline
              data-action-geometry="true"
              points="63,44 81,54 93,38"
              {...common}
            />
          </g>
        </g>
      );
    case 4:
      return (
        <g {...contentAttribute} data-content-kind="profile-closeup">
          <circle cx="52" cy="34" r="12" {...common} />
          <path d="m48 47-10 23-10 29M42 60l24 12M45 67l18 31" {...common} />
        </g>
      );
    case 5:
      return (
        <g {...contentAttribute} data-content-kind="focal-landscape">
          <circle cx="88" cy="31" r="11" fill={color} />
          <polyline points="9,91 40,58 61,79 91,44 109,68" {...common} />
        </g>
      );
    case 6:
      return (
        <g {...contentAttribute} data-content-kind="front-character">
          <circle cx="58" cy="32" r="11" {...common} />
          <path d="M58 45v51M42 57v39M74 57v39M42 57l16-10" {...common} />
          <g
            data-part={actionPart}
            style={LOCAL_TARGET_STYLE}
          >
            <polyline
              data-action-geometry="true"
              points="58,47 74,57 89,78"
              {...common}
            />
          </g>
        </g>
      );
    case 7:
      return (
        <g {...contentAttribute} data-content-kind="direction-arrow">
          <path
            d="M9 94c20-20 40-31 63-42l12-16 15-9-5 17 11 4-14 15-15 4C56 80 33 89 9 94Z"
            fill={color}
            fillOpacity="0.12"
            stroke={color}
            strokeLinejoin="round"
            strokeWidth="6"
          />
          <path d="m52 69 15-8 6-10" {...common} strokeWidth="4" />
        </g>
      );
    case 8:
      return (
        <g {...contentAttribute} data-content-kind="blocking-steps">
          <path d="M25 96V72h26V53h25V27h19v69Z" {...common} />
          <path d="M25 72h26v24M51 53h25v43M76 27h19" {...common} strokeWidth="4" />
        </g>
      );
    case 9:
      return (
        <g {...contentAttribute} data-content-kind="walking-exit">
          <circle cx="57" cy="31" r="11" {...common} />
          <path d="M51 69l21 10 11 18M52 54l22 9" {...common} />
          <g
            data-part={actionPart}
            style={LOCAL_TARGET_STYLE}
          >
            <polyline
              data-action-geometry="true"
              points="54,44 51,69 37,97"
              {...common}
            />
          </g>
        </g>
      );
    default:
      return null;
  }
}

interface StoryboardArtistAnimationProps {
  motionState: AgentRoleMotionState;
}

export default function StoryboardArtistAnimation({
  motionState,
}: StoryboardArtistAnimationProps) {
  const rootRef = useRef<SVGSVGElement>(null);
  const instanceId = useId().replaceAll(":", "");
  const panelClipId = (panelId: string): string => (
    `${instanceId}-storyboard-${panelId}`
  );
  useAgentRoleMotion(
    rootRef,
    motionState,
    STORYBOARD_ARTIST_MOTION_PROGRAM,
  );

  return (
    <svg
      ref={rootRef}
      viewBox="0 0 512 512"
      aria-hidden="true"
      data-agent-role="storyboard-artist"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        {PANEL_PLACEMENTS.map(({ id }) => (
          <clipPath
            key={id}
            id={panelClipId(id)}
            data-panel-clip={id}
          >
            <rect x="4" y="4" width="112" height="104" rx="2" />
          </clipPath>
        ))}
      </defs>

      <g data-part="base">
        {PANEL_PLACEMENTS.map(({ id, x, y }, index) => {
          const frame = (
            <>
              <rect
                data-panel-frame="true"
                x="2"
                y="2"
                width="116"
                height="106"
                rx="3"
                fill="#17202C"
                fillOpacity="0.16"
                stroke={motionState !== "working" && index === 4
                  ? "#FFB323"
                  : "#FAFBFF"}
                strokeLinejoin="round"
                strokeWidth="7"
              />
              <PanelContent panel={index + 1} tone="base" />
            </>
          );
          return (
            <g
              key={id}
              data-part={`${id}-cell`}
              data-panel-cell={id}
              transform={`translate(${x} ${y})`}
            >
              {index === 4
                ? <g data-part="center-panel">{frame}</g>
                : frame}
            </g>
          );
        })}
      </g>

      <g data-part="pose-advance" />

      <g data-part="panel-sequence">
        {PANEL_PLACEMENTS.map(({ id, x, y }, index) => (
          <g
            key={id}
            data-emphasis-owner={id}
            transform={`translate(${x} ${y})`}
          >
            <g
              data-part={`${id}-emphasis`}
              data-sequence-marker="true"
              opacity={motionState === "working" && index === 8 ? "0.88" : "0"}
              style={LOCAL_TARGET_STYLE}
            >
              <rect
                data-active-panel-frame="true"
                x="2"
                y="2"
                width="116"
                height="106"
                rx="3"
                fill="none"
                stroke="#FFB323"
                strokeWidth="7"
              />
              <g
                data-active-content-clip={id}
                clipPath={`url(#${panelClipId(id)})`}
              >
                <PanelContent panel={index + 1} tone="active" />
              </g>
            </g>
          </g>
        ))}
      </g>

    </svg>
  );
}
