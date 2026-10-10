import { useEffect, useState, type ReactNode } from "react";
import { ConnectionEffectContext } from "./connectionEffectContext";
import { createConnectionEffectStore } from "./connectionEffectStore";
import "./connection-effects.css";
export function ConnectionEffectsProvider({ children }: { children: ReactNode }) {
  const [store] = useState(createConnectionEffectStore);
  useEffect(() => () => store.clear(), [store]);
  return <ConnectionEffectContext.Provider value={store}>{children}</ConnectionEffectContext.Provider>;
}
