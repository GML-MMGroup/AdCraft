import { createContext, useContext, useSyncExternalStore } from "react";
import type { createConnectionEffectStore } from "./connectionEffectStore";
export const ConnectionEffectContext = createContext<ReturnType<typeof createConnectionEffectStore> | null>(null);
const noopSubscribe = () => () => {};
const empty = () => null;
export function useConnectionPulse(workflowId: string, nodeId: string) {
  const store = useContext(ConnectionEffectContext);
  return useSyncExternalStore(store?.subscribe ?? noopSubscribe, () => store?.get(workflowId, nodeId) ?? null, empty);
}
