import type { AgentCapabilityIdV2 } from "../../../types-v2.ts";
import { AgentCapabilityIcon } from "./AgentCapabilityIcon.tsx";
import type { AgentRoleMotionState } from "./agent-role-animation/types.ts";
import { useAgentRoleVisual } from "./agent-role-animation/useAgentRoleVisual.ts";
import { retryRoleVisual } from "./agent-role-animation/agentRoleVisualResource.ts";

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
  motionState,
}: {
  capabilityId: AgentCapabilityIdV2;
  displayName: string;
  detail?: string | null;
  motionState?: AgentRoleMotionState;
}) {
  const state = motionState ?? "idle";
  const visual = useAgentRoleVisual(capabilityId, state);
  const pending = visual.status === "pending";
  return (
    <div className={`agent-chat__capability-identity ${AGENT_CAPABILITY_ROLE_CLASSES[capabilityId]}`}
      data-role-identity-state={visual.status}>
      <AgentCapabilityIcon capabilityId={capabilityId} motionState={motionState} />
      <div className="agent-chat__capability-identity-copy" style={pending ? { visibility: "hidden" } : undefined} aria-hidden={pending || undefined}>
        <strong>{displayName}</strong>
        {detail ? <span>{detail}</span> : null}
      </div>
      {pending ? <span className="agent-chat__identity-skeleton" aria-hidden="true" /> : null}
      {visual.error ? <button type="button" className="agent-chat__identity-retry"
        aria-label={`Retry ${displayName} icon`} disabled={visual.retryAvailable === false}
        title={visual.retryAvailable === false ? "Icon unavailable. Reload the page to try again." : "Retry role icon"}
        onClick={() => retryRoleVisual(capabilityId, state === "idle" ? "bitmap" : "animated")}>↻</button> : null}
    </div>
  );
}
