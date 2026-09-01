import { ViewportPortal } from "@xyflow/react";

import type { FrozenCanvasEdgeSnapshot } from "./frozenCanvasEdges.ts";

type FrozenCanvasEdgesOverlayProps = {
  snapshots: readonly FrozenCanvasEdgeSnapshot[];
};

export function FrozenCanvasEdgesOverlay({ snapshots }: FrozenCanvasEdgesOverlayProps) {
  if (!snapshots.length) return null;

  return (
    <ViewportPortal>
      <svg
        className="agent-canvas-frozen-edges"
        aria-hidden="true"
        focusable="false"
        width="100%"
        height="100%"
        overflow="visible"
      >
        {snapshots.map((snapshot) => (
          <g
            key={snapshot.id}
            dangerouslySetInnerHTML={{ __html: snapshot.markup }}
          />
        ))}
      </svg>
    </ViewportPortal>
  );
}
