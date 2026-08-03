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

  test("keeps the chat composer textarea free of the global focus outline", () => {
    const chatStyles = source("features/agent-canvas/chat/agent-canvas-chat.css");
    const focusBlock = declarationBlock(
      chatStyles,
      'html[data-theme="dark"] .agent-chat__composer textarea:focus-visible',
    );

    expect(focusBlock).toContain("outline: none");
  });

  test("grows the chat composer from three to exactly six full lines", () => {
    const chatStyles = source("features/agent-canvas/chat/agent-canvas-chat.css");
    const textareaBlock = declarationBlock(chatStyles, ".agent-chat__composer textarea");

    expect(textareaBlock).toContain("min-height: 68px");
    expect(textareaBlock).toContain("max-height: 125px");
    expect(textareaBlock).toContain("padding: 5px 2px 6px");
    expect(textareaBlock).toContain("line-height: 19px");
    expect(textareaBlock).toContain("overflow-y: hidden");
  });

  test("keeps the node prompt composer free of the global focus outline", () => {
    const workbenchStyles = source(
      "features/agent-canvas/workbench/agent-canvas-inline-workbench.css",
    );
    const focusBlock = declarationBlock(
      workbenchStyles,
      'html[data-theme="dark"] .agent-node-workbench__composer textarea:focus-visible',
    );

    expect(focusBlock).toContain("outline: none");
  });

  test("keeps non-critical theme rules out of the initial style entry", () => {
    expect(source("main.tsx")).not.toContain('import "./styles/theme.css"');
    expect(source("components/Layout.tsx")).toContain('import "../styles/theme.css"');
  });

  test("scopes the static cosmic artwork to shared dark non-Workflow shells", () => {
    const themeStyles = source("styles/theme.css");
    const darkCosmicShell = declarationBlock(
      themeStyles,
      'html[data-theme="dark"] .app-shell--cosmic',
    );

    expect(darkCosmicShell).toContain('url("/assets/home-dark-cosmic.webp")');
    expect(darkCosmicShell).not.toMatch(/\bfixed\b/);
    expect(source("styles/base.css")).not.toContain("home-dark-cosmic.webp");
    expect(source("pages/home.css")).not.toContain("home-dark-cosmic.webp");
  });
});
