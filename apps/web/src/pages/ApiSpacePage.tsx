import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import {
  VOLCENGINE_CREDENTIAL_CONSUMERS,
  buildVolcengineCredentialUpdateRequest,
  emptyVolcengineCredentialDraft,
  hasVolcengineCredentialUpdate,
  supportsVolcengineCredentialTest,
  type VolcengineCredentialConsumer,
  type VolcengineCredentialDraft,
  type VolcengineCredentialStatusResponse,
  type VolcengineCredentialTestResponse,
} from "../apiSpace/volcengineCredentials";
import { PageHeader } from "../components/Layout";

type Notice = { kind: "success" | "error"; message: string } | null;
type CredentialTestState = Partial<Record<VolcengineCredentialConsumer, Notice>>;

const CREDENTIAL_LABELS: Record<VolcengineCredentialConsumer, { title: string; description: string }> = {
  llm: {
    title: "Text API Key",
    description: "Used for planning, scripts, prompt generation, and agent work.",
  },
  image: {
    title: "Image API Key",
    description: "Used by character, product, scene, and storyboard image generation.",
  },
  video: {
    title: "Video API Key",
    description: "Used by storyboard video generation.",
  },
};

export function ApiSpacePage() {
  const [credentialStatus, setCredentialStatus] = useState<VolcengineCredentialStatusResponse | null>(null);
  const [draft, setDraft] = useState<VolcengineCredentialDraft>(emptyVolcengineCredentialDraft);
  const [isLoadingStatus, setIsLoadingStatus] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [testingConsumer, setTestingConsumer] = useState<VolcengineCredentialConsumer | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [testState, setTestState] = useState<CredentialTestState>({});
  const statusRequestRef = useRef(0);

  const loadCredentialStatus = useCallback(async () => {
    const requestId = ++statusRequestRef.current;
    setIsLoadingStatus(true);
    setStatusError(null);

    try {
      const response = await api.getVolcengineCredentialStatus();
      if (requestId !== statusRequestRef.current) return;
      setCredentialStatus(response);
    } catch (error) {
      if (requestId !== statusRequestRef.current) return;
      setStatusError(credentialErrorMessage(error, "load"));
    } finally {
      if (requestId === statusRequestRef.current) setIsLoadingStatus(false);
    }
  }, []);

  useEffect(() => {
    void loadCredentialStatus();
    return () => {
      statusRequestRef.current += 1;
    };
  }, [loadCredentialStatus]);

  const updateRequest = useMemo(() => buildVolcengineCredentialUpdateRequest(draft), [draft]);
  const canSave = hasVolcengineCredentialUpdate(updateRequest) && !isSaving && !testingConsumer;

  function updateDraft(consumer: VolcengineCredentialConsumer, value: string) {
    setDraft((current) => ({ ...current, [consumer]: value }));
    setNotice(null);
    setTestState((current) => ({ ...current, [consumer]: null }));
  }

  function useTextKeyForAll() {
    if (!draft.llm.trim()) return;
    setDraft({ llm: draft.llm, image: draft.llm, video: draft.llm });
    setNotice(null);
    setTestState({});
  }

  async function saveCredentials() {
    if (!canSave) return;
    setIsSaving(true);
    setNotice(null);

    try {
      const response = await api.updateVolcengineCredentials(updateRequest);
      statusRequestRef.current += 1;
      setCredentialStatus(response);
      setDraft(emptyVolcengineCredentialDraft());
      setTestState({});
      setNotice({ kind: "success", message: "Credentials saved. New workflow requests use the updated configuration." });
    } catch (error) {
      setNotice({ kind: "error", message: credentialErrorMessage(error, "save") });
    } finally {
      setIsSaving(false);
    }
  }

  async function testCredential(consumer: VolcengineCredentialConsumer) {
    const status = credentialStatus?.credentials[consumer];
    if (!status || !supportsVolcengineCredentialTest(status.test_capability) || testingConsumer) return;

    const candidate = draft[consumer].trim();
    setTestingConsumer(consumer);
    setTestState((current) => ({ ...current, [consumer]: null }));

    try {
      const response = await api.testVolcengineCredential({
        consumer,
        ...(candidate ? { api_key: candidate } : {}),
      });
      setTestState((current) => ({ ...current, [consumer]: testResultNotice(response) }));
    } catch (error) {
      setTestState((current) => ({
        ...current,
        [consumer]: { kind: "error", message: credentialErrorMessage(error, "test") },
      }));
    } finally {
      setTestingConsumer(null);
    }
  }

  return (
    <section className="content-wrap api-space-page">
      <PageHeader title="API Space" subtitle="Local provider credentials for new workflow requests." />

      <section className="api-space-provider-surface" aria-labelledby="volcengine-credentials-title">
        <header className="api-space-provider-header">
          <div>
            <span className="api-space-eyebrow">Volcengine Ark</span>
            <h2 id="volcengine-credentials-title">Provider credentials</h2>
          </div>
          <span className="api-space-local-badge">Local settings</span>
        </header>

        <p className="api-space-intro">
          Keys are stored only by the local backend. Existing configured values are masked and cannot be read back into this browser.
        </p>

        {statusError ? (
          <div className="api-space-status-error" role="alert">
            <span>{statusError}</span>
            <button className="small-action" type="button" onClick={() => void loadCredentialStatus()} disabled={isLoadingStatus}>
              Reload status
            </button>
          </div>
        ) : null}

        <div className="api-space-credential-list" aria-busy={isLoadingStatus}>
          {VOLCENGINE_CREDENTIAL_CONSUMERS.map((consumer) => {
            const status = credentialStatus?.credentials[consumer];
            const testSupported = supportsVolcengineCredentialTest(status?.test_capability);
            const testResult = testState[consumer];
            const disabled = isSaving || testingConsumer === consumer;

            return (
              <section className="api-space-credential-row" key={consumer} aria-labelledby={`${consumer}-api-key-label`}>
                <div className="api-space-credential-copy">
                  <h3 id={`${consumer}-api-key-label`}>{CREDENTIAL_LABELS[consumer].title}</h3>
                  <p>{CREDENTIAL_LABELS[consumer].description}</p>
                  <CredentialStatus status={status} loading={isLoadingStatus} />
                </div>

                <div className="api-space-credential-control">
                  <label htmlFor={`${consumer}-api-key`} className="sr-only">
                    {CREDENTIAL_LABELS[consumer].title}
                  </label>
                  <input
                    id={`${consumer}-api-key`}
                    name={`${consumer}-api-key`}
                    type="password"
                    value={draft[consumer]}
                    placeholder="Paste a new API key"
                    autoComplete="new-password"
                    disabled={disabled}
                    onChange={(event) => updateDraft(consumer, event.target.value)}
                  />
                  <div className="api-space-credential-actions">
                    {testSupported ? (
                      <button
                        className="small-action"
                        type="button"
                        disabled={disabled}
                        onClick={() => void testCredential(consumer)}
                      >
                        {testingConsumer === consumer ? "Testing..." : "Test connection"}
                      </button>
                    ) : (
                      <span className="api-space-test-unavailable">Test unavailable</span>
                    )}
                    {testResult ? <InlineNotice notice={testResult} /> : null}
                  </div>
                </div>
              </section>
            );
          })}
        </div>

        <footer className="api-space-save-bar">
          <div className="api-space-save-actions">
            <button
              className="small-action"
              type="button"
              disabled={!draft.llm.trim() || isSaving || Boolean(testingConsumer)}
              onClick={useTextKeyForAll}
            >
              Use Text key for all
            </button>
            <button className="send-btn" type="button" disabled={!canSave} onClick={() => void saveCredentials()}>
              {isSaving ? "Saving..." : "Save credentials"}
            </button>
          </div>
          {notice ? <InlineNotice notice={notice} /> : null}
        </footer>
      </section>
    </section>
  );
}

