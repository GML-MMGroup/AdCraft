import { useRef } from "react";
import type {
  AgentRoleMotionProgram,
  AgentRoleMotionState,
  AgentRoleMotionTrack,
} from "../types.ts";
import { useAgentRoleMotion } from "../useAgentRoleMotion.ts";

const DASH_OPACITY = 0.58;
const QUICK_MEDIA_CYCLE_MS = 3_600;
const LOCAL_MOTION_STYLE = {
  transformBox: "fill-box",
  transformOrigin: "center",
} as const;

interface DashDefinition {
  part: string;
  start: { x: number; y: number };
  end: { x: number; y: number };
}

const DASHES: readonly DashDefinition[] = [
  { part: "route-dash-1", start: { x: 193, y: 166 }, end: { x: 185, y: 176 } },
  { part: "route-dash-2", start: { x: 175, y: 192 }, end: { x: 168, y: 204 } },
  { part: "route-dash-3", start: { x: 159, y: 222 }, end: { x: 154, y: 236 } },
  { part: "route-dash-4", start: { x: 180, y: 413 }, end: { x: 196, y: 419 } },
  { part: "route-dash-5", start: { x: 219, y: 426 }, end: { x: 237, y: 428 } },
  { part: "route-dash-6", start: { x: 268, y: 429 }, end: { x: 286, y: 425 } },
  { part: "route-dash-7", start: { x: 368, y: 240 }, end: { x: 363, y: 226 } },
  { part: "route-dash-8", start: { x: 354, y: 205 }, end: { x: 347, y: 193 } },
  { part: "route-dash-9", start: { x: 335, y: 176 }, end: { x: 325, y: 167 } },
] as const;

function mediaActivationTrack(
  part: "image-node" | "video-node" | "audio-node",
  window: {
    start: number;
    peakStart: number;
    peakEnd: number;
    end: number;
  },
): AgentRoleMotionTrack {
  return {
    part,
    keyframes: [
      { offset: 0, opacity: 0.68, transform: "none" },
      { offset: 0.04, opacity: 0.68, transform: "none" },
      {
        offset: window.start,
        opacity: 0.68,
        transform: "none",
        easing: "cubic-bezier(0.77, 0, 0.175, 1)",
      },
      {
        offset: window.peakStart,
        opacity: 1,
        transform: "translateY(-8px) scale(1.04)",
      },
      {
        offset: window.peakEnd,
        opacity: 1,
        transform: "translateY(-8px) scale(1.04)",
        easing: "cubic-bezier(0.77, 0, 0.175, 1)",
      },
      { offset: window.end, opacity: 0.68, transform: "none" },
      { offset: 0.96, opacity: 0.68, transform: "none" },
      { offset: 1, opacity: 0.68, transform: "none" },
    ],
    options: {
      duration: QUICK_MEDIA_CYCLE_MS,
      iterations: Infinity,
      easing: "linear",
    },
  };
}

export const QUICK_MEDIA_MOTION_PROGRAM: AgentRoleMotionProgram = {
  workingEntryTimeMs: 160,
  workingTransitionDurationMs: 160,
  working: [
    {
      part: "lightning-active",
      keyframes: [
        { offset: 0, opacity: 0.24, transform: "none" },
        {
          offset: 0.04,
          opacity: 0.24,
          transform: "none",
          easing: "cubic-bezier(0.23, 1, 0.32, 1)",
        },
        {
          offset: 0.12,
          opacity: 1,
          transform: "translateY(-6px) scale(1.04)",
        },
        {
          offset: 0.82,
          opacity: 1,
          transform: "translateY(-6px) scale(1.04)",
          easing: "cubic-bezier(0.77, 0, 0.175, 1)",
        },
        {
          offset: 0.92,
          opacity: 0.42,
          transform: "translateY(-2px) scale(1.01)",
          easing: "cubic-bezier(0.77, 0, 0.175, 1)",
        },
        { offset: 1, opacity: 0.24, transform: "none" },
      ],
      options: {
        duration: QUICK_MEDIA_CYCLE_MS,
        iterations: Infinity,
        easing: "linear",
      },
    },
    mediaActivationTrack("image-node", {
      start: 0.12,
      peakStart: 0.18,
      peakEnd: 0.24,
      end: 0.31,
    }),
    mediaActivationTrack("video-node", {
      start: 0.35,
      peakStart: 0.41,
      peakEnd: 0.47,
      end: 0.54,
    }),
    mediaActivationTrack("audio-node", {
      start: 0.58,
      peakStart: 0.64,
      peakEnd: 0.70,
      end: 0.77,
    }),
  ],
  waiting: [],
};

interface QuickMediaAnimationProps {
  motionState: AgentRoleMotionState;
}

