import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { HealthContext, type ApiConfigSummary, type HealthContextValue } from "./HealthContext";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "/api/v1").replace(/\/+$/, "");
const HYBRID_STORAGE_ERROR_EVENT = "hybrid-storage:error";
const CORE_CAPABILITIES = ["text", "image", "video", "audio"] as const;
const CONFIG_RECHECK_INTERVAL_MS = 60_000;

type HealthResponse = {
  service: string;
  mode: string;
};

type ProviderCredentialStatus = {
  configured?: boolean;
};

type ProvidersResponse = {
  items?: Array<{
    credentials?: Record<string, ProviderCredentialStatus | undefined>;
  }>;
};

type HybridStorageErrorDetail = {
  message?: string;
};

export function HealthProvider({ children }: { children: ReactNode }) {
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [apiMessage, setApiMessage] = useState("Checking FastAPI...");
  const [apiConfig, setApiConfig] = useState<ApiConfigSummary | null>(null);
  const [storageWarning, setStorageWarning] = useState<string | null>(null);

  const startNewProject = useCallback(async () => {
    const { resetNewProjectStorage } = await import("./startNewProject");
    await resetNewProjectStorage();
  }, []);

  const checkHealth = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/health`, {
        headers: { "Content-Type": "application/json" },
      });
      if (!response.ok) throw new Error("Health request failed");
      const health = await response.json() as HealthResponse;
      setApiOnline(true);
      setApiMessage(`${health.service} · ${health.mode}`);
    } catch {
      setApiOnline(false);
      setApiMessage("FastAPI is not reachable. Demo data is shown until the backend starts.");
    }
  }, []);

  const checkApiConfig = useCallback(async () => {
    // Configuration readiness (credentials configured in API Space) lives in
    // the provider registry and is independent of the liveness probe.
    try {
      const response = await fetch(`${API_BASE_URL}/providers`);
      if (!response.ok) {
        setApiConfig(null);
        return;
      }
      const payload = await response.json() as ProvidersResponse;
      const configured = new Set<string>();
      for (const provider of payload.items ?? []) {
        for (const [capability, credential] of Object.entries(provider.credentials ?? {})) {
          if (credential?.configured) configured.add(capability);
        }
      }
      const summary: ApiConfigSummary = {
        configured: CORE_CAPABILITIES.filter((capability) => configured.has(capability)),
        coreMissing: CORE_CAPABILITIES.filter((capability) => !configured.has(capability)),
      };
      setApiConfig(summary);
    } catch {
      setApiConfig(null);
    }
  }, []);

  const refresh = useCallback(() => {
    void checkHealth();
    void checkApiConfig();
  }, [checkApiConfig, checkHealth]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Keep the badge truthful: re-check when the user returns to the tab (e.g.
  // after saving credentials in API Space) and periodically while open.
  useEffect(() => {
    function handleFocus() {
      refresh();
    }
    window.addEventListener("focus", handleFocus);
    const interval = window.setInterval(refresh, CONFIG_RECHECK_INTERVAL_MS);
    return () => {
      window.removeEventListener("focus", handleFocus);
      window.clearInterval(interval);
    };
  }, [refresh]);

  useEffect(() => {
    function handleHybridStorageError(event: Event) {
      const detail = (event as CustomEvent<HybridStorageErrorDetail>).detail;
      setStorageWarning(detail?.message || "Local project storage failed. Recent changes may not persist after refresh.");
    }

    window.addEventListener(HYBRID_STORAGE_ERROR_EVENT, handleHybridStorageError as EventListener);
    return () => window.removeEventListener(HYBRID_STORAGE_ERROR_EVENT, handleHybridStorageError as EventListener);
  }, []);

  const value = useMemo<HealthContextValue>(() => ({
    apiOnline,
    apiMessage,
    apiConfig,
    storageWarning,
    startNewProject,
  }), [apiMessage, apiOnline, apiConfig, startNewProject, storageWarning]);

  return <HealthContext.Provider value={value}>{children}</HealthContext.Provider>;
}
