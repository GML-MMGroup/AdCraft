# Agent Canvas Drag Snapshot Coordination Design

## Problem

Agent Canvas currently reconciles every new `presentedNodes` array into React Flow, including while one or more nodes are being dragged. Runtime SSE updates and layout updates can therefore replace React Flow node objects during an active drag. The backend remains authoritative and retains every node, but the controlled React Flow state can remain incomplete or inconsistent until a full page refresh.

## Scope

- Change only the frontend Agent Canvas presentation synchronization.
- Keep backend workflow state, SSE processing, runtime merging, and layout persistence unchanged.
- Preserve the existing controlled React Flow architecture and layout preview behavior.
- Do not start a development server or modify backend files.

## Design

`AgentCanvasPage` will retain the latest complete `presentedNodes` snapshot in a ref. While the active dragged-node set is non-empty, new snapshots will also be recorded as pending but will not call `setNodes`. This prevents runtime publication from replacing React Flow node objects during a drag without blocking the underlying workflow state from advancing.

When dragging stops, the page will:

1. Collect finite final positions from every node in the drag-stop callback.
2. Clear the complete active drag set, including IDs that may be absent from the final callback.
3. Rebuild the entire React Flow node array from the newest pending or presented snapshot.
4. Overlay the finite final positions and preserve current selection state.
5. Remove all transient `dragging` flags.
6. Persist only finite positions through the existing session action.

If no drag is active, incoming snapshots continue to reconcile immediately through the existing selection-preserving behavior.

## Boundaries

`draggingNodeState.ts` owns pure coordination operations: finite-position filtering, complete drag-state cleanup, regular snapshot reconciliation, and final post-drag rebuilding. `AgentCanvasPage.tsx` owns React refs and event sequencing. The session remains responsible for optimistic layout persistence and backend conflict handling.

## Tests

- A runtime snapshot received during a drag does not replace the visible node array and is retained for post-drag rebuilding.
- Post-drag rebuilding restores every node from the newest snapshot while retaining final dragged positions.
- Multi-selection cleanup removes every active dragged-node ID even if the stop callback reports only part of the selection.
- `NaN` and infinite coordinates are neither applied to React Flow nor sent for persistence.
- Existing drag and layout tests remain green.