export default function QuickMediaAnimation({
  motionState,
}: QuickMediaAnimationProps) {
  const rootRef = useRef<SVGSVGElement>(null);
  useAgentRoleMotion(rootRef, motionState, QUICK_MEDIA_MOTION_PROGRAM);

  return (
    <svg
      ref={rootRef}
      viewBox="0 0 512 512"
      aria-hidden="true"
      data-agent-role="quick-media"
      xmlns="http://www.w3.org/2000/svg"
    >
      <g data-part="base">
        <ellipse
          cx="256"
          cy="453"
          rx="154"
          ry="13"
          fill="#17202C"
          fillOpacity="0.15"
        />
        <path
          d="M256 74C158 74 79 154 79 252s79 178 177 178 177-80 177-178S354 74 256 74Z"
          fill="none"
          stroke="#17202C"
          strokeOpacity="0.12"
          strokeWidth="8"
        />
      </g>

      <g data-part="direction-arrows">
        <g data-route-from="image" data-route-to="video">
          <path
            d="M196 163c-42 30-65 71-68 117"
            fill="none"
            stroke="#FFB323"
            strokeLinecap="round"
            strokeWidth="8"
          />
          <polygon points="128,292 116,270 140,274" fill="#FFB323" />
        </g>
        <g data-route-from="video" data-route-to="audio">
          <path
            d="M177 412c54 33 127 36 183 3"
            fill="none"
            stroke="#FFB323"
            strokeLinecap="round"
            strokeWidth="8"
          />
          <polygon points="373,406 355,426 351,401" fill="#FFB323" />
        </g>
        <g data-route-from="audio" data-route-to="image">
          <path
            d="M410 280c-2-52-27-96-70-123"
            fill="none"
            stroke="#7899E2"
            strokeLinecap="round"
            strokeWidth="8"
          />
          <polygon points="329,151 353,154 340,174" fill="#7899E2" />
        </g>
      </g>

      <g data-part="route-dashes">
        {DASHES.map((dash) => (
          <g
            key={dash.part}
            data-part={dash.part}
            style={{ ...LOCAL_MOTION_STYLE, opacity: DASH_OPACITY }}
          >
            <line
              x1={dash.start.x}
              y1={dash.start.y}
              x2={dash.end.x}
              y2={dash.end.y}
              stroke="#AFC5F5"
              strokeLinecap="round"
              strokeWidth="7"
            />
          </g>
        ))}
      </g>

      <g
        data-part="image-node"
        data-node-center-x="256"
        data-node-center-y="112"
        style={LOCAL_MOTION_STYLE}
      >
        <rect
          data-node-frame="true"
          x="179"
          y="55"
          width="154"
          height="114"
          rx="16"
          fill="#17202C"
          fillOpacity="0.24"
          stroke="#7899E2"
          strokeWidth="8"
        />
        <g data-static-glyph="true">
          <circle cx="301" cy="89" r="13" fill="#FFB323" />
          <path
            d="m193 151 38-43 30 29 24-22 35 36"
            fill="none"
            stroke="#7899E2"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="9"
          />
          <path
            d="M194 151h126"
            fill="none"
            stroke="#FAFBFF"
            strokeLinecap="round"
            strokeWidth="5"
          />
        </g>
      </g>

      <g
        data-part="video-node"
        data-node-center-x="127"
        data-node-center-y="350"
        style={LOCAL_MOTION_STYLE}
      >
        <rect
          data-node-frame="true"
          x="54"
          y="291"
          width="146"
          height="118"
          rx="18"
          fill="#17202C"
          fillOpacity="0.24"
          stroke="#FAFBFF"
          strokeWidth="8"
        />
        <g data-static-glyph="true">
          <polygon points="108,320 108,380 157,350" fill="#7899E2" />
          <path
            d="m115 329 31 20"
            fill="none"
            stroke="#AFC5F5"
            strokeLinecap="round"
            strokeWidth="5"
          />
        </g>
      </g>

      <g
        data-part="audio-node"
        data-node-center-x="385"
        data-node-center-y="350"
        style={LOCAL_MOTION_STYLE}
      >
        <circle
          data-node-frame="true"
          cx="385"
          cy="350"
          r="68"
          fill="#17202C"
          fillOpacity="0.24"
          stroke="#FAFBFF"
          strokeWidth="8"
        />
        <g data-static-glyph="true">
          <path
            d="M373 364v-54l48-10v52"
            fill="none"
            stroke="#FAFBFF"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="9"
          />
          <path d="m374 326 47-10" stroke="#7899E2" strokeWidth="8" />
          <circle cx="358" cy="366" r="14" fill="#FAFBFF" />
          <circle cx="406" cy="353" r="14" fill="#FAFBFF" />
        </g>
      </g>

      <g data-part="lightning">
        <g
          data-part="lightning-active"
          style={{ ...LOCAL_MOTION_STYLE, opacity: 0.24 }}
        >
          <polygon
            data-lightning-body="true"
            points="284,176 216,292 258,292 224,378 326,258 284,264"
            fill="#FFB323"
          />
          <polygon
            data-lightning-highlight="true"
            points="281,196 231,282 269,282 244,346 306,273 274,278"
            fill="#FFD36C"
            fillOpacity="0.5"
          />
        </g>
      </g>
    </svg>
  );
}
