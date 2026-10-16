import { useTranslation } from "../../i18n/useTranslation";
import { translateUi } from "../../i18n/uiMessages";
import { useLocale } from "../../i18n/locale";
import { useMemo, useState } from "react";

import { api } from "../../api/client.ts";
import { modelEligibility } from "../../api/providerModelPolicy.ts";
import {
  clearCapabilitiesForProvider,
  updateCredentialDraftForProvider,
  usesSharedOpenRouterCredential,
} from "../../api/providerCredentialPolicy.ts";
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
  const t = useTranslation();
  const { locale } = useLocale();
  const label = (capability: ProviderCapability) => t(capabilityLabel(capability));
  const [draft, setDraft] = useState(() => emptyProviderCredentialDraft(provider.capabilities));
  const [baseUrlDraft, setBaseUrlDraft] = useState(() => emptyProviderCredentialDraft(provider.capabilities));
  const [pending, setPending] = useState<"save" | "sync" | ProviderCapability | null>(null);
  const [notice, setNotice] = useState<ApiSpaceNotice>(null);
  const [testNotices, setTestNotices] = useState<CredentialNoticeByCapability>({});
  const [pendingClear, setPendingClear] = useState<ProviderCapability | null>(null);
  const hasSharedCredential = usesSharedOpenRouterCredential(provider);
  const updateRequest = useMemo(() => credentialUpdateFromDraft(draft, baseUrlDraft), [draft, baseUrlDraft]);
  const availableModelCount = models.filter((model) => (
    modelEligibility(model, "default").selectable
  )).length;

  const updateDraft = (capability: ProviderCapability, value: string) => {
    setDraft((current) => updateCredentialDraftForProvider(provider, current, capability, value));
    setNotice(null);
    setTestNotices((current) => ({ ...current, [capability]: null }));
  };

  const updateBaseUrlDraft = (capability: ProviderCapability, value: string) => {
    setBaseUrlDraft((current) => ({ ...current, [capability]: value }));
    setNotice(null);
  };

  const save = async () => {
    if (!updateRequest || pending) return;
    setPending("save");
    setNotice(null);
    try {
      const response = await api.updateProviderCredentials(provider.provider_id, updateRequest);
      onProviderUpdated(response.provider);
      setDraft(emptyProviderCredentialDraft(provider.capabilities));
      setBaseUrlDraft(emptyProviderCredentialDraft(provider.capabilities));
      setTestNotices({});
      setNotice({ kind: "success", message: t("{name} credentials saved.", { name: provider.display_name }) });
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
      const clearCapabilities = clearCapabilitiesForProvider(provider, capability);
      const response = await api.updateProviderCredentials(provider.provider_id, {
        api_keys: {},
        clear_capabilities: clearCapabilities,
      });
      onProviderUpdated(response.provider);
      setDraft((current) => Object.fromEntries(
        Object.entries(current).map(([draftCapability, value]) => [
          draftCapability,
          clearCapabilities.includes(draftCapability as ProviderCapability) ? "" : value,
        ]),
      ));
      setBaseUrlDraft((current) => Object.fromEntries(
        Object.entries(current).map(([draftCapability, value]) => [
          draftCapability,
          clearCapabilities.includes(draftCapability as ProviderCapability) ? "" : value,
        ]),
      ));
      setPendingClear(null);
      setNotice({
        kind: "success",
        message: hasSharedCredential
          ? t("OpenRouter credential cleared for Text and Image.")
          : t("{capability} credential cleared.", { capability: label(capability) }),
      });
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
        [capability]: { kind: "success", message: t("{capability} credential accepted.", { capability: label(capability) }) },
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
      setNotice({ kind: "success", message: t("Models synchronized.") });
    } catch (error) {
      setNotice({ kind: "error", message: providerRegistryErrorMessage(error, "sync") });
    } finally {
      setPending(null);
    }
  };

  return (
    <section className="api-space-provider-surface" aria-label={t("{name} provider settings", { name: provider.display_name })}>
      <header className="api-space-provider-header">
        <div>
          <span className="api-space-eyebrow">{t(provider.connection_state === "configured" ? "Configured provider" : "Provider")}</span>
          <h2>{provider.display_name}</h2>
        </div>
        <span className="api-space-local-badge">{t("Local settings")}</span>
      </header>

      <p className="api-space-intro">
        {t("Keys stay in the local backend. This browser receives configuration status only and never reads a saved key back.")}
      </p>

      <div className="api-space-credential-list">
        {hasSharedCredential ? (
          <section className="api-space-credential-row api-space-credential-row--shared">
            <div className="api-space-credential-copy">
              <h3>{t("OpenRouter API Key")}</h3>
              <p>{t("One key authorizes both Text and Image. Each capability keeps its own endpoint and readiness status.")}</p>
            </div>
            <div className="api-space-credential-control">
              <label className="sr-only" htmlFor={`${provider.provider_id}-shared-api-key`}>{t("OpenRouter API Key")}</label>
              <input
                id={`${provider.provider_id}-shared-api-key`}
                name={`${provider.provider_id}-shared-api-key`}
                type="password"
                value={draft.text ?? ""}
                placeholder={t("Paste a new OpenRouter API key")}
                autoComplete="new-password"
                disabled={Boolean(pending)}
                onChange={(event) => updateDraft("text", event.currentTarget.value)}
              />
              {provider.capabilities.some((capability) => provider.credentials[capability]?.configured) ? (
                <div className="api-space-credential-actions">
                  {pendingClear === "text" ? (
                    <span className="api-space-clear-confirmation">
                      {t("Clear the Text and Image credential?")}
                      <button className="small-action" type="button" disabled={Boolean(pending)} onClick={() => void clearCapability("text")}>
                        {t(pending === "text" ? "Clearing..." : "Confirm clear")}
                      </button>
                      <button className="small-action" type="button" disabled={Boolean(pending)} onClick={() => setPendingClear(null)}>{t("Cancel")}</button>
                    </span>
                  ) : (
                    <button className="small-action" type="button" disabled={Boolean(pending)} onClick={() => setPendingClear("text")}>
                      {t("Clear OpenRouter key")}
                    </button>
                  )}
                </div>
              ) : null}
            </div>
          </section>
        ) : null}
        {provider.capabilities.map((capability) => {
          const status = provider.credentials[capability];
          const isTesting = pending === capability && supportsCredentialTest(status);
          const isClearing = pending === capability && pendingClear === capability;
          const isBusy = Boolean(pending);
          return (
            <section className="api-space-credential-row" key={capability}>
              <div className="api-space-credential-copy">
                <h3>{t(hasSharedCredential ? "{capability} status" : "{capability} API Key", { capability: label(capability) })}</h3>
                <p>{translateUi(locale, capabilityDescription(capability))}</p>
                <CredentialStatus configured={status?.configured ?? false} fingerprint={status?.fingerprint ?? null} />
                {status?.endpoint ? <EndpointStatus capability={capability} endpoint={status.endpoint} /> : null}
              </div>
              <div className="api-space-credential-control">
                {!hasSharedCredential ? (
                  <>
                    <label className="sr-only" htmlFor={`${provider.provider_id}-${capability}-api-key`}>
                      {provider.display_name} {capabilityLabel(capability)} API Key
                    </label>
                    <input
                      id={`${provider.provider_id}-${capability}-api-key`}
                      name={`${provider.provider_id}-${capability}-api-key`}
                      type="password"
                      value={draft[capability] ?? ""}
                      placeholder={t("Paste a new API key")}
                      autoComplete="new-password"
                      disabled={isBusy}
                      onChange={(event) => updateDraft(capability, event.currentTarget.value)}
                    />
                  </>
                ) : null}
                <label className="sr-only" htmlFor={`${provider.provider_id}-${capability}-base-url`}>
                  {provider.display_name} {capabilityLabel(capability)} Base URL
                </label>
                <input
                  id={`${provider.provider_id}-${capability}-base-url`}
                  name={`${provider.provider_id}-${capability}-base-url`}
                  type="text"
                  value={baseUrlDraft[capability] ?? ""}
                  placeholder={baseUrlPlaceholder(status, locale)}
                  autoComplete="off"
                  spellCheck={false}
                  disabled={isBusy}
                  onChange={(event) => updateBaseUrlDraft(capability, event.currentTarget.value)}
                />
                <div className="api-space-credential-actions">
                  {supportsCredentialTest(status) ? (
                    <button
                      className="small-action"
                      type="button"
                      disabled={isBusy}
                      onClick={() => void testCredential(capability)}
                    >
                      {isTesting ? t("Testing...") : t("Test {capability} key", { capability: label(capability) })}
                    </button>
                  ) : <span className="api-space-test-unavailable">{t("Test unavailable")}</span>}
                  {status?.configured && !hasSharedCredential ? (
                    pendingClear === capability ? (
                      <span className="api-space-clear-confirmation">
                        {t("Clear this saved key?")}
                        <button className="small-action" type="button" disabled={isBusy} onClick={() => void clearCapability(capability)}>
                          {t(isClearing ? "Clearing..." : "Confirm clear")}
                        </button>
                        <button className="small-action" type="button" disabled={isBusy} onClick={() => setPendingClear(null)}>{t("Cancel")}</button>
                      </span>
                    ) : (
                      <button className="small-action" type="button" disabled={isBusy} onClick={() => setPendingClear(capability)}>
                        {t("Clear saved key")}
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
          {t("{available} available / {total} discovered models", { available: availableModelCount, total: models.length })}
        </span>
        <div className="api-space-save-actions">
          <button className="small-action" type="button" disabled={Boolean(pending)} onClick={() => void syncModels()}>
            {t(pending === "sync" ? "Syncing models..." : "Sync models")}
          </button>
          <button className="send-btn" type="button" disabled={!updateRequest || Boolean(pending)} onClick={() => void save()}>
            {pending === "save" ? t("Saving...") : t("Save {name} credentials", { name: provider.display_name })}
          </button>
        </div>
        {notice ? <InlineNotice notice={notice} /> : null}
      </footer>
    </section>
  );
}

function CredentialStatus({ configured, fingerprint }: { configured: boolean; fingerprint: string | null }) {
  const t = useTranslation();
  return configured
    ? <span className="api-space-credential-status is-configured">{t("Configured")}{fingerprint ? ` · ${fingerprint}` : ""}</span>
    : <span className="api-space-credential-status is-not-configured">{t("Not configured")}</span>;
}

function EndpointStatus({
  capability,
  endpoint,
}: {
  capability: ProviderCapability;
  endpoint: NonNullable<ProviderConnectionStatusV1["credentials"][ProviderCapability]>["endpoint"];
}) {
  const t = useTranslation();
  if (!endpoint) return null;
  return (
    <span className="api-space-credential-endpoint">
      {t("{capability} endpoint", { capability: t(capabilityLabel(capability)) })} · {endpoint.scheme}://{endpoint.host}{endpoint.path}
    </span>
  );
}

function InlineNotice({ notice }: { notice: Exclude<ApiSpaceNotice, null> }) {
  return <span className={`api-space-inline-notice is-${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>{notice.message}</span>;
}

function capabilityLabel(capability: ProviderCapability): "Text" | "Image" | "Video" | "Audio" {
  return ({ text: "Text", image: "Image", video: "Video", audio: "Audio" } as const)[capability];
}

function baseUrlPlaceholder(
  status: ProviderConnectionStatusV1["credentials"][ProviderCapability] | undefined,
  locale: string,
): string {
  const endpoint = status?.endpoint;
  if (endpoint) {
    return translateUi(locale, "Current: {url}", { url: `${endpoint.scheme}://${endpoint.host}${endpoint.path}` });
  }
  return translateUi(locale, "Base URL (leave empty to keep the provider default)");
}

function capabilityDescription(capability: ProviderCapability) {
  if (capability === "text") return "Used for planning, scripts, text nodes, and Agent work.";
  if (capability === "image") return "Used by image generation nodes.";
  if (capability === "video") return "Used by video generation nodes.";
  return "Used by audio and BGM generation nodes.";
}
