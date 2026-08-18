# Agent Canvas One-Click Layout Design

## Summary

Add a one-click canvas organization control to Agent Canvas. The feature arranges the complete workflow from left to right using persisted node-to-node Bindings, previews the result without saving it, and asks the user whether to keep or undo the arrangement.

The layout must improve readability without changing workflow semantics. It must not create, delete, reorder, enable, or infer Bindings. It must not modify prompts, media, runtime state, node selection, semantic revision, or execution behavior.

## Goals

- Arrange connected workflow nodes into a readable left-to-right dependency graph.
- Reduce edge crossings and keep branches and merge points visually understandable.
- Respect the rendered dimensions of different node cards.
- Place disconnected workflows and fully isolated nodes without overlap.
- Show the complete arranged canvas after one smooth transition.
- Keep the arrangement local until the user explicitly chooses to retain it.
- Preserve canvas interactivity while layout persistence is in progress.
- Produce deterministic positions for the same nodes and Bindings.

## Non-Goals

- Inferring dependencies from node type, title, creative role, location, or prompt text.
- Changing persisted Bindings or their order.
- Creating a semantic production-stage layout.
- Automatically arranging the canvas when a workflow opens or refreshes.
- Replacing manual node positioning.
- Adding a backend endpoint specifically for automatic layout.
- Adding a general-purpose layout history or undo stack.

## User Experience

### Entry Point

Add an icon-only layout control to the existing Agent Canvas toolbar. It uses the existing toolbar dimensions and visual language and exposes the accessible label and tooltip `Organize canvas`.

The control is disabled when there are no visible nodes. While a layout preview or save is active, another layout operation cannot be started.

### Preview Flow

1. The user selects `Organize canvas`.
2. The frontend calculates the final layout entirely in memory.
3. Nodes move once from their current positions to their final positions. Optimization passes are never rendered as intermediate states.
4. React Flow performs a smooth `fitView` that includes every visible node, including the isolated-node area.
5. A confirmation popover anchored to the layout control displays:

   `是否保留此次排布`

   Actions: `撤销` and `保留`.

### Preview Rules

- The preview does not call the backend layout API.
- The user may pan, zoom, inspect nodes, and view node content.
- Node dragging is disabled until the preview is resolved.
- Runtime and SSE updates continue to refresh node content and status.
- Preview positions override refreshed workflow positions so background updates cannot make nodes jump back.
- Node and edge selection remain unchanged.
- Starting another layout preview is disabled.

### Keep, Undo, and Dismissal

- `Keep` persists the complete target position set through the existing batch layout path.
- `Undo` restores every pre-layout node position and the pre-layout viewport without sending a request.
- `Escape`, clicking outside the popover, switching projects, or leaving the Workflow page behaves as `Undo`.
- A successful save closes the popover and removes the preview overlay.
- A failed save keeps the preview visible, reports the exact bounded error, and allows the user to retry `Keep` or choose `Undo`.
- While saving, both confirmation actions and the layout button are disabled. Pan, zoom, and content inspection remain available.

### Motion

- Normal mode uses a 360 ms node transition followed by a 420 ms viewport transition.
- `prefers-reduced-motion: reduce` applies final positions and the final viewport immediately.
- The layout engine's internal ordering passes are never visible.

## Layout Authority

Only enabled, persisted Bindings whose source is another visible node participate in graph topology. Asset bindings and disabled Bindings do not establish a node rank.

Every displayed connection remains backend-authored. Automatic layout changes positions only.

## Layout Algorithm

### Engine

Use a mature layered DAG layout engine rather than maintaining a second ad hoc graph algorithm. Configure it for left-to-right ranking and pass explicit node dimensions. A small adapter owns deterministic ordering, component packing, isolated-node placement, and conversion between center-based engine coordinates and React Flow top-left coordinates.

Use `@dagrejs/dagre`, isolated behind the local layout module so the engine can be replaced without changing the page or preview state machine.

### Input Preparation

1. Select visible Agent Canvas nodes.
2. Select enabled node-output Bindings whose source and target are both visible.
3. Sort nodes by stable node ID and Bindings by stable binding ID before graph insertion.
4. Build undirected connectivity only for finding connected components.
5. Keep the original directed Binding orientation for layout ranks.
6. Separate fully isolated nodes from connected components.

