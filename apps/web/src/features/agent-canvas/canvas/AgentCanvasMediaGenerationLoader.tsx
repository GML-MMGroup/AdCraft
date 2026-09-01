export function AgentCanvasMediaGenerationLoader({
  mediaType,
}: {
  mediaType: "image" | "video";
}) {
  return (
    <div
      className="agent-canvas-node__working agent-canvas-node__working--media"
      role="status"
      aria-label={`Generating ${mediaType}`}
    >
      <span className="agent-canvas-node__generation-energy" aria-hidden="true" />
    </div>
  );
}
