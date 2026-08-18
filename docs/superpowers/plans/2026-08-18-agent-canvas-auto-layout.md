# Agent Canvas One-Click Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic one-click Agent Canvas layout that previews a left-to-right dependency graph and persists it only after the user explicitly chooses `保留`.

**Architecture:** A pure Dagre adapter calculates positions from visible nodes and persisted node Bindings. A dedicated preview hook overlays those positions over canonical workflow data without saving, while a focused confirmation component owns Keep/Undo dismissal semantics. `AgentCanvasPage` only coordinates React Flow measurements, viewport transitions, and the existing batch layout action.

**Tech Stack:** React 19, TypeScript, React Flow 12, `@dagrejs/dagre` 3.1.1, Vitest, Testing Library, Playwright/Chromium smoke verification.

## Global Constraints

- Implement in `/data/longwei.wu/AdCraft-worktrees/feat-agent-canvas-auto-layout` on `feat/agent-canvas-auto-layout`.
- Modify frontend code only under `apps/web`; do not modify `AdCraft/apps/api` or any backend repository.
- Use only enabled persisted node-output Bindings for graph topology; never infer or mutate edges.
- Arrange all visible nodes from left to right.
- Place connected components first and fully isolated nodes in a separate area below them.
- Use 140 px rank separation, 84 px node separation, 160 px component separation, 220 px isolated-section separation, and layout origin `(120, 120)`.
- Compute all optimization passes offscreen; render one 360 ms node transition and one 420 ms viewport transition.
- Preview locally and call the existing layout persistence action only after `保留`.
- `撤销`, outside click, Escape, workflow switch, and unmount must not save.
- Preserve node/edge selection, semantic revision, Bindings, prompts, media, runtime state, and execution behavior.
- Keep pan, zoom, and content inspection available during preview; disable node dragging until preview resolves.
- Respect `prefers-reduced-motion` by applying node and viewport changes immediately.
- Use test-first red/green cycles for every behavioral task.

---

### Task 1: Deterministic Layered Layout Module

**Files:**
- Modify: `apps/web/package.json`
- Modify: `apps/web/package-lock.json`
- Create: `apps/web/src/features/agent-canvas/canvas/canvasAutoLayout.ts`
- Create: `apps/web/src/features/agent-canvas/canvas/canvasAutoLayout.test.ts`

**Interfaces:**
- Consumes: `CanvasBindingV2`, `CanvasLayoutPositionV2`, `CanvasPositionV2`, and `AgentCanvasNodeSize`.
- Produces:

```ts
export interface AgentCanvasLayoutNode {
  id: string;
  position: CanvasPositionV2;
  size: AgentCanvasNodeSize;
}

export interface AgentCanvasLayoutEdge {
  id: string;
  source: string;
  target: string;
}

export interface AgentCanvasLayoutBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface AgentCanvasAutoLayoutResult {
  positions: CanvasLayoutPositionV2[];
  bounds: AgentCanvasLayoutBounds;
}

export function enabledNodeLayoutEdges(
  bindings: readonly CanvasBindingV2[],
  visibleNodeIds: ReadonlySet<string>,
): AgentCanvasLayoutEdge[];

export function computeAgentCanvasAutoLayout(
  nodes: readonly AgentCanvasLayoutNode[],
  edges: readonly AgentCanvasLayoutEdge[],
  options?: { isolatedRowWidth?: number },
): AgentCanvasAutoLayoutResult;
```

- Later tasks rely on the returned positions being complete, deterministic, top-left based, integer rounded, and sorted by node ID.

- [ ] **Step 1: Install the pinned layout engine**

Run:

```bash
cd apps/web
npm install @dagrejs/dagre@3.1.1
```

Expected: `package.json` contains `"@dagrejs/dagre": "^3.1.1"` and the lockfile resolves version `3.1.1`.

- [ ] **Step 2: Write failing topology and rank tests**

Create tests that establish the public API before implementation:

