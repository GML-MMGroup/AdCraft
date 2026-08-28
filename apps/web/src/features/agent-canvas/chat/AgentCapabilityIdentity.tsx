import type { AgentCapabilityIdV2 } from "../../../types-v2.ts";
import { AgentCapabilityIcon } from "./AgentCapabilityIcon.tsx";

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
    <div className="agent-chat__capability-identity">
      <AgentCapabilityIcon capabilityId={capabilityId} />
      <div className="agent-chat__capability-identity-copy">
        <strong>{displayName}</strong>
        {detail ? <span>{detail}</span> : null}
      </div>
    </div>
  );
}
