import { createContext } from "react";

export type ApiConfigSummary = {
  /** Capabilities (text/image/video/audio) with configured credentials. */
  configured: string[];
  /** Core capabilities that are still missing credentials. */
  coreMissing: string[];
};

export type HealthContextValue = {
  apiOnline: boolean | null;
  apiMessage: string;
  /** Configuration readiness from /api/v1/providers; null while unknown. */
  apiConfig: ApiConfigSummary | null;
  storageWarning: string | null;
  startNewProject: () => Promise<void>;
};

export const HealthContext = createContext<HealthContextValue | null>(null);
