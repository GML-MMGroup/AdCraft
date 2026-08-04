import { afterEach, describe, expect, test } from "vitest";
import {
  applyTheme,
  readThemePreference,
  THEME_STORAGE_KEY,
  writeThemePreference,
} from "./themePreference";

class ThrowingStorage implements Storage {
  get length() {
    return 0;
  }

  clear() {
    throw new Error("storage unavailable");
  }

  getItem() {
    throw new Error("storage unavailable");
  }

  key() {
    return null;
  }

  removeItem() {
    throw new Error("storage unavailable");
  }

  setItem() {
    throw new Error("storage unavailable");
  }
}

afterEach(() => {
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
  document.documentElement.style.removeProperty("color-scheme");
});

describe("theme preference", () => {
  test("defaults to light and accepts only the stored dark preference", () => {
    expect(readThemePreference(window.localStorage)).toBe("light");

    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    expect(readThemePreference(window.localStorage)).toBe("dark");

    window.localStorage.setItem(THEME_STORAGE_KEY, "system");
    expect(readThemePreference(window.localStorage)).toBe("light");
  });

  test("keeps the active theme usable when storage is unavailable", () => {
    const storage = new ThrowingStorage();

    expect(readThemePreference(storage)).toBe("light");
    expect(() => writeThemePreference(storage, "dark")).not.toThrow();
  });

  test("writes the document theme and browser color scheme", () => {
    applyTheme(document, "dark");

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.style.colorScheme).toBe("dark");
  });
});
