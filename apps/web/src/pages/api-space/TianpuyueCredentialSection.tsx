import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../../api/client";
import {
  buildTianpuyueCredentialUpdateRequest,
  type TianpuyueCredentialStatus,
  type TianpuyueCredentialStatusResponse,
} from "../../apiSpace/tianpuyueCredentials";

type Notice = { kind: "success" | "error"; message: string } | null;

export function TianpuyueCredentialSection() {
  const [credentialStatus, setCredentialStatus] = useState<TianpuyueCredentialStatusResponse | null>(null);
  const [candidate, setCandidate] = useState("");
  const [isLoadingStatus, setIsLoadingStatus] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const statusRequestRef = useRef(0);

  const loadCredentialStatus = useCallback(async () => {
    const requestId = ++statusRequestRef.current;
    setIsLoadingStatus(true);
    setStatusError(null);

    try {
      const response = await api.getTianpuyueCredentialStatus();
      if (requestId !== statusRequestRef.current) return;
      setCredentialStatus(response);
    } catch (error) {
      if (requestId !== statusRequestRef.current) return;
      setStatusError(tianpuyueCredentialErrorMessage(error, "load"));
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

  const updateRequest = useMemo(
    () => buildTianpuyueCredentialUpdateRequest(candidate),
    [candidate],
  );
  const canSave = Boolean(updateRequest) && !isSaving;

  async function saveCredential() {
    if (!updateRequest || !canSave) return;
    setIsSaving(true);
    setNotice(null);

    try {
      const response = await api.updateTianpuyueCredentials(updateRequest);
      statusRequestRef.current += 1;
      setCredentialStatus(response);
      setCandidate("");
      setStatusError(null);
      setNotice({
        kind: "success",
        message: "Audio credential saved. New BGM requests use the updated configuration.",
      });
    } catch (error) {
      setNotice({
        kind: "error",
        message: tianpuyueCredentialErrorMessage(error, "save"),
      });
    } finally {
      setIsSaving(false);
    }
  }

  const audioStatus = credentialStatus?.credentials.audio;

  return (
    <section
      className="api-space-provider-surface api-space-provider-surface--tianpuyue"
      aria-label="Tianpuyue Music credentials"
    >
      <header className="api-space-provider-header">
        <div>
          <span className="api-space-eyebrow">Tianpuyue Music</span>
          <h2 id="tianpuyue-credentials-title">Audio credentials</h2>
        </div>
        <span className="api-space-local-badge">Local settings</span>
      </header>

      <p className="api-space-intro">
        This key is used for BGM generation. The local backend returns only a masked status after saving.
      </p>

      {statusError ? (
        <div className="api-space-status-error" role="alert">
          <span>{statusError}</span>
          <button
            className="small-action"
            type="button"
            onClick={() => void loadCredentialStatus()}
            disabled={isLoadingStatus}
          >
            Reload Tianpuyue status
          </button>
        </div>
      ) : null}

      <div className="api-space-credential-list" aria-busy={isLoadingStatus}>
        <section className="api-space-credential-row" aria-labelledby="audio-api-key-label">
          <div className="api-space-credential-copy">
            <h3 id="audio-api-key-label">Audio API Key</h3>
            <p>Used by Tianpuyue music generation for new BGM requests.</p>
            <TianpuyueCredentialStatusView status={audioStatus} loading={isLoadingStatus} />
          </div>

          <div className="api-space-credential-control">
            <label htmlFor="audio-api-key" className="sr-only">
              Audio API Key
            </label>
            <input
              id="audio-api-key"
              name="audio-api-key"
              type="password"
              value={candidate}
              placeholder="Paste a new Audio API key"
              autoComplete="new-password"
              disabled={isSaving}
              onChange={(event) => {
                setCandidate(event.target.value);
                setNotice(null);
              }}
            />
            <div className="api-space-credential-actions">
              <span className="api-space-test-unavailable">Test unavailable</span>
            </div>
          </div>
        </section>
      </div>

      <footer className="api-space-save-bar">
        <div className="api-space-save-actions">
          <button
            className="send-btn"
            type="button"
            disabled={!canSave}
            onClick={() => void saveCredential()}
          >
            {isSaving ? "Saving Audio key..." : "Save Audio key"}
          </button>
        </div>
        {notice ? <TianpuyueInlineNotice notice={notice} /> : null}
      </footer>
    </section>
  );
}

function TianpuyueCredentialStatusView({
  status,
  loading,
}: {
  status: TianpuyueCredentialStatus | undefined;
  loading: boolean;
}) {
  if (loading && !status) {
    return <span className="api-space-credential-status">Loading configuration...</span>;
  }
  if (!status?.configured) {
    return <span className="api-space-credential-status is-not-configured">Not configured</span>;
  }

  return (
    <span className="api-space-credential-status is-configured">
      Configured <code>{status.masked_api_key ?? "********"}</code>
    </span>
  );
}

function TianpuyueInlineNotice({ notice }: { notice: Exclude<Notice, null> }) {
  return (
    <span
      className={`api-space-inline-notice is-${notice.kind}`}
      role={notice.kind === "error" ? "alert" : "status"}
    >
      {notice.message}
    </span>
  );
}

function tianpuyueCredentialErrorMessage(error: unknown, operation: "load" | "save") {
  const code = errorCode(error);
  if (code === "local_settings_access_denied") {
    return "This browser is not allowed to manage local credentials.";
  }
  if (code === "credential_status_failed") {
    return "The backend could not read Tianpuyue credential status.";
  }
  if (code === "credential_update_invalid") {
    return "Enter a valid non-empty Audio key without line breaks.";
  }
  if (code === "credential_update_conflict") {
    return "Another credential update is in progress. Try again shortly.";
  }
  if (code === "credential_persistence_failed" || code === "credential_runtime_reload_failed") {
    return "The backend could not apply this Audio credential update.";
  }
  if (error instanceof ApiError && error.status === 404 && operation === "load") {
    return "This backend does not provide Tianpuyue credential settings yet.";
  }
  if (error instanceof ApiError && error.status === 403) {
    return "This browser is not allowed to manage local credentials.";
  }
  return operation === "load"
    ? "Unable to load Tianpuyue credential status. Check that the local backend supports this provider."
    : "Unable to save the Audio credential. No changes were confirmed.";
}

function errorCode(error: unknown) {
  if (!(error instanceof ApiError) || !error.payload || typeof error.payload !== "object") return "";
  const detail = (error.payload as { detail?: unknown }).detail;
  return detail && typeof detail === "object" && typeof (detail as { code?: unknown }).code === "string"
    ? (detail as { code: string }).code
    : "";
}
