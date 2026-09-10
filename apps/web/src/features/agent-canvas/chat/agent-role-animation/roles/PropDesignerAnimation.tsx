import { useId, useRef } from "react";
import type {
  AgentRoleMotionProgram,
  AgentRoleMotionState,
} from "../types.ts";
import { useAgentRoleMotion } from "../useAgentRoleMotion.ts";

const LOOP_EASING = "cubic-bezier(0.77, 0, 0.175, 1)";
const MOVING_PART_STYLE = {
  transformBox: "fill-box",
  transformOrigin: "center",
} as const;
const HANGING_PART_STYLE = {
  transformBox: "fill-box",
  transformOrigin: "top center",
} as const;

function guideTrack(
  part: string,
  axis: "X" | "Y",
  activeOffset: number,
): AgentRoleMotionProgram["working"][number] {
  const rest = `translate${axis}(0px)`;
  const drawn = `translate${axis}(18px)`;
  return {
    part,
    keyframes: [
      { offset: 0, opacity: 0, transform: rest },
      { offset: activeOffset - 0.06, opacity: 0, transform: rest },
      { offset: activeOffset, opacity: 0.84, transform: drawn },
      { offset: activeOffset + 0.08, opacity: 0.84, transform: drawn },
      { offset: activeOffset + 0.16, opacity: 0, transform: rest },
      { offset: 0.94, opacity: 0, transform: rest },
      { offset: 1, opacity: 0, transform: rest },
    ],
    options: {
      duration: 3_600,
      iterations: Infinity,
      easing: LOOP_EASING,
    },
  };
}

export const PROP_DESIGNER_MOTION_PROGRAM: AgentRoleMotionProgram = {
  workingEntryTimeMs: 1_296,
  working: [
    guideTrack("guide-active-horizontal", "X", 0.18),
    guideTrack("guide-active-vertical", "Y", 0.42),
    guideTrack("guide-active-cross", "X", 0.66),
    {
      part: "pull-chain",
      keyframes: [
        { offset: 0, transform: "translateY(0px)" },
        { offset: 0.1, transform: "translateY(0px)" },
        { offset: 0.16, transform: "translateY(22px)" },
        { offset: 0.2, transform: "translateY(22px)" },
        { offset: 0.28, transform: "translateY(8px)" },
        { offset: 0.34, transform: "translateY(0px)" },
        { offset: 0.94, transform: "translateY(0px)" },
        { offset: 1, transform: "translateY(0px)" },
      ],
      options: {
        duration: 7_200,
        iterations: Infinity,
        easing: LOOP_EASING,
      },
    },
    {
      part: "shade-light",
      keyframes: [
        { offset: 0, opacity: 0 },
        { offset: 0.2, opacity: 0 },
        { offset: 0.24, opacity: 0.68 },
        { offset: 0.82, opacity: 0.68 },
        { offset: 0.9, opacity: 0 },
        { offset: 0.94, opacity: 0 },
        { offset: 1, opacity: 0 },
      ],
      options: {
        duration: 7_200,
        iterations: Infinity,
        easing: LOOP_EASING,
      },
    },
    {
      part: "tassels",
      keyframes: [
        { offset: 0, transform: "rotate(0deg)" },
        { offset: 0.2, transform: "rotate(0deg)" },
        { offset: 0.22, transform: "rotate(4deg)" },
        { offset: 0.26, transform: "rotate(-2deg)" },
        { offset: 0.3, transform: "rotate(1deg)" },
        { offset: 0.38, transform: "rotate(0deg)" },
        { offset: 0.94, transform: "rotate(0deg)" },
        { offset: 1, transform: "rotate(0deg)" },
      ],
      options: {
        duration: 7_200,
        iterations: Infinity,
        easing: LOOP_EASING,
      },
    },
  ],
  waiting: [
    {
      part: "shade-light",
      keyframes: [
        { offset: 0, opacity: 0.68 },
        { offset: 0.1, opacity: 0.68 },
        { offset: 0.9, opacity: 0.68 },
        { offset: 1, opacity: 0.68 },
      ],
      options: {
        duration: 4_800,
        iterations: Infinity,
        easing: LOOP_EASING,
      },
    },
    {
      part: "guide-active-vertical",
      keyframes: [
        { offset: 0, opacity: 0, transform: "translateY(0px)" },
        { offset: 0.12, opacity: 0, transform: "translateY(0px)" },
        { offset: 0.48, opacity: 0.58, transform: "translateY(12px)" },
        { offset: 0.6, opacity: 0.58, transform: "translateY(12px)" },
        { offset: 0.9, opacity: 0, transform: "translateY(0px)" },
        { offset: 1, opacity: 0, transform: "translateY(0px)" },
      ],
      options: {
        duration: 4_800,
        iterations: Infinity,
        easing: LOOP_EASING,
      },
    },
  ],
};

