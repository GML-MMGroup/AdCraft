import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, test } from "vitest";

const sourceRoot = resolve(process.cwd(), "src");
const requiredTokens = [
  "--page-bg",
  "--nav-bg",
  "--surface-card",
  "--surface-raised",
  "--surface-input",
  "--text-primary",
  "--text-secondary",
  "--text-disabled",
  "--border-default",
  "--border-strong",
  "--brand",
  "--brand-hover",
  "--brand-subtle",
  "--focus-ring",
  "--success",
  "--warning",
  "--error",
  "--info",
];

function source(path: string) {
  return readFileSync(resolve(sourceRoot, path), "utf8");
}

function declarationBlock(styles: string, selector: string) {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = styles.match(new RegExp(`${escapedSelector}\\s*\\{([\\s\\S]*?)\\n\\}`, "m"));
  expect(match, `missing ${selector} declaration`).not.toBeNull();
  return match?.[1] ?? "";
}

describe("theme styles", () => {
  test("defines every semantic token for light and deep ink themes", () => {
    const styles = source("styles/theme.css");
    const light = declarationBlock(styles, ':root[data-theme="light"]');
    const dark = declarationBlock(styles, 'html[data-theme="dark"]');

    for (const token of requiredTokens) {
      expect(light).toContain(token);
      expect(dark).toContain(token);
    }

    expect(dark).toContain("#08090D");
    expect(dark).toContain("#9E8BEA");
  });

  test("provides scoped dark coverage for every primary product surface", () => {
    for (const path of [
      "pages/home.css",
      "pages/projects.css",
      "pages/assets.css",
      "pages/api-space.css",
      "features/workflow/workflow.css",
      "features/workflow/final-composition/final-composition.css",
      "features/workflow/v2/screenplay/screenplay.css",
    ]) {
      expect(source(path)).toContain('html[data-theme="dark"]');
    }
  });

  test("keeps non-critical theme rules out of the initial style entry", () => {
    expect(source("main.tsx")).not.toContain('import "./styles/theme.css"');
    expect(source("components/Layout.tsx")).toContain('import "../styles/theme.css"');
  });

  test("scopes the static cosmic artwork to the dark Home shell", () => {
    const homeStyles = source("pages/home.css");
    const darkHomeShell = declarationBlock(
      homeStyles,
      'html[data-theme="dark"] .app-shell--home',
    );

    expect(darkHomeShell).toContain('url("/assets/home-dark-cosmic.webp")');
    expect(darkHomeShell).not.toMatch(/\bfixed\b/);
    expect(source("styles/base.css")).not.toContain("home-dark-cosmic.webp");
    expect(source("styles/theme.css")).not.toContain("home-dark-cosmic.webp");
  });
});
