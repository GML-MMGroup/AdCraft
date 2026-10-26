import { useSyncExternalStore } from "react";

const query = "(prefers-reduced-motion: reduce)";
function subscribe(callback: () => void) {
  const media = window.matchMedia?.(query);
  media?.addEventListener("change", callback);
  document.addEventListener("visibilitychange", callback);
  return () => {
    media?.removeEventListener("change", callback);
    document.removeEventListener("visibilitychange", callback);
  };
}
const snapshot = () => !window.matchMedia?.(query).matches && document.visibilityState !== "hidden";
export function useEnergyMotion() {
  return useSyncExternalStore(subscribe, snapshot, () => false);
}
