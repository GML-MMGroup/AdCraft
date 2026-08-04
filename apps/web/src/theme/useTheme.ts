import { useCallback, useLayoutEffect, useState } from "react";
import {
  applyTheme,
  readThemePreference,
  type Theme,
  writeThemePreference,
} from "./themePreference";

function browserStorage() {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

function initialTheme(): Theme {
  if (typeof window === "undefined") return "light";
  return readThemePreference(browserStorage());
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useLayoutEffect(() => {
    applyTheme(document, theme);
  }, [theme]);

  const toggleTheme = useCallback(() => {
    const nextTheme: Theme = theme === "light" ? "dark" : "light";
    setTheme(nextTheme);
    writeThemePreference(browserStorage(), nextTheme);
  }, [theme]);

  return { theme, toggleTheme };
}
