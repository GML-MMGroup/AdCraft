import { useId, useRef } from "react";
import type { AgentRoleMotionState } from "../types.ts";
import { useAgentRoleMotion } from "../useAgentRoleMotion.ts";
import { CharacterDesignerArtwork } from "./CharacterDesignerArtwork.tsx";
import { CHARACTER_DESIGNER_MOTION_PROGRAM } from "./characterDesignerMotion.ts";

export { CHARACTER_DESIGNER_MOTION_PROGRAM } from "./characterDesignerMotion.ts";

export default function CharacterDesignerAnimation({ motionState }: { motionState: AgentRoleMotionState }) {
  const rootRef = useRef<SVGSVGElement>(null);
  const id = useId().replaceAll(":", "");
  useAgentRoleMotion(rootRef, motionState, CHARACTER_DESIGNER_MOTION_PROGRAM);
  return (
    <svg ref={rootRef} viewBox="0 0 512 512" aria-hidden="true" data-agent-role="character-designer" xmlns="http://www.w3.org/2000/svg">
      <CharacterDesignerArtwork idPrefix={id} />
    </svg>
  );
}
