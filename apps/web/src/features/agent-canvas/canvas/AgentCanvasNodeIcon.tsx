import type { CanvasNodeTypeV2 } from "../../../types-v2.ts";

const NODE_ICON_ASSETS: Record<CanvasNodeTypeV2, string> = {
  text: "/imgs/node-icons/text.svg",
  script: "/imgs/node-icons/text.svg",
  image: "/imgs/node-icons/picture.svg",
  video: "/imgs/node-icons/video.svg",
  audio: "/imgs/node-icons/audio.svg",
  editing: "/imgs/node-icons/video.svg",
};

export function AgentCanvasNodeIcon({ nodeType }: { nodeType: CanvasNodeTypeV2 }) {
  const asset = NODE_ICON_ASSETS[nodeType];
  return (
    <span
      className="agent-canvas-node-icon"
      aria-hidden="true"
      data-icon-source={asset}
      style={{
        maskImage: `url("${asset}")`,
        WebkitMaskImage: `url("${asset}")`,
      }}
    />
  );
}