```ts
it("uses only enabled persisted node-output bindings", () => {
  const edges = enabledNodeLayoutEdges([
    binding("ab", "a", "b", { enabled: true }),
    binding("bc", "b", "c", { enabled: false }),
    assetBinding("asset-c", "asset-1", "c"),
  ], new Set(["a", "b", "c"]));

  expect(edges).toEqual([{ id: "ab", source: "a", target: "b" }]);
});

it("places dependencies in left-to-right ranks", () => {
  const result = computeAgentCanvasAutoLayout(
    [node("a"), node("b"), node("c")],
    [edge("ab", "a", "b"), edge("bc", "b", "c")],
  );
  const byId = positionsById(result.positions);

  expect(byId.a.x).toBeLessThan(byId.b.x);
  expect(byId.b.x).toBeLessThan(byId.c.x);
});
```

- [ ] **Step 3: Write failing geometry, component, and determinism tests**

Cover the approved edge cases with concrete assertions:

```ts
it("does not overlap differently sized nodes", () => {
  const result = computeAgentCanvasAutoLayout([
    node("portrait", { width: 180, height: 360 }),
    node("script", { width: 248, height: 500 }),
    node("video", { width: 272, height: 184 }),
  ], [edge("pv", "portrait", "video"), edge("sv", "script", "video")]);

  expect(overlappingPairs(result.positions, sizes)).toEqual([]);
});

it("packs isolated nodes below every connected component", () => {
  const result = computeAgentCanvasAutoLayout(
    [node("a"), node("b"), node("c"), node("isolated")],
    [edge("ab", "a", "b"), edge("bc", "b", "c")],
  );
  expect(topOf("isolated", result)).toBeGreaterThan(bottomOfConnected(result));
});

it("returns identical coordinates for identical shuffled input", () => {
  const first = computeAgentCanvasAutoLayout(nodes, edges);
  const second = computeAgentCanvasAutoLayout([...nodes].reverse(), [...edges].reverse());
  expect(second).toEqual(first);
});
```

Also cover empty input, one node, all-isolated nodes, two connected components, a branch/merge graph, and a historical cycle.

- [ ] **Step 4: Run the new tests and verify RED**

Run:

```bash
npm test -- --run src/features/agent-canvas/canvas/canvasAutoLayout.test.ts
```

Expected: FAIL because `canvasAutoLayout.ts` and its exports do not exist.

- [ ] **Step 5: Implement Binding filtering and stable component discovery**

Implement `enabledNodeLayoutEdges()` with these exact guards:

```ts
return bindings
  .filter((binding) => (
    binding.enabled
    && binding.source.kind === "node_output"
    && visibleNodeIds.has(binding.source.source_node_id)
    && visibleNodeIds.has(binding.target_node_id)
  ))
  .map((binding) => ({
    id: binding.binding_id,
    source: binding.source.kind === "node_output" ? binding.source.source_node_id : "",
    target: binding.target_node_id,
  }))
  .sort((left, right) => left.id.localeCompare(right.id));
```

Build undirected adjacency only for connected-component discovery. Sort every component and sort connected components by descending node count, descending internal edge count, then minimum node ID.

- [ ] **Step 6: Implement Dagre layout and component packing**

For each connected component, create a multigraph and configure:

```ts
graph.setGraph({
  rankdir: "LR",
  ranksep: 140,
  nodesep: 84,
  edgesep: 28,
  marginx: 0,
  marginy: 0,
  ranker: "network-simplex",
});
graph.setDefaultEdgeLabel(() => ({}));
```

Insert sorted nodes with explicit width and height, insert sorted edges with stable edge names, call `dagre.layout(graph)`, and convert center coordinates to top-left coordinates:

```ts
const position = {
  x: Math.round(layoutNode.x - node.size.width / 2),
  y: Math.round(layoutNode.y - node.size.height / 2),
};
```

Pack connected components vertically with 160 px separation. Place isolated nodes below with 220 px section separation, preserve their original top-to-bottom then left-to-right order, and wrap rows at `max(connectedWidth, options.isolatedRowWidth ?? 960)`.

Translate all positions to origin `(120, 120)`, compute complete bounds, and sort output positions by node ID.

- [ ] **Step 7: Run the layout tests and verify GREEN**

Run:

```bash
npm test -- --run src/features/agent-canvas/canvas/canvasAutoLayout.test.ts
```

