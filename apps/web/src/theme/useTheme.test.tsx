import { afterEach, describe, expect, test } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useTheme } from "./useTheme";
import { THEME_STORAGE_KEY } from "./themePreference";

function ThemeProbe() {
  const { theme, toggleTheme } = useTheme();
  const nextTheme = theme === "light" ? "dark" : "light";

  return (
    <button type="button" aria-label={`Switch to ${nextTheme} theme`} onClick={toggleTheme}>
      {theme}
    </button>
  );
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
  document.documentElement.style.removeProperty("color-scheme");
});

describe("useTheme", () => {
  test("applies the saved theme and persists subsequent toggles", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");

    render(<ThemeProbe />);

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(screen.getByRole("button", { name: "Switch to light theme" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Switch to light theme" }));

    expect(document.documentElement.dataset.theme).toBe("light");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(screen.getByRole("button", { name: "Switch to dark theme" })).toBeTruthy();
  });
});
