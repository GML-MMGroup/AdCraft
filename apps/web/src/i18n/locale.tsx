import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

export type AppLocale = "zh-CN" | "en-US";
const STORAGE_KEY = "adcraft.locale";

function readLocale(initialLocale?: AppLocale): AppLocale {
  if (typeof window === "undefined") return initialLocale ?? "en-US";
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "en-US" || stored === "zh-CN") return stored;
  } catch {
    // Browser preferences still work when storage is unavailable.
  }
  if (initialLocale) return initialLocale;
  for (const language of [...window.navigator.languages, window.navigator.language]) {
    if (/^zh(?:-|$)/i.test(language)) return "zh-CN";
    if (/^en(?:-|$)/i.test(language)) return "en-US";
  }
  return "en-US";
}

export function isChineseLocale(locale: string | null | undefined): boolean {
  return String(locale ?? "").toLowerCase().startsWith("zh");
}

type LocaleContextValue = {
  locale: AppLocale;
  setLocale: (locale: AppLocale) => void;
  toggleLocale: () => void;
};

const LocaleContext = createContext<LocaleContextValue | null>(null);
const standaloneLocale: LocaleContextValue = {
  locale: "en-US",
  setLocale: () => undefined,
  toggleLocale: () => undefined,
};

export function LocaleProvider({ children, initialLocale }: { children: ReactNode; initialLocale?: AppLocale }) {
  const [locale, setLocaleState] = useState<AppLocale>(() => readLocale(initialLocale));
  const localeRef = useRef(locale);
  const setLocale = useCallback((next: AppLocale) => {
    if (next === localeRef.current) return;
    localeRef.current = next;
    setLocaleState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // The in-memory preference still works when browser storage is unavailable.
    }
  }, []);
  const toggleLocale = useCallback(() => setLocale(localeRef.current === "zh-CN" ? "en-US" : "zh-CN"), [setLocale]);
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);
  const value = useMemo(() => ({ locale, setLocale, toggleLocale }), [locale, setLocale, toggleLocale]);
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale() {
  return useContext(LocaleContext) ?? standaloneLocale;
}

/** A mounted app uses its explicit preference; isolated consumers retain their supplied locale. */
export function useUiLocale(fallback = "en-US"): string {
  return useContext(LocaleContext)?.locale ?? fallback;
}

export { localeText } from "./messages.ts";
