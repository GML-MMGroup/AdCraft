import type { ReactNode } from "react";

import type { StageThreadUnit } from "./stageThreadProjection.ts";
import { AgentCapabilityIcon } from "./AgentCapabilityIcon.tsx";

function statusLabel(status: StageThreadUnit["status"]): string {
  switch (status) {
    case "working": return "Working";
    case "waiting_user": return "Waiting for you";
    case "completed": return "Completed";
    case "failed": return "Needs attention";
    case "superseded": return "Superseded";
  }
}

function elapsedLabel(unit: StageThreadUnit): string | null {
  const elapsedMs = unit.activities.reduce((total, activity) => total + (activity.elapsed_ms ?? 0), 0);
  if (!elapsedMs) return null;
  const seconds = Math.max(1, Math.round(elapsedMs / 1000));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function StageThread({
  unit,
  children,
  result,
}: {
  unit: StageThreadUnit;
  children?: ReactNode;
  result?: ReactNode;
}) {
  const elapsed = elapsedLabel(unit);

  return (
    <section className={`agent-chat__stage-thread is-${unit.status}`}>
      <header>
        <div>
          <div className="agent-chat__capability-heading">
            <AgentCapabilityIcon capabilityId={unit.capability_id} />
            <strong>{unit.capability_display_name}</strong>
          </div>
          <span>
            {statusLabel(unit.status)}
            {elapsed ? ` · ${elapsed}` : ""}
          </span>
        </div>
        {result}
      </header>
      {children ? (
        <div className="agent-chat__stage-thread-history">{children}</div>
      ) : null}
    </section>
  );
}
