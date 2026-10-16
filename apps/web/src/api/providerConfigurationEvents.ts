export type ProviderConfigurationChange = "all" | "defaults";

const listeners = new Set<(change: ProviderConfigurationChange) => void>();

/** In-page invalidation only. Never send credential values or request bodies. */
export function notifyProviderConfigurationChanged(change: ProviderConfigurationChange): void {
  listeners.forEach(listener => listener(change));
}

export function subscribeProviderConfigurationChanges(
  listener: (change: ProviderConfigurationChange) => void,
): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
