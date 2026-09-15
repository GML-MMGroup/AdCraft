import { useCallback, useEffect, useSyncExternalStore } from "react";
import type { AgentCapabilityIdV2 } from "../../../../types-v2.ts";
import {
  getRoleVisualSnapshot,
  prepareRoleVisual,
  subscribeRoleVisual,
  type RoleVisualMode,
} from "./agentRoleVisualResource.ts";
import type { AgentRoleMotionState } from "./types.ts";

export function roleVisualMode(state: AgentRoleMotionState): RoleVisualMode {
  // Only working roles play the animated artwork; idle collapses to the static
  // bitmap. A role holds its working stretch until the next role takes over.
  return state === "working" ? "animated" : "bitmap";
}

export function useAgentRoleVisual(role: AgentCapabilityIdV2, state: AgentRoleMotionState) {
  const mode = roleVisualMode(state);
  const subscribe = useCallback((listener: () => void) => subscribeRoleVisual(role, mode, listener), [role, mode]);
  const snapshot = useCallback(() => getRoleVisualSnapshot(role, mode), [role, mode]);
  useEffect(() => { prepareRoleVisual(role, mode); }, [role, mode]);
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