### Node Dimensions

Prefer dimensions measured by React Flow because they represent the actual rendered card:

- Image nodes use their rendered media aspect ratio.
- Script nodes use their current content-driven height.
- Text, Video, Audio, and Editing nodes use their rendered size.

If a node has not been measured, use the existing safe placement dimensions from `nodeGeometry.ts`. Script falls back to its maximum safe height and unknown Image media uses its existing conservative square footprint.

### Connected Components

Run layered layout independently for each connected component:

- Rank direction is left to right.
- Sources occupy the leftmost rank.
- A downstream node is placed to the right of its deepest upstream dependency.
- The engine's ordering stage reduces crossings through forward and backward neighbor sweeps.
- Branches expand around their shared source.
- Merge nodes align near the vertical center of their upstream nodes.
- Horizontal spacing is wider than vertical spacing so Bezier edges have room to turn and remain traceable.

Initial layout constants are:

- Rank separation: 140 px between neighboring node bounds.
- Node separation: 84 px within a rank.
- Connected-component separation: 160 px.
- Connected-to-isolated section separation: 220 px.
- Layout origin: `(120, 120)`.

These values are part of the first implementation and may be tuned only through visual verification without changing the ordering rules.

The largest component is the primary component and appears first. Components are ordered by:

1. Descending visible node count.
2. Descending participating Binding count.
3. Stable minimum node ID.

Connected components are packed vertically with a component gap larger than the normal row gap.

### Isolated Nodes

Fully isolated nodes appear in a separate area below all connected components.

- Preserve their pre-layout reading order using current top-to-bottom, then left-to-right position, with stable node ID as the final tie-breaker.
- Place them in rows and wrap according to the width occupied by the connected layout.
- If no connected component exists, use a bounded default row width derived from the available canvas viewport.
- Keep a section gap larger than the component gap so the isolated area is visually distinct without adding a visible container or label.

### Normalization and Determinism

After component packing, translate all target positions to a common layout origin. Round coordinates to whole pixels. Stable input ordering, fixed engine options, stable component order, and fixed spacing ensure identical graph input produces identical output.

### Cycles and Historical Data

The backend normally prevents invalid cycles. If historical data contains one, the layout engine may reverse edges internally for positioning, but the frontend must preserve the real Binding direction and must not persist any graph mutation. The user still receives a readable best-effort layout.

## Component Design

### `canvasAutoLayout.ts`

A pure layout module with a narrow interface.

Responsibilities:

- Convert visible nodes, enabled node Bindings, and measured dimensions into engine input.
- Find connected components and isolated nodes.
- Run layered layout and pack results.
- Return a complete `CanvasLayoutPositionV2[]` and layout bounds.

It has no React state, network access, browser storage, or React Flow instance dependency.

### `useAgentCanvasLayoutPreview.ts`

A hook that owns the preview transaction.

Responsibilities:

- Capture original node positions and viewport.
- Track `idle`, `previewing`, `saving`, and `save_error` states.
- Overlay preview positions on canonical React Flow nodes.
- Keep preview positions through runtime and SSE refreshes.
- Restore positions and viewport on undo or dismissal.
- Call the existing `updateNodePositions()` action only when the user chooses `Keep`.
- Clear the preview after a successful save.

The hook treats a preview as a local transaction. It does not write preview state to browser storage.

### `AgentCanvasLayoutConfirmation.tsx`

A focused popover component anchored to the toolbar control.

Responsibilities:

- Render the approved question and two actions.
- Expose saving and error states.
- Implement accessible dialog/popover semantics and focus management.
- Return focus to the layout control after resolution.

### `AgentCanvasPage.tsx`

The page remains orchestration-only:

- Supplies canonical nodes, Bindings, measurements, layout persistence, and React Flow instance access.
- Renders the toolbar control and confirmation component.
- Uses preview-aware nodes for presentation.
- Disables node dragging while preview is unresolved.

No layout algorithm is implemented inline in the page.

## Data Flow

