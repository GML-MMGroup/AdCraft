import type { ReactNode } from "react";
import { InlineLoader } from "generative-loaders";
import "generative-loaders/styles.css";

import type { StageThreadUnit } from "./stageThreadProjection.ts";
import { AgentCapabilityIdentity } from "./AgentCapabilityIdentity.tsx";
import type { AgentRoleMotionState } from "./agent-role-animation/types.ts";
import { useAgentRoleVisual } from "./agent-role-animation/useAgentRoleVisual.ts";
import { retryRoleVisual } from "./agent-role-animation/agentRoleVisualResource.ts";

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
  const visual = useAgentRoleVisual(unit.capability_id, motionState);
  const workingArtworkReady = motionState !== "working"
    || (visual.status === "ready" && visual.Artwork !== null);

  if (!workingArtworkReady) {
    if (visual.error) {
      return (
        <section className="agent-chat__stage-thread" role="alert">
          <span>Role animation could not be loaded.</span>
          <button type="button" disabled={visual.retryAvailable === false}
            onClick={() => retryRoleVisual(unit.capability_id, "animated")}>
            {visual.retryAvailable === false ? "Reload the page to try again" : "Retry animation"}
          </button>
        </section>
      );
    }
    return (
      <section
        className={`agent-chat__stage-thread agent-chat__stage-thread--loading is-${unit.status}`}
        aria-label="Working"
        role="status"
      >
        <div className="agent-chat__role-loading">
          <InlineLoader
            variant="halo"
            size={20}
            className="agent-chat__role-loading-loader"
          />
          <span>Working</span>
        </div>
      </section>
    );
  }

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
