import type { ReactNode } from "react";

import type { StageThreadUnit } from "./stageThreadProjection.ts";
import { AgentCapabilityIdentity } from "./AgentCapabilityIdentity.tsx";
import type { AgentRoleMotionState } from "./agent-role-animation/types.ts";

export function StageThread({
  unit,
  motionState,
  children,
  result,
}: {
  unit: StageThreadUnit;
  motionState: AgentRoleMotionState;
  children?: ReactNode;
  result?: ReactNode;
}) {
  return (
    <section className={`agent-chat__stage-thread is-${unit.status}`}>
      <header>
        <AgentCapabilityIdentity
          capabilityId={unit.capability_id}
          displayName={unit.capability_display_name}
          motionState={motionState}
        />
        {result}
      </header>
      {children ? (
        <div className="agent-chat__stage-thread-history">{children}</div>
      ) : null}
    </section>
  );
}
