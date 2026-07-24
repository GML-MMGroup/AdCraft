import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "/api/v1").replace(/\/+$/, "");
const HYBRID_STORAGE_ERROR_EVENT = "hybrid-storage:error";
const WORKSPACE_WORKFLOW_KEY = "ad-workflow-active-workflow";
const WORKSPACE_MESSAGES_KEY = "ad-workflow-copilot-messages";
const WORKSPACE_ACTIVE_PROJECT_KEY = "ad-workflow-active-project-id";
const LOCAL_WORKFLOW_SNAPSHOT_KEY = "ad-workflow-canvas:local-workflow";

type HealthResponse = {
  service: string;
  mode: string;
};

type HybridStorageErrorDetail = {
  message?: string;
};

type HealthContextValue = {
  apiOnline: boolean | null;
  apiMessage: string;
  storageWarning: string | null;
  startNewProject: () => void;
};

const HealthContext = createContext<HealthContextValue | null>(null);

export function HealthProvider({ children }: { children: ReactNode }) {
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [apiMessage, setApiMessage] = useState("Checking FastAPI...");
  const [storageWarning, setStorageWarning] = useState<string | null>(null);

  const startNewProject = useCallback(() => {
    try {
      window.localStorage.removeItem(WORKSPACE_WORKFLOW_KEY);
      window.localStorage.removeItem(WORKSPACE_MESSAGES_KEY);
      window.localStorage.removeItem(WORKSPACE_ACTIVE_PROJECT_KEY);
      window.localStorage.removeItem(LOCAL_WORKFLOW_SNAPSHOT_KEY);
    } catch {
      // Local browser storage is optional for the empty workflow draft.
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function checkHealth() {
      try {
        const response = await fetch(`${API_BASE_URL}/health`, {
          headers: { "Content-Type": "application/json" },
        });
        if (!response.ok) throw new Error("Health request failed");
        const health = await response.json() as HealthResponse;
        if (cancelled) return;
        setApiOnline(true);
        setApiMessage(`${health.service} · ${health.mode}`);
      } catch {
        if (cancelled) return;
        setApiOnline(false);
        setApiMessage("FastAPI is not reachable. Demo data is shown until the backend starts.");
      }
    }

    void checkHealth();
    return () => {
      cancelled = true;
    };
  }, []);

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
    storageWarning,
    startNewProject,
  }), [apiMessage, apiOnline, startNewProject, storageWarning]);

  return <HealthContext.Provider value={value}>{children}</HealthContext.Provider>;
}

export function useHealth() {
  const context = useContext(HealthContext);
  if (!context) throw new Error("useHealth must be used within HealthProvider");
  return context;
}