Expected: all layout tests pass with no warnings.

- [ ] **Step 8: Run existing canvas model tests**

Run:

```bash
npm test -- --run \
  src/features/agent-canvas/canvas/canvasAutoLayout.test.ts \
  src/features/agent-canvas/canvas/canvasGraphModel.test.ts \
  src/features/agent-canvas/canvas/nodeGeometry.test.ts
```

Expected: all selected tests pass.

- [ ] **Step 9: Commit the layout engine**

```bash
git add apps/web/package.json apps/web/package-lock.json \
  apps/web/src/features/agent-canvas/canvas/canvasAutoLayout.ts \
  apps/web/src/features/agent-canvas/canvas/canvasAutoLayout.test.ts
git commit -m "feat(canvas): add deterministic auto layout engine"
```

---

### Task 2: Local Layout Preview Transaction

**Files:**
- Create: `apps/web/src/features/agent-canvas/canvas/useAgentCanvasLayoutPreview.ts`
- Create: `apps/web/src/features/agent-canvas/canvas/useAgentCanvasLayoutPreview.test.tsx`

**Interfaces:**
- Consumes: the current workflow ID, current Flow nodes, current viewport, target `CanvasLayoutPositionV2[]`, `updateNodePositions()`, and `setViewport()`.
- Produces:

```ts
export type AgentCanvasLayoutPreviewStatus =
  | "idle"
  | "previewing"
  | "saving"
  | "save_error";

export interface AgentCanvasLayoutPreviewStart<TNode> {
  workflowId: string;
  nodes: readonly TNode[];
  targetPositions: CanvasLayoutPositionV2[];
  viewport: Viewport;
}

export function overlayAgentCanvasLayoutPreview<TNode extends {
  id: string;
  position: CanvasPositionV2;
}>(
  nodes: readonly TNode[],
  positions: readonly CanvasLayoutPositionV2[],
): TNode[];

export function useAgentCanvasLayoutPreview<TNode extends {
  id: string;
  position: CanvasPositionV2;
}>({
  workflowId,
  persistPositions,
  restoreViewport,
}: {
  workflowId: string;
  persistPositions: (positions: CanvasLayoutPositionV2[]) => Promise<void>;
  restoreViewport: (viewport: Viewport) => Promise<unknown> | unknown;
}): {
  status: AgentCanvasLayoutPreviewStatus;
  error: string | null;
  active: boolean;
  positions: CanvasLayoutPositionV2[];
  begin: (preview: AgentCanvasLayoutPreviewStart<TNode>) => void;
  cancel: () => void;
  keep: () => Promise<void>;
  overlay: (nodes: readonly TNode[]) => TNode[];
};
```

- [ ] **Step 1: Write failing pure overlay tests**

```ts
it("overlays preview coordinates without changing node content or selection", () => {
  const current = [{ id: "a", position: { x: 1, y: 2 }, selected: true, data: { value: 1 } }];
  const next = overlayAgentCanvasLayoutPreview(current, [{ node_id: "a", x: 50, y: 60 }]);

  expect(next[0]).toMatchObject({
    id: "a",
    position: { x: 50, y: 60 },
    selected: true,
    data: { value: 1 },
  });
  expect(current[0].position).toEqual({ x: 1, y: 2 });
});
```

- [ ] **Step 2: Write failing hook lifecycle tests**

Use `renderHook()` to prove:

```ts
it("previews without persisting and keeps only after confirmation", async () => {
  const persistPositions = vi.fn().mockResolvedValue(undefined);
  const { result } = renderHook(() => useAgentCanvasLayoutPreview({
    workflowId: "wf-1",
    persistPositions,
    restoreViewport: vi.fn(),
  }));

  act(() => result.current.begin(preview));
  expect(result.current.status).toBe("previewing");
  expect(persistPositions).not.toHaveBeenCalled();

  await act(() => result.current.keep());
  expect(persistPositions).toHaveBeenCalledOnce();
  expect(persistPositions).toHaveBeenCalledWith(preview.targetPositions);
  expect(result.current.status).toBe("idle");
});
```

