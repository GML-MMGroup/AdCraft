import { useId, useRef } from "react";
import type { AgentRoleMotionState } from "../types.ts";
import { useAgentRoleMotion } from "../useAgentRoleMotion.ts";
import { SCRIPT_WRITER_MOTION_PROGRAM, SCRIPT_WRITING_ROWS } from "./scriptWriterMotion.ts";
export { SCRIPT_WRITER_MOTION_PROGRAM } from "./scriptWriterMotion.ts";
const VIEWBOX_MOTION_STYLE = {
  transformBox: "view-box",
  transformOrigin: "center",
} as const;

interface ScriptWriterAnimationProps {
  motionState: AgentRoleMotionState;
}

export default function ScriptWriterAnimation({
  motionState,
}: ScriptWriterAnimationProps) {
  const rootRef = useRef<SVGSVGElement>(null);
  const instanceId = useId().replaceAll(":", "");
  const viewportId = `${instanceId}-script-viewport`;
  const rowMaskIds = SCRIPT_WRITING_ROWS.map((_, index) => (
    `${instanceId}-script-row-${index + 1}`
  ));
  useAgentRoleMotion(rootRef, motionState, SCRIPT_WRITER_MOTION_PROGRAM);

  return (
    <svg
      ref={rootRef}
      viewBox="0 0 512 512"
      aria-hidden="true"
      data-agent-role="script-writer"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <clipPath id={viewportId}>
          <rect x="160" y="210" width="150" height="120" />
        </clipPath>
        {SCRIPT_WRITING_ROWS.map((row, index) => (
          <mask
            key={row.y}
            id={rowMaskIds[index]}
            x="0"
            y="-12"
            width="512"
            height="24"
            maskUnits="userSpaceOnUse"
          >
            <rect
              data-part={`writing-row-${index + 1}`}
              data-motion-measurement="internal-clip"
              x="26"
              y="-12"
              width="144"
              height="24"
              fill="#FFFFFF"
              opacity={index === 3 ? 0 : 1}
              transform={`translate(${index === 3 ? 0 : row.width} 0)`}
              style={VIEWBOX_MOTION_STYLE}
            />
          </mask>
        ))}
      </defs>

      <g data-part="base">
        <path
          d="M139 66h209l73 73v295c0 16-10 26-26 26H139c-14 0-25-11-25-25V91c0-14 11-25 25-25Z"
          fill="#17202C"
          fillOpacity="0.16"
          stroke="#FAFBFF"
          strokeLinejoin="round"
          strokeWidth="9"
        />
        <path
          d="M348 67v49c0 15 10 24 25 24h47"
          fill="#17202C"
          fillOpacity="0.12"
          stroke="#FAFBFF"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="9"
        />
        <path
          d="M168 156h94M168 188h162"
          fill="none"
          stroke="#7899E2"
          strokeLinecap="round"
          strokeOpacity="0.48"
          strokeWidth="7"
        />
      </g>

      <g data-writing-viewport="true" clipPath={`url(#${viewportId})`}>
        {SCRIPT_WRITING_ROWS.map((row, index) => (
          <g
            key={index}
            data-writing-row={index + 1}
            data-part={`row-position-${index}`}
            style={{ ...VIEWBOX_MOTION_STYLE, transform: `translateY(${row.y}px)` }}
          >
            <g mask={`url(#${rowMaskIds[index]})`} strokeLinecap="round" strokeWidth="8">
              {row.words.map(([start, end]) => (
                <line key={start} data-word="true" x1={170 + start} x2={170 + end} y1="0" y2="0" stroke={row.color} />
              ))}
              <g data-part={`row-highlight-${index}`} opacity="0" stroke="#FFB323">
                {row.words.map(([start, end]) => (
                  <line key={start} x1={170 + start} x2={170 + end} y1="0" y2="0" />
                ))}
              </g>
            </g>
          </g>
        ))}
      </g>

      <g data-part="writing-pen" style={{ ...VIEWBOX_MOTION_STYLE, transformOrigin: "170px 230px" }}>
        <polygon
          points="170,230 181,190 260,96 287,119 197,210"
          fill="#7899E2"
          fillOpacity="0.74"
          stroke="#FAFBFF"
          strokeLinejoin="round"
          strokeWidth="8"
        />
        <path
          d="m193 193 77-87"
          fill="none"
          stroke="#C8D8F7"
          strokeLinecap="round"
          strokeWidth="5"
        />
        <polygon
          points="170,230 181,190 197,210"
          fill="#17202C"
          fillOpacity="0.4"
          stroke="#FFB323"
          strokeLinejoin="round"
          strokeWidth="7"
        />
        <circle cx="170" cy="230" r="4" fill="#FFB323" />
      </g>
    </svg>
  );
}
