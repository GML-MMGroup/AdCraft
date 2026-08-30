import { ImageLoader } from "generative-loaders";
import "generative-loaders/styles.css";

export function AgentCanvasMediaGenerationLoader({
  mediaType,
}: {
  mediaType: "image" | "video";
}) {
  return (
    <div className="agent-canvas-node__working agent-canvas-node__working--media">
      <div className="agent-canvas-node__generation-loader">
        <ImageLoader
          label={`Generating ${mediaType}`}
          size={192}
          variant="coalesce"
        />
      </div>
    </div>
  );
}