function CredentialStatus({
  status,
  loading,
}: {
  status: VolcengineCredentialStatusResponse["credentials"][VolcengineCredentialConsumer] | undefined;
  loading: boolean;
}) {
  if (loading && !status) return <span className="api-space-credential-status">Loading configuration...</span>;
  if (!status || !status.configured) return <span className="api-space-credential-status is-not-configured">Not configured</span>;

  return (
    <span className="api-space-credential-status is-configured">
      Configured <code>{status.masked_api_key ?? "********"}</code>
    </span>
  );
}

function InlineNotice({ notice }: { notice: Exclude<Notice, null> }) {
  return <span className={`api-space-inline-notice is-${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>{notice.message}</span>;
}

function testResultNotice(response: VolcengineCredentialTestResponse): Exclude<Notice, null> {
  return {
    kind: response.accepted ? "success" : "error",
    message: response.accepted ? "Connection verified." : "Connection was not accepted.",
  };
}

function credentialErrorMessage(error: unknown, operation: "load" | "save" | "test") {
  const code = errorCode(error);
  if (code === "local_settings_access_denied") return "This browser is not allowed to manage local credentials.";
  if (code === "credential_update_invalid") return "Enter a valid non-empty key without line breaks.";
  if (code === "credential_update_conflict") return "Another credential update is in progress. Try again shortly.";
  if (code === "credential_persistence_failed" || code === "credential_runtime_reload_failed") return "The backend could not apply this credential update.";
  if (code === "credential_not_configured") return "Enter a key here or save one before testing.";
  if (code === "credential_test_not_supported") return "This provider capability cannot be safely tested here.";
  if (code === "credential_test_configuration_invalid") return "The backend test configuration is invalid.";
  if (code === "credential_test_failed") return "The provider rejected this credential.";
  if (code === "provider_test_unavailable") return "The provider is temporarily unavailable. Try again later.";

  if (error instanceof ApiError && error.status === 404 && operation === "load") {
    return "This backend does not provide local credential settings yet.";
  }
  if (error instanceof ApiError && error.status === 403) return "This browser is not allowed to manage local credentials.";
  return operation === "load"
    ? "Unable to load credential status. Check that the local backend is running."
    : operation === "save"
      ? "Unable to save credentials. No changes were confirmed."
      : "Unable to test this credential.";
}

function errorCode(error: unknown) {
  if (!(error instanceof ApiError) || !error.payload || typeof error.payload !== "object") return "";
  const detail = (error.payload as { detail?: unknown }).detail;
  return detail && typeof detail === "object" && typeof (detail as { code?: unknown }).code === "string"
    ? (detail as { code: string }).code
    : "";
}
