import { useMemo, useState } from "react";

import { api } from "../../api/client.ts";
import {
  credentialUpdateFromDraft,
  emptyProviderCredentialDraft,
  supportsCredentialTest,
  type ProviderCapability,
  type ProviderConnectionStatusV1,
  type ProviderModelSummaryV1,
} from "../../api/providerRegistry.ts";
import { providerRegistryErrorMessage, type ApiSpaceNotice } from "./providerRegistryMessages.ts";

type CredentialNoticeByCapability = Partial<Record<ProviderCapability, ApiSpaceNotice>>;

export function ProviderCredentialCard({
  provider,
  models,
  onProviderUpdated,
  onModelsUpdated,
}: {
  provider: ProviderConnectionStatusV1;
  models: ProviderModelSummaryV1[];
  onProviderUpdated: (provider: ProviderConnectionStatusV1) => void;
  onModelsUpdated: (providerId: string, models: ProviderModelSummaryV1[]) => void;
}) {
  const [draft, setDraft] = useState(() => emptyProviderCredentialDraft(provider.capabilities));
  const [pending, setPending] = useState<"save" | "sync" | ProviderCapability | null>(null);
  const [notice, setNotice] = useState<ApiSpaceNotice>(null);
  const [testNotices, setTestNotices] = useState<CredentialNoticeByCapability>({});
  const [pendingClear, setPendingClear] = useState<ProviderCapability | null>(null);
  const updateRequest = useMemo(() => credentialUpdateFromDraft(draft), [draft]);
  const availableModelCount = models.filter((model) => model.availability === "available").length;

  const updateDraft = (capability: ProviderCapability, value: string) => {
    setDraft((current) => ({ ...current, [capability]: value }));
    setNotice(null);
    setTestNotices((current) => ({ ...current, [capability]: null }));
  };

  const save = async () => {
    if (!updateRequest || pending) return;
    setPending("save");
    setNotice(null);
    try {
      const response = await api.updateProviderCredentials(provider.provider_id, updateRequest);
      onProviderUpdated(response.provider);
      setDraft(emptyProviderCredentialDraft(provider.capabilities));
      setTestNotices({});
      setNotice({ kind: "success", message: `${provider.display_name} credentials saved.` });
    } catch (error) {
      setNotice({ kind: "error", message: providerRegistryErrorMessage(error, "save") });
    } finally {
      setPending(null);
    }
  };

  const clearCapability = async (capability: ProviderCapability) => {
    if (pending) return;
    setPending(capability);
    setNotice(null);
    try {
      const response = await api.updateProviderCredentials(provider.provider_id, {
        api_keys: {},
        clear_capabilities: [capability],
      });
      onProviderUpdated(response.provider);
      setDraft((current) => ({ ...current, [capability]: "" }));
      setPendingClear(null);
      setNotice({ kind: "success", message: `${capabilityLabel(capability)} credential cleared.` });
    } catch (error) {
      setNotice({ kind: "error", message: providerRegistryErrorMessage(error, "save") });
    } finally {
      setPending(null);
    }
  };

  const testCredential = async (capability: ProviderCapability) => {
    const status = provider.credentials[capability];
    if (!supportsCredentialTest(status) || pending) return;
    const candidate = draft[capability]?.trim();
    setPending(capability);
    setTestNotices((current) => ({ ...current, [capability]: null }));
    try {
      await api.testProviderCredential(provider.provider_id, {
        capability,
        ...(candidate ? { api_key: candidate } : {}),
      });
      setTestNotices((current) => ({
        ...current,
        [capability]: { kind: "success", message: `${capabilityLabel(capability)} credential verified.` },
      }));
    } catch (error) {
      setTestNotices((current) => ({
        ...current,
        [capability]: { kind: "error", message: providerRegistryErrorMessage(error, "test") },
      }));
    } finally {
      setPending(null);
    }
  };

  const syncModels = async () => {
    if (pending) return;
    setPending("sync");
    setNotice(null);
    try {
      await api.syncProviderModels(provider.provider_id);
      const nextModels = await api.listProviderModels({
        provider: provider.provider_id,
        include_unavailable: true,
      });
      onModelsUpdated(provider.provider_id, nextModels.items);
      setNotice({ kind: "success", message: "Models synchronized." });
    } catch (error) {
      setNotice({ kind: "error", message: providerRegistryErrorMessage(error, "sync") });
    } finally {
      setPending(null);
    }
  };

  return (
    <section className="api-space-provider-surface" aria-label={`${provider.display_name} provider settings`}>
      <header className="api-space-provider-header">
        <div>
          <span className="api-space-eyebrow">{provider.connection_state === "configured" ? "Configured provider" : "Provider"}</span>
          <h2>{provider.display_name}</h2>
        </div>
        <span className="api-space-local-badge">Local settings</span>
      </header>

      <p className="api-space-intro">
        Keys stay in the local backend. This browser receives configuration status only and never reads a saved key back.
      </p>

      <div className="api-space-credential-list">
        {provider.capabilities.map((capability) => {
          const status = provider.credentials[capability];
          const isTesting = pending === capability && supportsCredentialTest(status);
          const isClearing = pending === capability && pendingClear === capability;
          const isBusy = Boolean(pending);
          return (
            <section className="api-space-credential-row" key={capability}>
              <div className="api-space-credential-copy">
                <h3>{capabilityLabel(capability)} API Key</h3>
                <p>{capabilityDescription(capability)}</p>
                <CredentialStatus configured={status?.configured ?? false} fingerprint={status?.fingerprint ?? null} />
              </div>
              <div className="api-space-credential-control">
                <label className="sr-only" htmlFor={`${provider.provider_id}-${capability}-api-key`}>
                  {provider.display_name} {capabilityLabel(capability)} API Key
                </label>
                <input
                  id={`${provider.provider_id}-${capability}-api-key`}
                  name={`${provider.provider_id}-${capability}-api-key`}
                  type="password"
                  value={draft[capability] ?? ""}
                  placeholder="Paste a new API key"
                  autoComplete="new-password"
                  disabled={isBusy}
                  onChange={(event) => updateDraft(capability, event.currentTarget.value)}
                />
                <div className="api-space-credential-actions">
                  {supportsCredentialTest(status) ? (
                    <button
                      className="small-action"
                      type="button"
                      disabled={isBusy}
                      onClick={() => void testCredential(capability)}
                    >
                      {isTesting ? "Testing..." : `Test ${capabilityLabel(capability)} key`}
                    </button>
                  ) : <span className="api-space-test-unavailable">Test unavailable</span>}
                  {status?.configured ? (
                    pendingClear === capability ? (
                      <span className="api-space-clear-confirmation">
                        Clear this saved key?
                        <button className="small-action" type="button" disabled={isBusy} onClick={() => void clearCapability(capability)}>
                          {isClearing ? "Clearing..." : "Confirm clear"}
                        </button>
                        <button className="small-action" type="button" disabled={isBusy} onClick={() => setPendingClear(null)}>Cancel</button>
                      </span>
                    ) : (
                      <button className="small-action" type="button" disabled={isBusy} onClick={() => setPendingClear(capability)}>
                        Clear saved key
                      </button>
                    )
                  ) : null}
                  {testNotices[capability] ? <InlineNotice notice={testNotices[capability]!} /> : null}
                </div>
              </div>
            </section>
          );
        })}
      </div>

      <footer className="api-space-save-bar">
        <span className="api-space-model-count">
          {availableModelCount} available / {models.length} discovered models
        </span>
        <div className="api-space-save-actions">
          <button className="small-action" type="button" disabled={Boolean(pending)} onClick={() => void syncModels()}>
            {pending === "sync" ? "Syncing models..." : "Sync models"}
          </button>
          <button className="send-btn" type="button" disabled={!updateRequest || Boolean(pending)} onClick={() => void save()}>
            {pending === "save" ? "Saving..." : `Save ${provider.display_name} credentials`}
          </button>
        </div>
        {notice ? <InlineNotice notice={notice} /> : null}
      </footer>
    </section>
  );
}

function CredentialStatus({ configured, fingerprint }: { configured: boolean; fingerprint: string | null }) {
  return configured
    ? <span className="api-space-credential-status is-configured">Configured{fingerprint ? ` · ${fingerprint}` : ""}</span>
    : <span className="api-space-credential-status is-not-configured">Not configured</span>;
}

function InlineNotice({ notice }: { notice: Exclude<ApiSpaceNotice, null> }) {
  return <span className={`api-space-inline-notice is-${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>{notice.message}</span>;
}

function capabilityLabel(capability: ProviderCapability): string {
  return capability.charAt(0).toUpperCase() + capability.slice(1);
}

function capabilityDescription(capability: ProviderCapability): string {
  if (capability === "text") return "Used for planning, scripts, text nodes, and Agent work.";
  if (capability === "image") return "Used by image generation nodes.";
  if (capability === "video") return "Used by video generation nodes.";
  return "Used by audio and BGM generation nodes.";
}
