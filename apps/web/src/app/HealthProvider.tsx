import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { HealthContext, type HealthContextValue } from "./HealthContext";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "/api/v1").replace(/\/+$/, "");
const HYBRID_STORAGE_ERROR_EVENT = "hybrid-storage:error";

type HealthResponse = {
  service: string;
  mode: string;
};

type HybridStorageErrorDetail = {
  message?: string;
};

export function HealthProvider({ children }: { children: ReactNode }) {
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [apiMessage, setApiMessage] = useState("Checking FastAPI...");
  const [storageWarning, setStorageWarning] = useState<string | null>(null);

  const startNewProject = useCallback(async () => {
    const { resetNewProjectStorage } = await import("./startNewProject");
    await resetNewProjectStorage();
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
