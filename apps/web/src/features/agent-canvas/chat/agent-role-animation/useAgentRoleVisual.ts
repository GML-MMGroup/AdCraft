import { useCallback, useEffect, useSyncExternalStore } from "react";
import type { AgentCapabilityIdV2 } from "../../../../types-v2.ts";
import { getRoleVisualSnapshot, prepareRoleVisual, subscribeRoleVisual } from "./agentRoleVisualResource.ts";
import type { AgentRoleMotionState } from "./types.ts";

export function useAgentRoleVisual(role: AgentCapabilityIdV2, state: AgentRoleMotionState) {
  const mode = state === "idle" ? "bitmap" : "animated";
  const subscribe = useCallback((listener: () => void) => subscribeRoleVisual(role, mode, listener), [role, mode]);
  const snapshot = useCallback(() => getRoleVisualSnapshot(role, mode), [role, mode]);
  useEffect(() => { prepareRoleVisual(role, mode); }, [role, mode]);
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