Add separate tests for cancel restoring the saved viewport without persisting, save failure retaining positions and exposing retry, retry success, and workflow ID change clearing the preview without saving.

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
npm test -- --run src/features/agent-canvas/canvas/useAgentCanvasLayoutPreview.test.tsx
```

Expected: FAIL because the hook module does not exist.

- [ ] **Step 4: Implement the preview transaction**

Keep the complete snapshot in one state value:

```ts
type PreviewSnapshot = {
  workflowId: string;
  originalPositions: CanvasLayoutPositionV2[];
  targetPositions: CanvasLayoutPositionV2[];
  originalViewport: Viewport;
};
```

`begin()` records original positions from the passed nodes and target positions but performs no network request. `overlay()` applies target positions whenever a snapshot for the active workflow exists. `cancel()` clears the snapshot and calls `restoreViewport(originalViewport)`. `keep()` changes status to `saving`, awaits `persistPositions(targetPositions)`, clears on success, and changes to `save_error` while retaining the snapshot on failure.

On `workflowId` change, clear any snapshot belonging to another workflow without calling persistence. The unmount cleanup also performs no persistence.

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```bash
npm test -- --run src/features/agent-canvas/canvas/useAgentCanvasLayoutPreview.test.tsx
```

Expected: all preview transaction tests pass.

- [ ] **Step 6: Commit the preview transaction**

```bash
git add \
  apps/web/src/features/agent-canvas/canvas/useAgentCanvasLayoutPreview.ts \
  apps/web/src/features/agent-canvas/canvas/useAgentCanvasLayoutPreview.test.tsx
git commit -m "feat(canvas): add reversible layout preview"
```

---

### Task 3: Accessible Keep-or-Undo Confirmation

**Files:**
- Create: `apps/web/src/features/agent-canvas/canvas/AgentCanvasLayoutConfirmation.tsx`
- Create: `apps/web/src/features/agent-canvas/canvas/AgentCanvasLayoutConfirmation.test.tsx`
- Modify: `apps/web/src/features/agent-canvas/agent-canvas-page.css`

**Interfaces:**
- Consumes:

```ts
export interface AgentCanvasLayoutConfirmationProps {
  status: "previewing" | "saving" | "save_error";
  error: string | null;
  onUndo: () => void;
  onKeep: () => void;
}
```

- Produces a keyboard-accessible confirmation surface. Outside pointer events and Escape call `onUndo`; the component never persists positions itself.

- [ ] **Step 1: Write failing component interaction tests**

```tsx
it("renders approved copy and dispatches explicit actions", async () => {
  const user = userEvent.setup();
  const onUndo = vi.fn();
  const onKeep = vi.fn();
  render(<AgentCanvasLayoutConfirmation
    status="previewing"
    error={null}
    onUndo={onUndo}
    onKeep={onKeep}
  />);

  expect(screen.getByRole("dialog", { name: "是否保留此次排布" })).toBeVisible();
  await user.click(screen.getByRole("button", { name: "保留" }));
  expect(onKeep).toHaveBeenCalledOnce();
  expect(onUndo).not.toHaveBeenCalled();
});
```

Add tests that Escape and an outside `pointerdown` call `onUndo`, clicks inside do not dismiss, initial focus lands on the heading, saving disables both actions, and `save_error` remains visible with actions enabled.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
npm test -- --run src/features/agent-canvas/canvas/AgentCanvasLayoutConfirmation.test.tsx
```

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement the confirmation component**

Render one compact surface:

```tsx
<div
  ref={dialogRef}
  className="agent-canvas-layout-confirmation"
  role="dialog"
  aria-labelledby={headingId}
>
  <p id={headingId} ref={headingRef} tabIndex={-1}>是否保留此次排布</p>
  {error ? <span role="alert">{error}</span> : null}
  <div className="agent-canvas-layout-confirmation__actions">
    <button type="button" disabled={saving} onClick={onUndo}>撤销</button>
    <button type="button" disabled={saving} onClick={onKeep}>保留</button>
  </div>
</div>
```

Focus the heading on mount. Install document `pointerdown` and `keydown` listeners and remove them on cleanup. Treat only events whose target is outside `dialogRef` as outside dismissal. While `status === "saving"`, ignore outside pointer events and Escape because the in-flight layout request cannot be cancelled safely.

