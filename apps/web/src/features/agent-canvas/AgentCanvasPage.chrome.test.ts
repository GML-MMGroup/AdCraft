import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("AgentCanvasPage chrome", () => {
  it("hides the React Flow attribution panel", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/AgentCanvasPage.tsx"),
      "utf8",
    );

    expect(source).toContain("proOptions={{ hideAttribution: true }}");
  });

  it("suppresses the browser menu across the canvas while preserving the pane menu", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/AgentCanvasPage.tsx"),
      "utf8",
    );

    expect(source).toContain('className="agent-canvas-board"');
    expect(source).toContain('onContextMenu={(event) => event.preventDefault()}');
    expect(source).toContain("onPaneContextMenu={(event) => {");
    expect(source).toContain("onRelocate={openCanvasContextMenu}");
  });

  it("extends only the Workflow bottom inset without widening the canvas shell", () => {
    const baseCss = readFileSync(resolve(process.cwd(), "src/styles/base.css"), "utf8");
    const canvasCss = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/agent-canvas-page.css"),
      "utf8",
    );

    expect(baseCss).toContain("min-height: calc(100dvh - 16px)");
    expect(baseCss).toContain("margin: 16px auto 0");
    expect(canvasCss).toContain("height: calc(100dvh - var(--topbar-height) - 16px)");
  });

  it("keeps backend edges selectable and animates only the selected monochrome dash", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/AgentCanvasPage.tsx"),
      "utf8",
    );
    const canvasCss = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/agent-canvas-page.css"),
      "utf8",
    );

    expect(source).toContain("useEdgesState<Edge>([])");
    expect(source).toContain("onEdgesChange={onEdgesChange}");
    expect(source).toContain("deleteKeyCode={[\"Backspace\", \"Delete\"]}");
    expect(source).toContain("onEdgesDelete={deleteEdges}");
    expect(source).toContain("highlightNodeRelatedCanvasEdges(");
    expect(source).toContain("session.state.selectedNodeId");
    expect(canvasCss).toContain(".agent-canvas-board .react-flow__edge.selected .react-flow__edge-path");
    expect(canvasCss).toContain(".agent-canvas-board .react-flow__edge.is-node-related .react-flow__edge-path");
    expect(canvasCss).toContain("stroke-dasharray: 8 6");
    expect(canvasCss).toContain("animation: agent-canvas-selected-edge-flow 760ms linear infinite");
    expect(canvasCss).toContain("@keyframes agent-canvas-selected-edge-flow");
    expect(canvasCss).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.agent-canvas-board \.react-flow__edge\.selected \.react-flow__edge-path[\s\S]*?animation: none;/,
    );
  });

  it("restores canonical bindings immediately when a delete mutation fails", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/AgentCanvasPage.tsx"),
      "utf8",
    );

    expect(source).toMatch(
      /const recoverDeletedCanvasState = useCallback\(async \(\) => \{[\s\S]*?setNodes\(canonicalNodes\);[\s\S]*?setEdges\(\(current\) => reconcileSelectableCanvasEdges\(presentedEdges, current\)\);[\s\S]*?await refreshWorkflow\(\);/,
    );
  });
});
