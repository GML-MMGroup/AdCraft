import type { ReactNode } from "react";

import type { StageThreadUnit } from "./stageThreadProjection.ts";
import { AgentCapabilityIdentity } from "./AgentCapabilityIdentity.tsx";

export function StageThread({
  unit,
  children,
  result,
}: {
  unit: StageThreadUnit;
  children?: ReactNode;
  result?: ReactNode;
}) {
  return (
    <section className={`agent-chat__stage-thread is-${unit.status}`}>
      <header>
        <AgentCapabilityIdentity
          capabilityId={unit.capability_id}
          displayName={unit.capability_display_name}
        />
        {result}
      </header>
      {children ? (
        <div className="agent-chat__stage-thread-history">{children}</div>
      ) : null}
    </section>
  );
}