- [ ] **Step 4: Add restrained toolbar-popover styling**

Position the surface beneath the layout control, use the existing toolbar glass language, keep corners at 8 px or less, and use the project semantic colors:

```css
.agent-canvas-layout-confirmation {
  position: absolute;
  top: 44px;
  left: 50%;
  width: 220px;
  padding: 12px;
  color: #f3f4f8;
  background: rgb(24 26 34 / 96%);
  border: 1px solid rgb(255 255 255 / 10%);
  border-radius: 8px;
  box-shadow: 0 18px 42px rgb(0 0 0 / 32%);
  transform: translateX(-50%);
}
```

Use `#CA6F6F` for Undo emphasis and `#9CD38E` for Keep emphasis without adding gradients.

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```bash
npm test -- --run src/features/agent-canvas/canvas/AgentCanvasLayoutConfirmation.test.tsx
```

Expected: all confirmation tests pass.

- [ ] **Step 6: Commit the confirmation surface**

```bash
git add \
  apps/web/src/features/agent-canvas/canvas/AgentCanvasLayoutConfirmation.tsx \
  apps/web/src/features/agent-canvas/canvas/AgentCanvasLayoutConfirmation.test.tsx \
  apps/web/src/features/agent-canvas/agent-canvas-page.css
git commit -m "feat(canvas): add layout confirmation popover"
```

---

### Task 4: Agent Canvas Integration and Viewport Motion

**Files:**
- Modify: `apps/web/src/features/agent-canvas/AgentCanvasPage.tsx`
- Modify: `apps/web/src/features/agent-canvas/AgentCanvasPage.chrome.test.ts`
- Modify: `apps/web/src/features/agent-canvas/agent-canvas-page.css`
- Modify: `apps/web/src/features/agent-canvas/canvas/canvasAutoLayout.ts`
- Modify: `apps/web/src/features/agent-canvas/canvas/canvasAutoLayout.test.ts`

**Interfaces:**
- Consumes Task 1 `computeAgentCanvasAutoLayout()` and `enabledNodeLayoutEdges()`.
- Consumes Task 2 `useAgentCanvasLayoutPreview()` and `overlayAgentCanvasLayoutPreview()`.
- Consumes Task 3 `AgentCanvasLayoutConfirmation`.
- Reuses `LayoutIcon`, React Flow `fitView()`, `getViewport()`, existing node measurements, and `session.actions.updateNodePositions()`.

- [ ] **Step 1: Add a failing measured-size adapter test**

Add and test:

```ts
export function agentCanvasLayoutNodeFromFlowNode(
  node: AgentCanvasFlowNode,
): AgentCanvasLayoutNode;
```

The test must prove measured width/height win over fallback dimensions and an unmeasured Script uses `agentCanvasNodePlacementSize("script")`.

- [ ] **Step 2: Add failing page-structure assertions**

Extend `AgentCanvasPage.chrome.test.ts` to assert the page:

```ts
expect(source).toContain("computeAgentCanvasAutoLayout(");
expect(source).toContain("useAgentCanvasLayoutPreview(");
expect(source).toContain("<AgentCanvasLayoutConfirmation");
expect(source).toContain("nodesDraggable={!layoutPreview.active}");
expect(source).toContain("<LayoutIcon />");
expect(source).toContain('aria-label="Organize canvas"');
expect(source).toContain("updateNodePositions");
```

Also assert the CSS contains a preview-only node transform transition and disables it under `prefers-reduced-motion`.

- [ ] **Step 3: Run integration-focused tests and verify RED**

Run:

```bash
npm test -- --run \
  src/features/agent-canvas/canvas/canvasAutoLayout.test.ts \
  src/features/agent-canvas/AgentCanvasPage.chrome.test.ts
```

Expected: FAIL because the measured-size adapter and page integration do not exist.

- [ ] **Step 4: Implement the measured-size adapter**

Choose dimensions in this order:

```ts
const measuredWidth = node.measured?.width;
const measuredHeight = node.measured?.height;
const fallback = agentCanvasNodePlacementSize(
  node.data.node.node_type,
  node.data.asset ? {
    width: node.data.asset.width,
    height: node.data.asset.height,
  } : null,
);
return {
  id: node.id,
  position: node.position,
  size: {
    width: measuredWidth && measuredWidth > 0 ? measuredWidth : fallback.width,
    height: measuredHeight && measuredHeight > 0 ? measuredHeight : fallback.height,
  },
};
```

- [ ] **Step 5: Integrate the preview-aware node projection**

Instantiate the preview hook with the active workflow ID, `updateNodePositions`, and `flowRef.current?.setViewport`. Derive canonical nodes as today, then overlay preview positions before `reconcileDragAwareNodes()`:

```ts
const presentedNodes = useMemo(
  () => layoutPreview.overlay(canonicalNodes),
  [canonicalNodes, layoutPreview.overlay],
);
```

Runtime/SSE refreshes continue rebuilding canonical node data, while `overlay()` reapplies preview coordinates.

- [ ] **Step 6: Implement the Organize action**

On toolbar activation:

1. Convert current Flow nodes with `agentCanvasLayoutNodeFromFlowNode()`.
2. Convert workflow Bindings with `enabledNodeLayoutEdges()`.
3. Calculate isolated row width from the board width in flow coordinates:

```ts
const viewport = instance.getViewport();
const isolatedRowWidth = Math.max(
  960,
  (pointerSpotlight.hostRef.current?.clientWidth ?? 960) / viewport.zoom,
);
```

4. Call `computeAgentCanvasAutoLayout()`.
5. Call `layoutPreview.begin()` with current nodes, target positions, and viewport.
6. On the next animation frame, call:

```ts
void instance.fitView({
  nodes: result.positions.map(({ node_id }) => ({ id: node_id })),
  padding: 0.2,
  maxZoom: 1,
  duration: reducedMotion ? 0 : 420,
});
```

Catch calculation failures before starting preview and report them through `surfaceError` without moving nodes.

- [ ] **Step 7: Render the toolbar control and confirmation**

Wrap the layout button and confirmation in a positioned toolbar item:

```tsx
<div className="agent-canvas-toolbar__layout">
  <button
    type="button"
    aria-label="Organize canvas"
    title="Organize canvas"
    disabled={!nodes.length || layoutPreview.active}
    onClick={organizeCanvas}
  >
    <LayoutIcon />
  </button>
  {layoutPreview.active ? (
    <AgentCanvasLayoutConfirmation
      status={layoutPreview.status === "idle" ? "previewing" : layoutPreview.status}
      error={layoutPreview.error}
      onUndo={layoutPreview.cancel}
      onKeep={() => void layoutPreview.keep()}
    />
  ) : null}
</div>
```

Keep the button enabled only when visible nodes exist and no unresolved preview is active. Wrap `layoutPreview.cancel()` and `layoutPreview.keep()` with page callbacks. After successful Keep or any Undo path, schedule `layoutButtonRef.current?.focus()` on the next animation frame. Do not return focus after a failed Keep because the error and actions remain active in the confirmation surface.

- [ ] **Step 8: Disable only node dragging during preview**

Set:

```tsx
nodesDraggable={!layoutPreview.active}
```

Do not disable pane drag, wheel zoom, node selection, edge selection, workbench controls, chat, Run, or Export. Add `is-layout-previewing` to the board only while preview positions are active so the 360 ms transform transition cannot affect ordinary dragging.

- [ ] **Step 9: Add transition and reduced-motion CSS**

```css
.agent-canvas-board.is-layout-previewing .react-flow__node {
  transition: transform 360ms cubic-bezier(.22, .72, .24, 1);
}

@media (prefers-reduced-motion: reduce) {
  .agent-canvas-board.is-layout-previewing .react-flow__node {
    transition: none;
  }
}
```

Match toolbar wrapper/button selectors so the new control retains the existing 34 px button geometry.

- [ ] **Step 10: Run all feature-focused tests**

Run:

