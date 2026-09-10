import { Component, useCallback, useRef, useState, type ReactNode } from "react";
import type { AgentCapabilityIdV2 } from "../../../../types-v2.ts";
import type { AgentRoleMotionState } from "./types.ts";
import { useAgentRoleVisual } from "./useAgentRoleVisual.ts";
import { useRoleWaitingMotion } from "./useRoleWaitingMotion.ts";
import { reportRoleArtworkError } from "./agentRoleVisualResource.ts";

class RoleArtworkBoundary extends Component<
  { children: ReactNode; fallback: ReactNode; onError(): void }, { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() { this.props.onError(); }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

function StaticRoleIcon({ source, generic }: { source: string | null; generic: boolean }) {
  if (!source) return generic ? <span className="agent-chat__role-generic" data-role-generic-fallback="true" aria-hidden="true">✧</span> : null;
  return <img className="agent-chat__role-animation-asset agent-chat__role-animation-static is-visible"
    data-testid="agent-role-static-icon" src={source} width={32} height={32}
    decoding="sync" alt="" aria-hidden="true" draggable={false} />;
}

export function AgentRoleAnimation({ capabilityId, motionState }: {
  capabilityId: AgentCapabilityIdV2; motionState: AgentRoleMotionState;
}) {
  const visual = useAgentRoleVisual(capabilityId, motionState);
  const [failedGeneration, setFailedGeneration] = useState<number | null>(null);
  const failed = failedGeneration === visual.generation;
  const Artwork = motionState !== "idle" && !failed ? visual.Artwork : null;
  const waiting = motionState === "waiting" || (motionState === "working" && !Artwork);
  const ref = useRef<HTMLSpanElement>(null);
  useRoleWaitingMotion(ref, waiting && visual.status !== "pending");
  const onError = useCallback(() => {
    setFailedGeneration(visual.generation);
    reportRoleArtworkError(capabilityId, "Role artwork could not be displayed");
  }, [capabilityId, visual.generation]);
  const fallback = <StaticRoleIcon source={visual.source} generic={visual.fallbackKind === "generic"} />;
  return (
    <span ref={ref} className="agent-chat__role-animation-frame"
      style={{ width: 32, height: 32 }}
      data-testid="agent-role-animation-frame" data-motion-state={motionState}
      data-role-waiting-motion={String(waiting)} aria-hidden="true">
      {Artwork ? <RoleArtworkBoundary key={capabilityId + visual.generation} fallback={fallback} onError={onError}>
        <span className="agent-chat__role-animation-asset agent-chat__role-animation-artwork is-visible">
          <Artwork motionState={motionState} />
        </span>
      </RoleArtworkBoundary> : fallback}
    </span>
  );
}
