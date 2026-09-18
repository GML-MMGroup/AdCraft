import { api } from "../../../api/client.ts";
import { subscribeProviderConfigurationChanges } from "../../../api/providerConfigurationEvents.ts";
import type { ModelDefaultsResponseV1, ProviderModelSummaryV1 } from "../../../api/providerRegistry.ts";

export type ModelPickerNodeType = "text" | "script" | "image" | "video" | "audio";
export const PROVIDER_MODEL_CACHE_MAX_AGE_MS = 5 * 60 * 1_000;

interface ResourceSnapshot<T> {
  data: T | null;
  error: string | null;
  pending: boolean;
}

// Dedicated to the five node-type catalogs and one installation-default resource.
// No credentials, Workflow state, or user drafts belong in this cache.
function createResource<T>(load: () => Promise<T>, fallbackError: string) {
  let snapshot: ResourceSnapshot<T> = { data: null, error: null, pending: false };
  let freshUntil = 0;
  let generation = 0;
  let request: Promise<void> | null = null;
  const listeners = new Set<() => void>();
  const publish = (next: ResourceSnapshot<T>) => {
    snapshot = next;
    listeners.forEach(listener => listener());
  };

  const ensureFresh = (force = false): Promise<void> => {
    if (request) return request;
    if (!force && snapshot.data !== null && !snapshot.error && Date.now() < freshUntil) return Promise.resolve();
    const requestGeneration = generation;
    request = load().then(data => {
      if (generation !== requestGeneration) return;
      freshUntil = Date.now() + PROVIDER_MODEL_CACHE_MAX_AGE_MS;
      publish({ data, error: null, pending: false });
    }).catch((error: unknown) => {
      if (generation !== requestGeneration) return;
      publish({
        data: snapshot.data,
        error: error instanceof Error ? error.message : fallbackError,
        pending: false,
      });
    }).finally(() => {
      if (generation === requestGeneration) request = null;
    });
    publish({ ...snapshot, error: null, pending: true });
    return request;
  };

  return {
    getSnapshot: () => snapshot,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    ensureFresh,
    invalidate: () => {
      generation += 1;
      request = null;
      freshUntil = 0;
      publish({ data: null, error: null, pending: false });
      if (listeners.size) void ensureFresh();
    },
  };
}

const catalogs = new Map<ModelPickerNodeType, ReturnType<typeof createResource<ProviderModelSummaryV1[]>>>();

export function providerModelsForNodeType(nodeType: ModelPickerNodeType) {
  let resource = catalogs.get(nodeType);
  if (!resource) {
    resource = createResource(
      async () => (await api.listProviderModels({ node_type: nodeType, include_unavailable: true })).items,
      "Compatible models could not be loaded.",
    );
    catalogs.set(nodeType, resource);
  }
  return resource;
}

export const providerModelDefaults = createResource<ModelDefaultsResponseV1>(
  () => api.getModelDefaults(),
  "Default model could not be loaded.",
);

subscribeProviderConfigurationChanges(change => {
  if (change === "all") catalogs.forEach(resource => resource.invalidate());
  providerModelDefaults.invalidate();
});
