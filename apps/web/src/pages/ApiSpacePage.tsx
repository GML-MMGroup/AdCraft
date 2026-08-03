import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api/client.ts";
import {
  MODEL_DEFAULT_PURPOSES,
  type ModelDefaultPurpose,
  type ModelDefaultsPatchRequestV1,
  type ModelDefaultsResponseV1,
  type ProviderConnectionStatusV1,
  type ProviderModelSummaryV1,
} from "../api/providerRegistry.ts";
import { PageHeader } from "../components/Layout";
import { ModelDefaultsPanel } from "./api-space/ModelDefaultsPanel.tsx";
import { ProviderCredentialCard } from "./api-space/ProviderCredentialCard.tsx";
import { providerRegistryErrorMessage, type ApiSpaceNotice } from "./api-space/providerRegistryMessages.ts";
import "./api-space.css";

type ModelsByProvider = Record<string, ProviderModelSummaryV1[]>;
type ModelsByPurpose = Record<ModelDefaultPurpose, ProviderModelSummaryV1[]>;

export function ApiSpacePage() {
  const [providers, setProviders] = useState<ProviderConnectionStatusV1[]>([]);
  const [modelsByProvider, setModelsByProvider] = useState<ModelsByProvider>({});
  const [defaults, setDefaults] = useState<ModelDefaultsResponseV1>({ defaults: {}, modes: {}, revisions: {} });
  const [modelsByPurpose, setModelsByPurpose] = useState<ModelsByPurpose>(emptyModelsByPurpose);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [defaultsPending, setDefaultsPending] = useState(false);
  const [defaultsNotice, setDefaultsNotice] = useState<ApiSpaceNotice>(null);
  const requestRef = useRef(0);

  const load = useCallback(async () => {
    const requestId = ++requestRef.current;
    setLoading(true);
    setLoadError(null);
    try {
      const providerResponse = await api.listProviders();
      const [defaultsResponse, purposeResponses, providerResponses] = await Promise.all([
        api.getModelDefaults(),
        Promise.all(MODEL_DEFAULT_PURPOSES.map((purpose) => api.listProviderModels({ purpose }))),
        Promise.all(providerResponse.items.map(async (provider) => ({
          providerId: provider.provider_id,
          response: await api.listProviderModels({ provider: provider.provider_id, include_unavailable: true }),
        }))),
      ]);
      if (requestId !== requestRef.current) return;
      setProviders(providerResponse.items);
      setDefaults(defaultsResponse);
      setModelsByPurpose(Object.fromEntries(MODEL_DEFAULT_PURPOSES.map((purpose, index) => [
        purpose,
        purposeResponses[index]?.items ?? [],
      ])) as ModelsByPurpose);
      setModelsByProvider(Object.fromEntries(providerResponses.map(({ providerId, response }) => [
        providerId,
        response.items,
      ])));
    } catch (error) {
      if (requestId === requestRef.current) setLoadError(providerRegistryErrorMessage(error, "load"));
    } finally {
      if (requestId === requestRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    return () => { requestRef.current += 1; };
  }, [load]);

  const updateProvider = useCallback((next: ProviderConnectionStatusV1) => {
    setProviders((current) => current.map((provider) => (
      provider.provider_id === next.provider_id ? next : provider
    )));
  }, []);

  const updateProviderModels = useCallback((providerId: string, models: ProviderModelSummaryV1[]) => {
    setModelsByProvider((current) => ({ ...current, [providerId]: models }));
    void Promise.all(MODEL_DEFAULT_PURPOSES.map((purpose) => api.listProviderModels({ purpose })))
      .then((responses) => {
        setModelsByPurpose(Object.fromEntries(MODEL_DEFAULT_PURPOSES.map((purpose, index) => [
          purpose,
          responses[index]?.items ?? [],
        ])) as ModelsByPurpose);
      })
      .catch(() => {
        // Provider cards retain their successfully refreshed list if default options cannot refresh.
      });
  }, []);

  const saveDefaults = useCallback(async (changes: ModelDefaultsPatchRequestV1) => {
    setDefaultsPending(true);
    setDefaultsNotice(null);
    try {
      const response = await api.patchModelDefaults(changes);
      setDefaults(response);
      setDefaultsNotice({ kind: "success", message: "Default model settings saved." });
    } catch (error) {
      setDefaultsNotice({ kind: "error", message: providerRegistryErrorMessage(error, "defaults") });
    } finally {
      setDefaultsPending(false);
    }
  }, []);

  return (
    <section className="content-wrap api-space-page">
      <PageHeader title="API Space" subtitle="Configure local provider credentials and the models used by new runs." />

      {loadError ? (
        <div className="api-space-status-error" role="alert">
          <span>{loadError}</span>
          <button className="small-action" type="button" disabled={loading} onClick={() => void load()}>
            Reload providers
          </button>
        </div>
      ) : null}

      {loading && !providers.length ? <p className="api-space-loading">Loading provider settings...</p> : null}

      {providers.map((provider) => (
        <ProviderCredentialCard
          key={provider.provider_id}
          provider={provider}
          models={modelsByProvider[provider.provider_id] ?? []}
          onProviderUpdated={updateProvider}
          onModelsUpdated={updateProviderModels}
        />
      ))}

      <ModelDefaultsPanel
        defaults={defaults}
        modelsByPurpose={modelsByPurpose}
        loading={loading}
        pending={defaultsPending}
        notice={defaultsNotice}
        onSave={saveDefaults}
      />
    </section>
  );
}

function emptyModelsByPurpose(): ModelsByPurpose {
  return MODEL_DEFAULT_PURPOSES.reduce<ModelsByPurpose>((result, purpose) => {
    result[purpose] = [];
    return result;
  }, {} as ModelsByPurpose);
}
