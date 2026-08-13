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

  test("uses the approved red, green, and yellow semantic palette across theme layers", () => {
    const themeStyles = source("styles/theme.css");
    const baseStyles = source("styles/base.css");
    const typographyLabStyles = source("pages/home-typography-lab.css");
    const light = declarationBlock(themeStyles, ':root[data-theme="light"]');
    const dark = declarationBlock(themeStyles, 'html[data-theme="dark"]');
    const base = declarationBlock(baseStyles, ":root");
    const baseDark = declarationBlock(baseStyles, 'html[data-theme="dark"]');
    const typographyLab = declarationBlock(
      typographyLabStyles,
      ".home-typography-lab--dark",
    );

    for (const block of [light, dark]) {
      expect(block).toContain("--success: #9CD38E");
      expect(block).toContain("--warning: #E1A750");
      expect(block).toContain("--error: #CA6F6F");
    }

    for (const block of [base, baseDark, typographyLab]) {
      expect(block).toContain("--butter: #E1A750");
      expect(block).toContain("--rose: #CA6F6F");
    }
    expect(typographyLab).toContain("--error: #CA6F6F");
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

    expect(textareaBlock).toContain("min-height: 60px");
    expect(textareaBlock).toContain("max-height: 120px");
    expect(textareaBlock).toContain("padding: 0 2px");
    expect(textareaBlock).toContain("line-height: 20px");
    expect(textareaBlock).toContain("overflow-y: hidden");
  });

  test("keeps chat timeline scrolling stable and contained", () => {
    const chatStyles = source("features/agent-canvas/chat/agent-canvas-chat.css");
    const shellBlock = declarationBlock(chatStyles, ".agent-chat__timeline-shell");
    const timelineBlock = declarationBlock(chatStyles, ".agent-chat__timeline");
    const jumpBlock = declarationBlock(chatStyles, ".agent-chat__jump-to-latest");

    expect(shellBlock).toContain("position: relative");
    expect(shellBlock).toContain("min-height: 0");
    expect(timelineBlock).toContain("scrollbar-gutter: stable");
    expect(timelineBlock).toContain("scrollbar-width: thin");
    expect(timelineBlock).toContain("overscroll-behavior: contain");
    expect(jumpBlock).toContain("position: absolute");
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

  test("keeps the dark theme brand logo in its illuminated hover treatment", () => {
    const themeStyles = source("styles/theme.css");
    const brandBlock = declarationBlock(
      themeStyles,
      'html[data-theme="dark"] .brand-logo',
    );

    expect(brandBlock).toContain("transform: scale(1.06)");
    expect(brandBlock).toContain("drop-shadow(0 0 16px rgba(180, 220, 255, 0.72))");
    expect(brandBlock).toContain("drop-shadow(0 0 28px rgba(202, 177, 255, 0.38))");
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

  test("keeps clear-glass navigation buttons inside the home navigation rail", () => {
    const themeStyles = source("styles/theme.css");
    const homeRail = declarationBlock(
      themeStyles,
      'html[data-theme="dark"]:has(.main-view[data-route="/"]) .floating-rail',
    );
    const homeRailItem = declarationBlock(
      themeStyles,
      'html[data-theme="dark"]:has(.main-view[data-route="/"]) .rail-item',
    );
    const homeActiveRailItem = declarationBlock(
      themeStyles,
      'html[data-theme="dark"]:has(.main-view[data-route="/"]) .rail-item.is-active',
    );
    const homeRailItemHover = declarationBlock(
      themeStyles,
      'html[data-theme="dark"]:has(.main-view[data-route="/"]) .rail-item:is(:hover, :focus-visible)',
    );

    expect(homeRail).toContain("background: rgba(255, 255, 255, 0.008)");
    expect(homeRail).toContain("border-color: rgba(255, 255, 255, 0.075)");
    expect(homeRail).toContain("blur(1.5px) saturate(114%) brightness(1.025)");
    expect(homeRail).toContain("box-shadow: 0 8px 22px rgba(0, 13, 24, 0.12)");
    expect(homeRailItem).toContain("background: rgba(255, 255, 255, 0.008)");
    expect(homeRailItem).toContain("border-color: rgba(255, 255, 255, 0.075)");
    expect(homeRailItem).toContain("blur(1.5px) saturate(114%) brightness(1.025)");
    expect(homeRailItem).toContain("box-shadow: 0 8px 22px rgba(0, 13, 24, 0.12)");
    expect(homeActiveRailItem).toContain("background: rgba(255, 255, 255, 0.018)");
    expect(homeActiveRailItem).toContain("border-color: rgba(255, 255, 255, 0.13)");
    expect(homeActiveRailItem).toContain("box-shadow: 0 11px 26px rgba(0, 13, 24, 0.17)");
    expect(homeActiveRailItem).not.toContain("transform:");
    expect(homeRailItemHover).toContain("transform: translateY(-1px)");
  });
});
