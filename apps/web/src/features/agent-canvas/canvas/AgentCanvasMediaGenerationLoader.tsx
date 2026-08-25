import type { CSSProperties } from "react";

const STAR_PARTICLES = Array.from({ length: 20 }, (_, index) => ({
  index,
  x: 8 + ((index * 37) % 84),
  y: 8 + ((index * 53) % 84),
  size: 5.4 + ((index * 7) % 5) * 1.05,
  delay: -((index * 13) % 20) / 20,
  rotation: ((index * 29) % 32) - 16,
}));

type StarParticleStyle = CSSProperties & {
  "--star-x": string;
  "--star-y": string;
  "--star-size": string;
  "--star-delay": string;
  "--star-rotation": string;
};

export function AgentCanvasMediaGenerationLoader({
  mediaType,
}: {
  mediaType: "image" | "video";
}) {
  return (
    <div className="agent-canvas-node__working agent-canvas-node__working--media">
      <span
        className="agent-canvas-node__generation-loader"
        data-variant="star-diffusion"
        role="status"
        aria-label={`Generating ${mediaType}`}
      >
        <span className="agent-canvas-node__generation-field" aria-hidden="true">
          {STAR_PARTICLES.map((particle) => (
            <i
              key={particle.index}
              className="agent-canvas-node__generation-star"
              style={{
                "--star-x": `${particle.x}%`,
                "--star-y": `${particle.y}%`,
                "--star-size": `${particle.size}%`,
                "--star-delay": `${particle.delay * 2.5}s`,
                "--star-rotation": `${particle.rotation}deg`,
              } as StarParticleStyle}
            />
          ))}
        </span>
      </span>
    </div>
  );
}
