import type { AgentCapabilityIdV2 } from "../../../types-v2.ts";
import { AgentCapabilityIcon } from "./AgentCapabilityIcon.tsx";

const AGENT_CAPABILITY_ROLE_CLASSES: Record<AgentCapabilityIdV2, string> = {
  world_setting: "is-role-world-setting",
  product_design: "is-role-product-design",
  prop_design: "is-role-prop-design",
  character_design: "is-role-character-design",
  scene_design: "is-role-scene-design",
  script_authoring: "is-role-script-authoring",
  storyboard_design: "is-role-storyboard-design",
  video_direction: "is-role-video-direction",
  bgm_direction: "is-role-bgm-direction",
  quick_media: "is-role-quick-media",
};

export function AgentCapabilityIdentity({
  capabilityId,
  displayName,
  detail,
}: {
  capabilityId: AgentCapabilityIdV2;
  displayName: string;
  detail?: string | null;
}) {
  return (
    <div className={`agent-chat__capability-identity ${AGENT_CAPABILITY_ROLE_CLASSES[capabilityId]}`}>
      <AgentCapabilityIcon capabilityId={capabilityId} />
      <div className="agent-chat__capability-identity-copy">
        <strong>{displayName}</strong>
        {detail ? <span>{detail}</span> : null}
      </div>
    </div>
  );
}
