import { createContext } from "react";

export type HealthContextValue = {
  apiOnline: boolean | null;
  apiMessage: string;
  storageWarning: string | null;
  startNewProject: () => Promise<void>;
};

export const HealthContext = createContext<HealthContextValue | null>(null);
