import { Background, BackgroundVariant } from "@xyflow/react";

const AGENT_CANVAS_GRID_GAP = 24;
const AGENT_CANVAS_GRID_DOT_SIZE = 1.2;

export function AgentCanvasPointerBackgrounds() {
  return (
    <>
      <Background
        id="agent-canvas-base-grid"
        variant={BackgroundVariant.Dots}
        gap={AGENT_CANVAS_GRID_GAP}
        size={AGENT_CANVAS_GRID_DOT_SIZE}
      />
      <Background
        id="agent-canvas-pointer-spotlight"
        className="agent-canvas-pointer-background"
        patternClassName="agent-canvas-pointer-dot"
        variant={BackgroundVariant.Dots}
        gap={AGENT_CANVAS_GRID_GAP}
        size={AGENT_CANVAS_GRID_DOT_SIZE}
        color="var(--agent-canvas-pointer-dot-color)"
        bgColor="transparent"
      />
    </>
  );
}
