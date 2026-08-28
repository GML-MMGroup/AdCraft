import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const sourceRoot = resolve(process.cwd(), "src");
const source = (path: string) => readFileSync(resolve(sourceRoot, path), "utf8");

const interactionStyles = [
  "styles/base.css",
  "pages/home.css",
  "pages/home-typography-lab.css",
  "pages/projects.css",
  "pages/assets.css",
  "features/agent-canvas/agent-canvas-page.css",
  "features/agent-canvas/canvas/AgentCanvasConnectedNodeMenu.css",
  "features/agent-canvas/chat/agent-canvas-chat.css",
  "features/agent-canvas/assets/AgentAssetBrowser.css",
  "features/agent-canvas/documents/agent-canvas-documents.css",
  "features/agent-canvas/settings/agent-canvas-settings.css",
  "features/agent-canvas/workbench/agent-canvas-inline-workbench.css",
  "features/agent-canvas/editing/agent-canvas-editing.css",
].map(source).join("\n");

describe("blue brand interactions", () => {
  it("provides shared blue aliases for component-level accent styling", () => {
    const theme = source("styles/theme.css");

    expect(theme).toContain("--accent: var(--brand)");
    expect(theme).toContain("--accent-strong: var(--brand-hover)");
    expect(theme).toContain("--accent-soft: var(--brand-subtle)");
  });

  it("uses theme tokens for generic Home and Agent Canvas interactions", () => {
    expect(interactionStyles).toContain(
      "color-mix(in srgb, var(--brand) 30%, transparent)",
    );
    expect(interactionStyles).toContain("--agent-canvas-pointer-dot-color: #a3a3a3");
    expect(interactionStyles).toContain("background: var(--brand)");
    expect(interactionStyles).toContain("accent-color: var(--brand)");
    expect(interactionStyles).not.toMatch(
      /#(?:59458f|5e4fa5|65509b|67529d|6754a6|6755aa|6853ad|6d56b2|6e5ab0|6f5aae|6f62aa|705cb1|715cb1|725db4|7565b5|7662b8|7664b7|7667b8|7a6ac4|7b68bb|7e68c2|806dc2|8771cc|8873c9|8a70d2|8c79c9|8d76d4|9581d7|9e8bef|a894f5|a990f3|b3a4f5|c0b2f5|c9bcff|cfc4ff|ddd5ff|eae6ff)/i,
    );
    expect(interactionStyles).not.toMatch(/rgba\((?:108, 93, 171|109, 113, 214),/);
    expect(interactionStyles).not.toContain("rgb(124 102 200 /");
    expect(interactionStyles).not.toContain("rgb(111 96 168 /");
  });

  it("keeps non-chat primary actions branded while Agent Canvas chrome stays monochrome", () => {
    const canvas = source("features/agent-canvas/agent-canvas-page.css");
    const chat = source("features/agent-canvas/chat/agent-canvas-chat.css");
    const assets = source("features/agent-canvas/assets/AgentAssetBrowser.css");
    const editing = source("features/agent-canvas/editing/agent-canvas-editing.css");

    expect(canvas).toMatch(/\.agent-canvas-toolbar__run \{[^}]*color: #111 !important;[^}]*background: #e7e7e7 !important;/s);
    expect(canvas).toMatch(/\.agent-canvas-inspector__primary \{[^}]*color: var\(--text-inverse\);/s);
    expect(canvas).toMatch(/\.agent-canvas-inspector__save \{[^}]*color: var\(--text-inverse\);/s);
    expect(chat).toMatch(/\.agent-chat__revision button \{[^}]*background: var\(--agent-chat-primary\);[^}]*color: var\(--agent-chat-panel\);/s);
    expect(chat).toMatch(/\.agent-chat__composer-actions \.agent-chat__send \{[^}]*background: var\(--agent-chat-primary\);[^}]*color: var\(--agent-chat-panel\);/s);
    expect(assets).toMatch(/\.agent-asset-browser__upload \{[^}]*color: var\(--text-inverse\);/s);
    expect(assets).toMatch(/\.agent-asset-browser__add \{[^}]*color: var\(--text-inverse\) !important;/s);
    expect(editing).toMatch(/\.agent-editing-panel__export \{[^}]*color: #111;[^}]*background: #e7e7e7;/s);
  });

  it("keeps node-type and semantic color declarations unchanged", () => {
    const nodes = source("features/agent-canvas/canvas/AgentCanvasNode.css");
    const theme = source("styles/theme.css");

    expect(nodes).toContain("--agent-node-accent: #7465b5");
    expect(nodes).toContain("--agent-node-accent: #3f9c8e");
    expect(nodes).toContain("--agent-node-accent: #4d78d2");
    expect(theme).toContain("--success: #9CD38E");
    expect(theme).toContain("--warning: #E1A750");
    expect(theme).toContain("--error: #CA6F6F");
  });
});