```bash
npm test -- --run \
  src/features/agent-canvas/canvas/canvasAutoLayout.test.ts \
  src/features/agent-canvas/canvas/useAgentCanvasLayoutPreview.test.tsx \
  src/features/agent-canvas/canvas/AgentCanvasLayoutConfirmation.test.tsx \
  src/features/agent-canvas/canvas/canvasGraphModel.test.ts \
  src/features/agent-canvas/canvas/deleteCanvasEntities.test.ts \
  src/features/agent-canvas/AgentCanvasPage.chrome.test.ts \
  src/features/agent-canvas/session/layoutQueue.test.ts \
  src/features/agent-canvas/session/layoutPersistence.test.ts \
  src/features/agent-canvas/session/workflowMerge.test.ts
```

Expected: all selected tests pass.

- [ ] **Step 11: Commit the page integration**

```bash
git add \
  apps/web/src/features/agent-canvas/AgentCanvasPage.tsx \
  apps/web/src/features/agent-canvas/AgentCanvasPage.chrome.test.ts \
  apps/web/src/features/agent-canvas/agent-canvas-page.css \
  apps/web/src/features/agent-canvas/canvas/canvasAutoLayout.ts \
  apps/web/src/features/agent-canvas/canvas/canvasAutoLayout.test.ts
git commit -m "feat(canvas): add one-click layout workflow"
```

---

### Task 5: Verification, Review, and Local Main Integration

**Files:**
- Modify only files required by concrete verification findings.

**Interfaces:**
- Verifies the complete feature against the approved design; produces no new product behavior.

- [ ] **Step 1: Run static checks**

```bash
cd apps/web
npm run typecheck
npm run lint
npm run build
git diff --check
```

Expected: every command exits `0`; Vite produces the production bundle.

- [ ] **Step 2: Start the worktree frontend for Chromium verification**

```bash
npm run dev -- --host 0.0.0.0 --port 5191
```

Use the backend on port 8000 and an existing project with connected and isolated nodes.

- [ ] **Step 3: Verify preview behavior in Chromium**

Confirm all of the following in one real browser session:

- The layout button is visible and uses the existing toolbar dimensions.
- One click moves nodes once and fits every node into the usable viewport.
- Connected dependencies read left to right and edges cross less than the starting layout.
- Connected components do not overlap.
- Isolated nodes appear below the connected graph.
- The confirmation displays `是否保留此次排布`, `撤销`, and `保留`.
- No layout network request occurs before Keep.
- Runtime refresh does not reset preview coordinates.
- Nodes cannot be dragged during preview, but pan, zoom, selection, chat, and node inspection remain usable.
- Undo, Escape, and outside click restore original coordinates without a layout request.
- Keep sends the existing workflow layout request and the arrangement survives refresh.
- Node and edge selection remain unchanged.
- With reduced motion emulated, nodes and viewport move without animation.
- The page reports no uncaught browser errors.

- [ ] **Step 4: Request a code review**

Review the feature branch against the design commit `f659967`, focusing on graph correctness, deletion/selection regressions, preview persistence boundaries, event cleanup, and save conflict behavior. Resolve every Critical or Important finding and rerun affected tests.

- [ ] **Step 5: Run fresh final verification**

```bash
npm test -- --run \
  src/features/agent-canvas/canvas/canvasAutoLayout.test.ts \
  src/features/agent-canvas/canvas/useAgentCanvasLayoutPreview.test.tsx \
  src/features/agent-canvas/canvas/AgentCanvasLayoutConfirmation.test.tsx \
  src/features/agent-canvas/canvas/canvasGraphModel.test.ts \
  src/features/agent-canvas/canvas/deleteCanvasEntities.test.ts \
  src/features/agent-canvas/AgentCanvasPage.chrome.test.ts \
  src/features/agent-canvas/session/layoutQueue.test.ts \
  src/features/agent-canvas/session/layoutPersistence.test.ts \
  src/features/agent-canvas/session/workflowMerge.test.ts
npm run typecheck
npm run lint
npm run build
```

Expected: zero failing tests and every command exits `0`.

- [ ] **Step 6: Merge locally using the required non-fast-forward history**

From `/data/longwei.wu/AdCraft`:

```bash
git merge --no-ff feat/agent-canvas-auto-layout -m "merge: add Agent Canvas one-click layout"
```

Run the focused test command and `npm run typecheck` again from local `main`. Do not push to a remote or create a PR.