```text
Toolbar click
  -> collect canonical nodes, enabled node Bindings, measured sizes
  -> canvasAutoLayout computes final positions and bounds
  -> preview hook captures original positions and viewport
  -> preview positions overlay canonical React Flow nodes
  -> React Flow fitView includes all preview nodes
  -> confirmation popover opens

Undo/dismiss
  -> remove preview overlay
  -> restore original viewport
  -> no backend request

Keep
  -> updateNodePositions(all target positions)
  -> existing layout queue and layout_revision conflict handling
  -> success: remove preview overlay, retain arranged viewport
  -> failure: retain preview and expose retry/undo
```

## Persistence and Concurrency

- Reuse the existing Workflow layout endpoint and `AgentCanvasLayoutQueue`.
- Do not send semantic `If-Match`; layout remains governed by `layout_revision`.
- Preserve the existing conflict behavior that fetches the latest layout revision and reapplies only the intended target positions.
- Runtime and semantic SSE events do not resolve or cancel the preview.
- A project/workflow identity change cancels the preview before rendering the new workflow.
- The final persistence set includes every visible node target position, allowing one user decision to correspond to one logical arrangement even if the queue must split a very large payload into backend-sized chunks.

## Error Handling

- Layout calculation failure leaves the current canvas untouched and shows a bounded message.
- Missing measured dimensions use safe fallbacks and are not an error.
- Save failure does not silently keep or discard the arrangement.
- Layout revision conflicts follow existing rebase behavior.
- A workflow identity change during save surfaces the existing workflow-changed error and does not apply positions to the new workflow.
- The feature does not interpret SSE disconnection as a layout failure.

## Accessibility

- The toolbar button has an accessible name and tooltip.
- The confirmation surface uses dialog or popover semantics with a clear label.
- Initial focus moves to the dialog heading so opening the preview cannot make Enter retain it accidentally. Tab order is `撤销`, then `保留`.
- `Escape` performs Undo.
- Focus returns to the toolbar control after Keep or Undo.
- Actions remain keyboard accessible.
- Reduced-motion preferences remove node and viewport animation.

## Verification

### Pure Layout Tests

- Produces left-to-right ranks from directed Bindings.
- Places branches and merge points coherently.
- Does not use disabled or asset Bindings for topology.
- Does not add or alter Bindings.
- Uses measured dimensions and prevents node overlap.
- Keeps multiple connected components separate.
- Places isolated nodes below connected components without overlap.
- Produces stable positions for stable input.
- Handles an empty graph, one node, all-isolated nodes, and historical cycles.
- Crossing reduction does not produce more crossings than the deterministic initial order for representative graphs.

### Preview State Tests

- Starting preview performs no backend request.
- Runtime refresh keeps preview coordinates while updating node content.
- Keep submits the complete target position set once as a logical action.
- Undo restores positions and viewport without saving.
- Outside click, Escape, workflow switch, and unmount cancel without saving.
- Save failure preserves preview and supports retry or Undo.
- Successful save clears preview.

### Page Interaction Tests

- Toolbar button state follows node and preview state.
- Node dragging is disabled only while preview is unresolved.
- Pan, zoom, selection, and content inspection remain available.
- `fitView` includes connected components and isolated nodes.
- Existing node and edge selection are preserved.
- Reduced-motion mode uses immediate transitions.

### Regression Checks

- Existing manual dragging and batch layout persistence still work.
- Runtime/SSE refresh behavior remains unchanged outside preview positions.
- Node execution, Global Run, Editing Export, asset browsing, and chat are unaffected.
- Typecheck, lint, focused tests, production build, and a Chromium canvas smoke test pass before merge.

## Accepted Decisions

- Layout scope: all visible nodes.
- Main direction: left to right.
- Algorithm: layered DAG layout with crossing reduction.
- Disconnected components: arranged as separate connected sections.
- Fully isolated nodes: placed in a separate area below the connected graph.
- Viewport: automatically fit all visible nodes after arranging.
- Persistence: preview first; save only after explicit Keep.
- Dismissal: Undo on outside click, Escape, project switch, or page exit.
- Internal optimization: invisible; the user sees one final transition only.
