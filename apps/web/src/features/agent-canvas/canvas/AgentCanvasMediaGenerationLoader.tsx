import type { CSSProperties } from "react";

const ORBIT_DURATION_SECONDS = 6.4;
const BREATHE_DURATION_SECONDS = 2.4;

type LoaderStyle = CSSProperties & {
  "--agent-canvas-loader-orbit-delay": string;
  "--agent-canvas-loader-breathe-delay": string;
};

// Kept beside the Loader so its CSS phase contract remains explicit and testable.
// eslint-disable-next-line react-refresh/only-export-components
export function mediaGenerationLoaderDelays(nodeId: string): LoaderStyle {
  let hash = 2166136261;
  for (let index = 0; index < nodeId.length; index += 1) {
    hash ^= nodeId.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  const phase = (hash >>> 0) / 0x1_0000_0000;
  return {
    "--agent-canvas-loader-orbit-delay": `-${(phase * ORBIT_DURATION_SECONDS).toFixed(3)}s`,
    "--agent-canvas-loader-breathe-delay": `-${(phase * BREATHE_DURATION_SECONDS).toFixed(3)}s`,
  };
}

export function AgentCanvasMediaGenerationLoader({
  mediaType,
  nodeId,
  overMedia = false,
}: {
  mediaType: "image" | "video";
  nodeId: string;
  overMedia?: boolean;
}) {
  return (
    <div
      className={[
        "agent-canvas-node__working",
        "agent-canvas-node__working--media",
        overMedia ? "agent-canvas-node__working--over-media" : "",
      ].filter(Boolean).join(" ")}
      role="status"
      aria-label={`Generating ${mediaType}`}
      style={mediaGenerationLoaderDelays(nodeId)}
    >
      <span
        className="agent-canvas-node__generation-dots agent-canvas-node__generation-dots--static"
        aria-hidden="true"
      />
      <span
        className="agent-canvas-node__generation-dots agent-canvas-node__generation-dots--dynamic"
        aria-hidden="true"
      />
    </div>
  );
}
