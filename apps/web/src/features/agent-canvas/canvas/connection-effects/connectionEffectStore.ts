export type ConnectionPulse = { id: number; color: string; connectionId: string };
export function createConnectionEffectStore() {
  const pulses = new Map<string, ConnectionPulse>();
  const timers = new Map<string, ReturnType<typeof setTimeout>>();
  const listeners = new Set<() => void>();
  let sequence = 0;
  const key = (workflowId: string, nodeId: string) => JSON.stringify([workflowId, nodeId]);
  const emit = () => listeners.forEach(listener => listener());
  return {
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    get(workflowId: string, nodeId: string) { return pulses.get(key(workflowId, nodeId)) ?? null; },
    publish(workflowId: string, nodeId: string, connectionId: string, color: string) {
      const scope = key(workflowId, nodeId);
      // Latest gesture per node wins: bursts never accumulate overlays or timers.
      clearTimeout(timers.get(scope));
      pulses.set(scope, { id: ++sequence, color, connectionId });
      timers.set(scope, setTimeout(() => { pulses.delete(scope); timers.delete(scope); emit(); }, 950));
      emit();
    },
    clear() { timers.forEach(clearTimeout); timers.clear(); pulses.clear(); emit(); },
  };
}
