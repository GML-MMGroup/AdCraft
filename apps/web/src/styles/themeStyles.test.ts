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
  test("defines every semantic token once for the fixed dark theme", () => {
    const styles = source("styles/theme.css");
    const dark = declarationBlock(styles, ":root");

    for (const token of requiredTokens) {
      expect(dark).toContain(token);
    }

    expect(dark).toContain("#08090D");
    expect(dark).toContain("#9DAFE6");
    expect(styles).not.toContain("data-theme");
    expect(source("styles/base.css")).toContain("color-scheme: dark");
  });

  test("uses the approved blue brand palette and preserves semantic colors", () => {
    const theme = declarationBlock(source("styles/theme.css"), ":root");
    const base = declarationBlock(source("styles/base.css"), ":root");
    const typographyLab = declarationBlock(
      source("pages/home-typography-lab.css"),
      ".home-typography-lab--dark",
    );

    expect(theme).toContain("--brand: #9DAFE6");
    expect(theme).toContain("--brand-hover: #B2C0ED");
    expect(theme).toContain("--brand-subtle: #20283F");
    expect(theme).toContain("--focus-ring: #CAD4F5");
    expect(theme).toContain("--mauve: var(--brand)");
    expect(theme).toContain("--iris: var(--brand)");
    expect(base).toContain("--mauve: #9DAFE6");
    expect(base).toContain("--iris: #9DAFE6");
    expect(typographyLab).toContain("--brand: #9DAFE6");
    expect(theme).toContain("--success: #9CD38E");
    expect(theme).toContain("--warning: #E1A750");
    expect(theme).toContain("--error: #CA6F6F");
    expect(theme).toContain("--info: #7F9FE8");
    for (const block of [base, typographyLab]) {
      expect(block).toContain("--butter: #E1A750");
      expect(block).toContain("--rose: #CA6F6F");
    }
    expect(typographyLab).toContain("--error: #CA6F6F");
  });

  test("provides fixed dark coverage for every primary product surface", () => {
    for (const path of [
      "pages/home.css",
      "pages/projects.css",
      "pages/assets.css",
      "pages/api-space.css",
      "features/workflow/workflow.css",
      "features/workflow/final-composition/final-composition.css",
      "features/workflow/v2/screenplay/screenplay.css",
    ]) {
      expect(source(path)).toContain(":root");
      expect(source(path)).not.toContain("data-theme");
    }
  });

  test("keeps the chat composer textarea free of the global focus outline", () => {
    const chatStyles = source("features/agent-canvas/chat/agent-canvas-chat.css");
    const focusBlock = declarationBlock(
      chatStyles,
      ":root .agent-chat__composer textarea:focus-visible",
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
    expect(shellBlock).toContain("min-height: 56px");
    expect(shellBlock).toContain("flex: 1 1 72px");
    expect(timelineBlock).toContain("scrollbar-gutter: stable");
    expect(timelineBlock).toContain("scrollbar-width: thin");
    expect(timelineBlock).toContain("overscroll-behavior: contain");
    expect(jumpBlock).toContain("position: absolute");
  });

  test("uses a pure monochrome Agent Canvas background", () => {
    const canvasStyles = source("features/agent-canvas/agent-canvas-page.css");
    const pageBlock = declarationBlock(canvasStyles, ".agent-canvas-page");
    const boardBlock = declarationBlock(canvasStyles, ".agent-canvas-board");

    expect(pageBlock).toContain("background: #0a0a0a");
    expect(boardBlock).toContain("border-right: 1px solid #353535");
  });

  test("keeps the node prompt composer free of the global focus outline", () => {
    const workbenchStyles = source(
      "features/agent-canvas/workbench/agent-canvas-inline-workbench.css",
    );
    const focusBlock = declarationBlock(
      workbenchStyles,
      ":root .agent-node-workbench__composer textarea:focus-visible",
    );

    expect(focusBlock).toContain("outline: none");
  });

  test("keeps the fixed dark brand logo in its illuminated treatment", () => {
    const themeStyles = source("styles/theme.css");
    const brandBlock = declarationBlock(
      themeStyles,
      ":root .brand-logo",
    );

    expect(brandBlock).toContain("transform: scale(1.06)");
    expect(brandBlock).toContain("drop-shadow(0 0 16px rgba(180, 220, 255, 0.72))");
    expect(brandBlock).toContain("drop-shadow(0 0 28px rgba(202, 177, 255, 0.38))");
  });

  test("loads fixed theme rules with the initial style entry", () => {
    expect(source("main.tsx")).toContain('import "./styles/theme.css"');
    expect(source("components/Layout.tsx")).not.toContain('import "../styles/theme.css"');
  });

  test("keeps cosmic artwork fixed behind every application shell", () => {
    const themeStyles = source("styles/theme.css");
    const shell = declarationBlock(themeStyles, ":root .app-shell");
    const cosmicShell = declarationBlock(
      themeStyles,
      ":root .app-shell--cosmic",
    );

    expect(themeStyles).toMatch(
      /:root body\s*\{[\s\S]*?url\("\/assets\/home-dark-black-hole\.webp"\) 50% 60% \/ cover fixed no-repeat,[\s\S]*?\n\}/,
    );
    expect(shell).toContain("background: transparent");
    expect(cosmicShell).toContain("background: transparent");
    expect(cosmicShell).not.toContain("border-color");
    expect(cosmicShell).toContain("box-shadow: none");
    expect(source("styles/base.css")).not.toContain("home-dark-black-hole.webp");
    expect(source("pages/home.css")).not.toContain("home-dark-black-hole.webp");
    expect(source("pages/home-typography-lab.css")).toContain(
      'url("/assets/home-dark-black-hole.webp") 50% 60% / cover scroll no-repeat',
    );
    expect(source("pages/home-typography-lab.css")).not.toContain(
      "home-dark-cosmic.webp",
    );
    expect(themeStyles).toContain("background-position: 50% 63%");
  });

  test("shares the home clear-glass navigation rail across primary content routes", () => {
    const themeStyles = source("styles/theme.css");
    const homeRail = declarationBlock(
      themeStyles,
      ":root .floating-rail--clear-glass",
    );
    const homeRailItem = declarationBlock(
      themeStyles,
      ":root .clear-glass-control",
    );
    const homeActiveRailItem = declarationBlock(
      themeStyles,
      ":root .clear-glass-control.is-active",
    );
    const homeRailItemHover = declarationBlock(
      themeStyles,
      ":root .clear-glass-control:is(:hover, :focus-visible)",
    );

    expect(homeRail).toContain("background: rgba(255, 255, 255, 0.008)");
    expect(homeRail).toContain("border-color: rgba(255, 255, 255, 0.075)");
    expect(homeRail).toContain("blur(1.5px) saturate(114%) brightness(1.025)");
    expect(homeRail).toContain("box-shadow: 0 8px 22px rgba(0, 13, 24, 0.12)");
    expect(homeRailItem).toContain("background: rgba(255, 255, 255, 0.008)");
    expect(homeRailItem).toContain("border-color: rgba(255, 255, 255, 0.075)");
    expect(homeRailItem).toContain("blur(1.5px) saturate(114%) brightness(1.025)");
    expect(homeRailItem).toContain("box-shadow: 0 8px 22px rgba(0, 13, 24, 0.12)");
    expect(homeActiveRailItem).toContain("background: color-mix(in srgb, #9DAFE6 10%, transparent)");
    expect(homeActiveRailItem).toContain("#9DAFE6 62%");
    expect(homeActiveRailItem).toContain("0 0 20px color-mix(in srgb, #9DAFE6 36%, transparent)");
    expect(homeActiveRailItem).not.toContain("transform:");
    expect(homeRailItemHover).toContain("transform: translateY(-1px)");
    expect(homeRailItemHover).toContain("#9DAFE6 54%");
    expect(homeRailItemHover).toContain("0 0 16px color-mix(in srgb, #9DAFE6 28%, transparent)");

    const layout = source("components/Layout.tsx");
    expect(layout).toContain('"/projects", "/assets", "/trash"');
    expect(layout).toContain('location.pathname.startsWith("/workflow")');
    expect(layout).toContain('floating-rail--clear-glass');
  });

  test("hides the project search placeholder on focus and uses the approved caret color", () => {
    const themeStyles = source("styles/theme.css");
    const projectStyles = source("pages/projects.css");
    const selectedControl = declarationBlock(themeStyles, ":root .clear-glass-control.is-active");
    const searchBox = declarationBlock(projectStyles, ".projects-toolbar .search-box");
    const interactiveSearchBox = declarationBlock(
      projectStyles,
      ".projects-toolbar .search-box.clear-glass-control.is-active:is(:hover, :focus, :focus-visible, :active)",
    );

    expect(searchBox).toContain("caret-color: #9DAFE6");
    expect(searchBox).not.toContain("border-color");
    for (const selectedStyle of [
      "border-color: color-mix(in srgb, #9DAFE6 62%, rgba(255, 255, 255, 0.13))",
      "background: color-mix(in srgb, #9DAFE6 10%, transparent)",
      "0 0 0 1px color-mix(in srgb, #9DAFE6 22%, transparent)",
      "0 0 20px color-mix(in srgb, #9DAFE6 36%, transparent)",
    ]) {
      expect(selectedControl).toContain(selectedStyle);
      expect(interactiveSearchBox).toContain(selectedStyle);
    }
    expect(interactiveSearchBox).toContain("transform: none");
    expect(declarationBlock(projectStyles, ".projects-toolbar .search-box:focus::placeholder")).toContain("color: transparent");
  });

  test("keeps the new project card on the shared clear-glass control treatment", () => {
    const projectStyles = source("pages/projects.css");
    const createCard = declarationBlock(projectStyles, ":root .create-card--new-project.clear-glass-control");
    const createCardPlus = declarationBlock(projectStyles, ":root .create-card--new-project .create-plus");

    expect(createCard).toContain("color: rgba(255, 255, 255, 0.8)");
    expect(createCardPlus).toContain("width: 48px");
    expect(createCardPlus).toContain("height: 48px");
    expect(createCardPlus).toContain("border-radius: 50%");
    expect(createCardPlus).toContain("background: rgba(255, 255, 255, 0.12)");
    expect(createCardPlus).toContain("color: currentColor");
  });
});
