import type { AgentCapabilityIdV2 } from "../../../types-v2.ts";

const AGENT_CAPABILITY_ICON_PATHS: Partial<Record<AgentCapabilityIdV2, string>> = {
  world_setting: "/imgs/agent-role-icons/world-setting.png",
  product_design: "/imgs/agent-role-icons/product-designer.png",
  prop_design: "/imgs/agent-role-icons/prop-designer.png",
  character_design: "/imgs/agent-role-icons/character-designer.png",
  scene_design: "/imgs/agent-role-icons/scene-designer.png",
  script_authoring: "/imgs/agent-role-icons/script-writer.png",
  storyboard_design: "/imgs/agent-role-icons/storyboard-artist.png",
  video_direction: "/imgs/agent-role-icons/video-director.png",
  bgm_direction: "/imgs/agent-role-icons/bgm-director.png",
  quick_media: "/imgs/agent-role-icons/quick-media.png",
};

export function AgentCapabilityIcon({
  capabilityId,
}: {
  capabilityId: AgentCapabilityIdV2;
}) {
  const source = AGENT_CAPABILITY_ICON_PATHS[capabilityId];
  if (!source) return null;

  return (
    <img
      className="agent-chat__capability-icon"
      data-testid="agent-capability-icon"
      src={source}
      alt=""
      aria-hidden="true"
      draggable={false}
    />
  );
}
