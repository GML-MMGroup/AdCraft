import { useId, useRef } from "react";
import type {
  AgentRoleMotionProgram,
  AgentRoleMotionState,
} from "../types.ts";
import { useAgentRoleMotion } from "../useAgentRoleMotion.ts";

const CENTERED_MOVING_PART_STYLE = {
  transformBox: "fill-box",
  transformOrigin: "center",
} as const;
const FLASH_EASING = "cubic-bezier(0.23, 1, 0.32, 1)";

export const PRODUCT_DESIGNER_MOTION_PROGRAM: AgentRoleMotionProgram = {
  workingEntryTimeMs: 160,
  working: [
    {
      part: "glass-sweep",
      keyframes: [
        { offset: 0, opacity: 0, transform: "translateX(0px)" },
        { offset: 0.04, opacity: 0.01, transform: "translateX(0px)" },
        { offset: 0.1, opacity: 0.76, transform: "translateX(28px)" },
        { offset: 0.415, opacity: 0.76, transform: "translateX(208px)" },
        { offset: 0.46, opacity: 0, transform: "translateX(228px)" },
        { offset: 0.94, opacity: 0, transform: "translateX(0px)" },
        { offset: 1, opacity: 0, transform: "translateX(0px)" },
      ],
      options: {
        duration: 3_200,
        iterations: Infinity,
        easing: "linear",
      },
    },
    {
      part: "camera-flash",
      keyframes: [
        { offset: 0, opacity: 0, transform: "scale(0.92)" },
        { offset: 0.46, opacity: 0, transform: "scale(0.92)" },
        {
          offset: 0.47,
          opacity: 0.01,
          transform: "scale(0.92)",
          easing: FLASH_EASING,
        },
        { offset: 0.4809375, opacity: 1, transform: "scale(1)" },
        {
          offset: 0.498125,
          opacity: 1,
          transform: "scale(1)",
          easing: FLASH_EASING,
        },
        { offset: 0.52625, opacity: 0.01, transform: "scale(1.28)" },
        { offset: 0.53625, opacity: 0, transform: "scale(1.28)" },
        { offset: 0.94, opacity: 0, transform: "scale(0.92)" },
        { offset: 1, opacity: 0, transform: "scale(0.92)" },
      ],
      options: {
        duration: 3_200,
        iterations: Infinity,
        easing: "linear",
      },
    },
  ],
  waiting: [],
};

interface ProductDesignerAnimationProps {
  motionState: AgentRoleMotionState;
}

export default function ProductDesignerAnimation({
  motionState,
}: ProductDesignerAnimationProps) {
  const rootRef = useRef<SVGSVGElement>(null);
  const clipId = useId().replaceAll(":", "");
  const phoneClipId = `${clipId}-product-phone-surface`;
  useAgentRoleMotion(rootRef, motionState, PRODUCT_DESIGNER_MOTION_PROGRAM);

  return (
    <svg
      ref={rootRef}
      viewBox="0 0 512 512"
      aria-hidden="true"
      data-agent-role="product-designer"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <clipPath id={phoneClipId} clipPathUnits="userSpaceOnUse">
          <path
            d="M246 54 379 77c26 5 42 25 42 52v309c0 39-23 66-57 62l-111-21c-25-5-39-24-39-53V104c0-36 13-55 32-50Z"
            transform="matrix(.84 0 0 .88 18 5)"
          />
        </clipPath>
      </defs>

      <g data-part="base" transform="matrix(.84 0 0 .88 18 5)">
        <path
          d="M267 46 385 69c34 7 56 30 56 65v304c0 45-25 75-64 70l-119-23c-32-6-50-30-50-66V109c0-44 19-70 59-63Z"
          fill="#17202C"
          fillOpacity="0.18"
          stroke="#83A5EC"
          strokeWidth="8"
        />
        <path
          data-phone-body="true"
          d="M248 50 374 74c29 5 47 27 47 58v303c0 43-23 69-57 64l-112-21c-26-5-41-25-41-56V108c0-40 15-64 37-58Z"
          fill="#202733"
          fillOpacity="0.16"
          stroke="#FAFBFF"
          strokeLinejoin="round"
          strokeWidth="9"
        />
        <path
          d="M252 77 373 99c17 3 27 17 27 37v302c0 27-13 43-34 40l-106-20c-18-4-27-17-27-39V113c0-25 7-39 19-36Z"
          fill="none"
          stroke="#FAFBFF"
          strokeOpacity="0.9"
          strokeWidth="5"
        />
        <path
          d="M212 417c1 32 14 53 40 59l112 22c16 2 31-3 41-15"
          fill="none"
          stroke="#D8E3FA"
          strokeLinecap="round"
          strokeWidth="6"
        />
        <path
          d="M421 268v56"
          fill="none"
          stroke="#FAFBFF"
          strokeLinecap="round"
          strokeWidth="7"
        />
        <path
          d="M435 153v62"
          fill="none"
          stroke="#7899E2"
          strokeLinecap="round"
          strokeWidth="5"
        />
      </g>

      <g clipPath={`url(#${phoneClipId})`}>
        <g data-part="glass-sweep" style={CENTERED_MOVING_PART_STYLE}>
          <polygon
            points="84,24 126,24 286,494 244,494"
            fill="#FAFBFF"
            fillOpacity="0.34"
          />
          <polygon
            points="130,24 142,24 302,494 290,494"
            fill="#C8D8F7"
            fillOpacity="0.22"
          />
        </g>
      </g>

      <g data-part="camera-cluster" transform="matrix(.84 0 0 .88 18 5)">
        <path
          d="M250 82 292 90c18 4 29 17 29 35v65c0 22-12 35-30 31l-39-8c-15-3-24-15-24-33v-65c0-22 8-36 22-33Z"
          fill="#202733"
          fillOpacity="0.24"
          stroke="#FAFBFF"
          strokeLinejoin="round"
          strokeWidth="7"
        />
        <ellipse cx="270" cy="119" rx="14" ry="17" fill="#FAFBFF" />
        <ellipse cx="297" cy="148" rx="16" ry="19" fill="#FAFBFF" />
        <ellipse cx="265" cy="177" rx="15" ry="19" fill="#FAFBFF" />
        <ellipse cx="298" cy="199" rx="8" ry="10" fill="#FAFBFF" />
        <g
          data-part="camera-flash"
          style={{ ...CENTERED_MOVING_PART_STYLE, opacity: 0 }}
        >
          <circle
            data-flash-halo="true"
            cx="298"
            cy="199"
            r="46"
            fill="#FFD26A"
            fillOpacity="0.18"
          />
          <path
            data-flash-star="true"
            d="m298 160 7 30 33 9-33 9-7 30-7-30-33-9 33-9 7-30Z"
            fill="#FFFFFF"
          />
          <path
            data-flash-rays="true"
            d="M298 146v-14M298 266v-14M245 199h-14M365 199h-14M260 161l-10-10M346 247l-10-10M336 161l10-10M250 247l10-10"
            fill="none"
            stroke="#FFD26A"
            strokeLinecap="round"
            strokeWidth="5"
          />
          <circle
            data-flash-core="true"
            cx="298"
            cy="199"
            r="10"
            fill="#FFFFFF"
          />
        </g>
      </g>

    </svg>
  );
}