interface PropDesignerAnimationProps {
  motionState: AgentRoleMotionState;
}

export default function PropDesignerAnimation({
  motionState,
}: PropDesignerAnimationProps) {
  const rootRef = useRef<SVGSVGElement>(null);
  const instanceId = useId().replaceAll(":", "");
  const shadeClipId = `${instanceId}-prop-shade-interior`;
  const horizontalGuideClipId = `${instanceId}-prop-guide-horizontal`;
  const verticalGuideClipId = `${instanceId}-prop-guide-vertical`;
  const crossGuideClipId = `${instanceId}-prop-guide-cross`;
  useAgentRoleMotion(rootRef, motionState, PROP_DESIGNER_MOTION_PROGRAM);

  return (
    <svg
      ref={rootRef}
      viewBox="0 0 512 512"
      aria-hidden="true"
      data-agent-role="prop-designer"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <clipPath id={shadeClipId} clipPathUnits="userSpaceOnUse">
          <polygon points="225,139 300,139 357,178 397,280 376,305 337,296 290,310 239,310 194,295 151,309 130,283 171,185" />
        </clipPath>
        <clipPath id={horizontalGuideClipId} clipPathUnits="userSpaceOnUse">
          <rect x="292" y="114" width="76" height="20" />
        </clipPath>
        <clipPath id={verticalGuideClipId} clipPathUnits="userSpaceOnUse">
          <rect x="420" y="180" width="20" height="90" />
        </clipPath>
        <clipPath id={crossGuideClipId} clipPathUnits="userSpaceOnUse">
          <rect x="398" y="232" width="72" height="20" />
        </clipPath>
      </defs>

      <g data-part="blueprint">
        <path
          d="M209 392V53h173l89 92v247H322"
          fill="#17202C"
          fillOpacity="0.14"
          stroke="#82A4EB"
          strokeLinejoin="round"
          strokeWidth="8"
        />
        <path
          data-fold="true"
          d="M382 53v92h89"
          fill="#253143"
          fillOpacity="0.34"
          stroke="#92AFF0"
          strokeLinejoin="round"
          strokeWidth="7"
        />
        <g data-part="blueprint-guides">
          <path
            d="M278 126h112M430 164v248"
            fill="none"
            stroke="#7899E2"
            strokeDasharray="7 18"
            strokeLinecap="round"
            strokeWidth="5"
          />
          <path
            d="M397 242h66m-33-33v66"
            fill="none"
            stroke="#7899E2"
            strokeLinecap="round"
            strokeWidth="5"
          />
          <g clipPath={`url(#${horizontalGuideClipId})`}>
            <g
              data-part="guide-active-horizontal"
              opacity={0}
              style={MOVING_PART_STYLE}
            >
              <line
                x1="270"
                x2="342"
                y1="124"
                y2="124"
                stroke="#C9D8F7"
                strokeLinecap="round"
                strokeWidth="7"
              />
            </g>
          </g>
          <g clipPath={`url(#${verticalGuideClipId})`}>
            <g
              data-part="guide-active-vertical"
              opacity={0}
              style={MOVING_PART_STYLE}
            >
              <line
                x1="430"
                x2="430"
                y1="160"
                y2="230"
                stroke="#C9D8F7"
                strokeLinecap="round"
                strokeWidth="7"
              />
            </g>
          </g>
          <g clipPath={`url(#${crossGuideClipId})`}>
            <g
              data-part="guide-active-cross"
              opacity={0}
              style={MOVING_PART_STYLE}
            >
              <line
                x1="382"
                x2="442"
                y1="242"
                y2="242"
                stroke="#C9D8F7"
                strokeLinecap="round"
                strokeWidth="7"
              />
            </g>
          </g>
        </g>
      </g>

      <path
        d="M142 54c4 17 10 24 27 28-17 4-23 11-27 28-4-17-10-24-27-28 17-4 23-11 27-28Z"
        fill="#FFB323"
        stroke="#FAFBFF"
        strokeLinejoin="round"
        strokeWidth="4"
      />

      <g data-part="lamp-body" transform="translate(0 -20) scale(.9 1)">
        <g
          data-part="shade-light"
          clipPath={`url(#${shadeClipId})`}
          opacity={0}
          style={MOVING_PART_STYLE}
        >
          <rect
            x="104"
            y="120"
            width="314"
            height="208"
            fill="#FFB323"
            fillOpacity="0.5"
          />
        </g>

        <g data-part="shade">
          <path
            d="M224 140c-27 8-43 25-54 51l-38 82c-7 15-1 29 14 35 18 7 38-1 48-16 7 18 27 25 45 17 13 17 37 19 51 0 18 9 39 2 47-15 10 15 31 22 47 12 14-8 18-22 11-37l-38-82c-11-25-28-42-56-49"
            fill="#17202C"
            fillOpacity="0.14"
            stroke="#FAFBFF"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="10"
          />
          <ellipse
            cx="263"
            cy="143"
            rx="39"
            ry="11"
            fill="#17202C"
            fillOpacity="0.26"
            stroke="#FAFBFF"
            strokeWidth="8"
          />
          <path
            d="m225 158-31 134m64-137-19 154m57-151-6 151m38-137 9 122m17-98 31 91"
            fill="none"
            stroke="#7899E2"
            strokeLinecap="round"
            strokeWidth="8"
          />
          <path
            d="M200 171 215 188m78-20 14 18m34 5 13 18"
            fill="none"
            stroke="#A9BEF2"
            strokeLinecap="round"
            strokeWidth="6"
          />
        </g>

        <g data-part="trim">
          <path
            d="M134 278c16 18 42 20 60 14 14 15 31 22 45 17 15 13 36 15 51 0 17 8 36 2 47-15 19 12 42 7 58-11"
            fill="none"
            stroke="#FAFBFF"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="9"
          />
          <path
            d="M154 273c10 8 21 9 31 5m36 15c8 5 15 6 23 3m65 1c8 0 15-4 22-11m28-4c7 5 14 5 21 1"
            fill="none"
            stroke="#C4D4F5"
            strokeLinecap="round"
            strokeWidth="4"
          />
        </g>

        <g data-part="stand">
          <path
            d="M263 325v90"
            fill="none"
            stroke="#FAFBFF"
            strokeLinecap="round"
            strokeWidth="10"
          />
          <path
            d="M225 450h76"
            fill="none"
            stroke="#A7BDF0"
            strokeLinecap="round"
            strokeWidth="7"
          />
        </g>

        <g data-part="tassels" style={HANGING_PART_STYLE}>
          <path
            d="M248 312h30l-4 22-11 8-11-8-4-22Z"
            fill="#17202C"
            fillOpacity="0.2"
            stroke="#FAFBFF"
            strokeLinejoin="round"
            strokeWidth="7"
          />
          <path
            d="M255 340c0 15-4 27-11 39-7 11-9 20 3 28 9 6 23 6 32 0 12-8 10-17 3-28-7-12-11-24-11-39"
            fill="#17202C"
            fillOpacity="0.16"
            stroke="#FAFBFF"
            strokeLinejoin="round"
            strokeWidth="9"
          />
        </g>

        <g data-part="pull-chain" style={HANGING_PART_STYLE}>
          <path
            d="M347 308v70"
            fill="none"
            stroke="#FFB323"
            strokeDasharray="8 10"
            strokeLinecap="round"
            strokeWidth="7"
          />
          <circle
            cx="347"
            cy="390"
            r="11"
            fill="#17202C"
            fillOpacity="0.26"
            stroke="#FFB323"
            strokeWidth="7"
          />
        </g>

        <g data-part="base">
          <ellipse
            cx="263"
            cy="430"
            rx="85"
            ry="23"
            fill="#17202C"
            fillOpacity="0.2"
            stroke="#FAFBFF"
            strokeWidth="9"
          />
          <path
            d="M131 465 176 444h174l46 21v35H131v-35Z"
            fill="#202937"
            fillOpacity="0.34"
            stroke="#84A6EC"
            strokeLinejoin="round"
            strokeWidth="8"
          />
          <path
            d="M181 438c24 14 138 14 164 0v12c-30 13-137 13-164 0v-12Z"
            fill="#FFB323"
            fillOpacity="0.62"
            stroke="#FFB323"
            strokeLinejoin="round"
            strokeWidth="6"
          />
        </g>
      </g>
    </svg>
  );
}
