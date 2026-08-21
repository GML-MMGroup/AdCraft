import { ImageLoader } from "generative-loaders";
import "generative-loaders/styles.css";

export function AgentCanvasMediaGenerationLoader({
  mediaType,
}: {
  mediaType: "image" | "video";
}) {
  return (
    <div className="agent-canvas-node__working agent-canvas-node__working--media">
      <ImageLoader
        variant="diffusion"
        size={192}
        label={`Generating ${mediaType}`}
        className="agent-canvas-node__generation-loader"
      />
    </div>
  );
}
