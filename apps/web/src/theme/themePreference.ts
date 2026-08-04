export const THEME_STORAGE_KEY = "adcraft-theme";

export type Theme = "light" | "dark";

export function readThemePreference(storage: Storage | undefined): Theme {
  try {
    return storage?.getItem(THEME_STORAGE_KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

export function writeThemePreference(storage: Storage | undefined, theme: Theme) {
  try {
    storage?.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Storage can be unavailable in privacy modes or when a browser quota is exhausted.
  }
}

export function applyTheme(target: Document, theme: Theme) {
  target.documentElement.dataset.theme = theme;
  target.documentElement.style.colorScheme = theme;
}
