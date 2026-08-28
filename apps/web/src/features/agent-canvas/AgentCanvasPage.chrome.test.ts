import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("AgentCanvasPage chrome", () => {
  it("hides the React Flow attribution panel", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/AgentCanvasPageSurface.tsx"),
      "utf8",
    );

    expect(source).toContain("proOptions={{ hideAttribution: true }}");
  });

  it("uses a monochrome treatment for the workflow toolbar and add-node menu", () => {
    const canvasCss = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/agent-canvas-page.css"),
      "utf8",
    );

    expect(canvasCss).toMatch(
      /\.agent-canvas-toolbar \{[\s\S]*?color: #dedede;[\s\S]*?background: #151515;[\s\S]*?border: 1px solid #353535;/,
    );
    expect(canvasCss).toMatch(
      /\.agent-canvas-toolbar__run \{[\s\S]*?color: #111 !important;[\s\S]*?background: #e7e7e7 !important;/,
    );
    expect(canvasCss).toMatch(
      /\.agent-canvas-node-picker \{[\s\S]*?background: #1d1d1d;[\s\S]*?border: 1px solid #3a3a3a;/,
    );
  });

  it("uses one monochrome panel for the canvas context menu and node picker", () => {
    const canvasCss = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/agent-canvas-page.css"),
      "utf8",
    );

    expect(canvasCss).toMatch(
      /\.agent-canvas-context-menu \{[\s\S]*?color: #dedede;[\s\S]*?background: #151515;[\s\S]*?border: 1px solid #353535;/,
    );
    expect(canvasCss).toMatch(
      /\.agent-canvas-context-menu__action:hover,[\s\S]*?background: #303030;/,
    );
    expect(canvasCss).toMatch(
      /\.agent-canvas-context-menu__node-picker \{[\s\S]*?background: transparent;[\s\S]*?border: 0;[\s\S]*?border-radius: 0;/,
    );
  });

  it("suppresses the browser menu across the canvas while preserving the pane menu", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/AgentCanvasPageSurface.tsx"),
      "utf8",
    );

    expect(source).toContain(
      'className={`agent-canvas-board${layoutPreview.active ? " is-layout-previewing" : ""}${canvasInteracting ? " is-interacting" : ""}`}',
    );
    expect(source).toContain('onContextMenu={(event) => event.preventDefault()}');
    expect(source).toContain("onPaneContextMenu={(event) => {");
    expect(source).toContain("onRelocate={openCanvasContextMenu}");
  });

  it("fills the Workflow viewport below the topbar without a shell inset", () => {
    const baseCss = readFileSync(resolve(process.cwd(), "src/styles/base.css"), "utf8");
    const canvasCss = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/agent-canvas-page.css"),
      "utf8",
    );

    expect(baseCss).toContain("min-height: 100dvh");
    expect(baseCss).toContain("margin: 0");
    expect(canvasCss).toContain("height: calc(100dvh - var(--topbar-height))");
    expect(canvasCss).not.toContain("var(--topbar-height) - 16px");
  });

  it("tracks responsive content padding without horizontal overflow or a mobile gap", () => {
    const baseCss = readFileSync(resolve(process.cwd(), "src/styles/base.css"), "utf8");
    const canvasCss = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/agent-canvas-page.css"),
      "utf8",
    );

    expect(canvasCss).toMatch(
      /@media \(max-width: 900px\)[\s\S]*?\.agent-canvas-page,[\s\S]*?\.agent-canvas-state[\s\S]*?margin: 0 -18px -48px -80px;/,
    );
    expect(baseCss).toMatch(
      /@media \(max-width: 620px\)[\s\S]*?:root \{[\s\S]*?--topbar-height: 64px;/,
    );
  });

  it("keeps backend edges selectable and animates only the selected monochrome dash", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/AgentCanvasPageSurface.tsx"),
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
      resolve(process.cwd(), "src/features/agent-canvas/AgentCanvasPageSurface.tsx"),
      "utf8",
    );

    expect(source).toMatch(
      /const recoverDeletedCanvasState = useCallback\(async \(\) => \{[\s\S]*?setNodes\(presentedNodes\);[\s\S]*?setEdges\(\(current\) => reconcileSelectableCanvasEdges\(presentedEdges, current\)\);[\s\S]*?await refreshWorkflow\(\);/,
    );
  });

  it("integrates one-click layout as a reversible node preview", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/AgentCanvasPageSurface.tsx"),
      "utf8",
    );

    expect(source).toContain("computeAgentCanvasAutoLayout(");
    expect(source).toContain("useAgentCanvasLayoutPreview(");
    expect(source).toContain("<AgentCanvasLayoutConfirmation");
    expect(source).toContain("nodesDraggable={!layoutPreview.active}");
    expect(source).toContain(
      'className={`agent-canvas-board${layoutPreview.active ? " is-layout-previewing" : ""}${canvasInteracting ? " is-interacting" : ""}`}',
    );
    expect(source).toContain("<LayoutIcon />");
    expect(source).toContain('aria-label="Organize canvas"');
    expect(source).toContain("updateNodePositions");
    expect(source).toContain("rollbackPositions: rollbackNodePositions");
    expect(source).not.toContain("layoutKeepSucceededRef");
  });

  it("repairs overlapping persisted node positions during initial hydration", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/AgentCanvasPageSurface.tsx"),
      "utf8",
    );

    expect(source).toContain("needsInitialCanvasLayout(visibleCanonicalNodes.map((node) => node.data.node))");
    expect(source).toContain("initialLayoutRepairWorkflowIdsRef");
    expect(source).toContain("readAgentCanvasViewport(workflowId)");
    expect(source).toMatch(
      /computeAgentCanvasAutoLayout\([\s\S]*?enabledNodeLayoutEdges\(workflow\.bindings,[\s\S]*?updateNodePositions\(layoutResult\.positions\)[\s\S]*?fitView\(/,
    );
  });

  it("stages receipt nodes before rendering and reveals them through the progressive queue", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/AgentCanvasPageSurface.tsx"),
      "utf8",
    );
    const sessionSource = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/session/useAgentCanvasSession.ts"),
      "utf8",
    );
    const receiptStart = source.indexOf("const placeReceiptNodes");
    const receiptEnd = source.indexOf("const organizeCanvas", receiptStart);
    const receiptSource = source.slice(receiptStart, receiptEnd);

    expect(source).toContain("useAgentCanvasNodeRevealQueue");
    expect(source).toContain("reserveRevealNodeIds(receipt.created_node_ids)");
    expect(source).toContain("syncRevealCanonicalNodeIds(canonicalNodes.map((node) => node.id))");
    expect(source).toContain("visibleCanonicalNodes");
    expect(source).toContain("interruptReveal()");
    expect(sessionSource).toContain("buildAgentCanvasPreRevealLayout({");
    expect(sessionSource).toContain("await updateNodePositions(preRevealLayout.positions)");
    expect(sessionSource).not.toContain("planProgressiveNodePlacement({");
    expect(sessionSource).toMatch(
      /const preRevealLayout = buildAgentCanvasPreRevealLayout\([\s\S]*?applyWorkflow\(latest\.value\);[\s\S]*?await updateNodePositions\(preRevealLayout\.positions\);[\s\S]*?return preRevealLayout\.revealPlan;/,
    );
    expect(receiptSource).toContain("placeActionReceiptNodes(receipt)");
    expect(receiptSource).not.toContain("screenToFlowPosition({");
    expect(receiptSource).not.toContain("viewportAnchor");
    const receiptFailureSource = receiptSource.slice(receiptSource.indexOf(".catch((error) =>"));
    expect(receiptFailureSource).not.toContain("releaseRevealNodeIds(receipt.created_node_ids)");
  });

  it("animates node transforms only during layout preview and respects reduced motion", () => {
    const canvasCss = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/agent-canvas-page.css"),
      "utf8",
    );

    expect(canvasCss).toContain(".agent-canvas-board.is-layout-previewing .react-flow__node");
    expect(canvasCss).toContain("transition: transform 360ms cubic-bezier(.22, .72, .24, 1);");
    expect(canvasCss).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.agent-canvas-board\.is-layout-previewing \.react-flow__node[\s\S]*?transition: none;/,
    );
  });

  it("defers runtime node replacement until drag stop rebuilds the complete snapshot", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/AgentCanvasPageSurface.tsx"),
      "utf8",
    );

    expect(source).toContain("latestPresentedNodesRef");
    expect(source).toContain("pendingPresentedNodesRef");
    expect(source).toContain("deferNodeSnapshotDuringDrag(");
    expect(source).toContain("finishNodeDrag(");
    expect(source).toMatch(
      /const handleNodeChanges = useCallback\([\s\S]*?applyNodeChanges\(changes, current\)[\s\S]*?flowNodesRef\.current = next;[\s\S]*?return next;/,
    );
    expect(source).toMatch(
      /const dragResult = finishNodeDrag\([\s\S]*?pendingPresentedNodesRef\.current = null;[\s\S]*?setNodes\(dragResult\.nodes\);[\s\S]*?updateNodePositions\(dragResult\.positions\)/,
    );
  });

  it("cleans interrupted drag sessions and recovers failed layout persistence", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/AgentCanvasPageSurface.tsx"),
      "utf8",
    );

    expect(source).toContain("beginNodeDrag(");
    expect(source).toContain("cancelNodeDrag(");
    expect(source).toContain('window.addEventListener("blur", handleWindowBlur)');
    expect(source).toContain('document.addEventListener("visibilitychange", handleVisibilityChange)');
    expect(source).toContain("pointerSpotlight.onPointerCancel(event);");
    expect(source).toContain("clearCanvasInteractions();");
    expect(source).toContain("cancelActiveNodeDrag();");
    expect(source).toContain("dragCancellationPendingRef.current = true;");
    expect(source).toMatch(
      /onNodeDragStop=\{\(_event, node, draggedNodes\) => \{[\s\S]*?if \(dragCancellationPendingRef\.current\) \{[\s\S]*?dragCancellationPendingRef\.current = false;[\s\S]*?return;/,
    );
    expect(source).toMatch(
      /updateNodePositions\(dragResult\.positions\)[\s\S]*?catch\(\(\) => \{[\s\S]*?refreshWorkflow\(\)/,
    );
  });

  it("keeps workflow nodes mounted so media previews survive viewport changes", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/AgentCanvasPageSurface.tsx"),
      "utf8",
    );
    const nodeSource = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/canvas/AgentCanvasNode.tsx"),
      "utf8",
    );

    expect(source).toContain("onlyRenderVisibleElements={false}");
    expect(nodeSource).toContain("areAgentCanvasNodePropsEqual");
    expect(nodeSource).toMatch(
      /memo\(\s*AgentCanvasNodeRendererComponent,\s*areAgentCanvasNodePropsEqual,?\s*\)/,
    );
  });

  it("uses a lightweight visual mode only while the canvas is moving", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/AgentCanvasPageSurface.tsx"),
      "utf8",
    );
    const canvasCss = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/agent-canvas-page.css"),
      "utf8",
    );

    expect(source).toContain('canvasInteracting ? " is-interacting" : ""');
    expect(source).toContain('beginCanvasInteraction("viewport")');
    expect(source).toContain('endCanvasInteraction("viewport")');
    expect(source).toContain('beginCanvasInteraction("node-drag")');
    expect(source).toContain('endCanvasInteraction("node-drag")');
    expect(canvasCss).toContain(".agent-canvas-board.is-interacting .agent-canvas-node");
    expect(canvasCss).toContain(".agent-canvas-board.is-interacting .react-flow__edge-path");
    expect(canvasCss).toMatch(
      /\.agent-canvas-board\.is-interacting \.react-flow__edge\.selected \.react-flow__edge-path,[\s\S]*?filter: none;[\s\S]*?animation-play-state: paused;/,
    );
    expect(canvasCss).toContain("animation-play-state: paused");
    expect(canvasCss).toContain("backdrop-filter: none");
  });
});
