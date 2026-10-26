import { createContext, useContext } from "react";
import type { ModeId } from "./ModeChoicePanel";

export interface ModeLaunch {
  begin: (mode: ModeId, projectId: string, keyboard: boolean) => void;
  ready: () => void;
  finish: () => void;
  revealing: boolean;
  preparing: boolean;
  keyboard: boolean;
}
export const ModeLaunchContext = createContext<ModeLaunch | null>(null);
export const useModeLaunch = () => useContext(ModeLaunchContext);
