# 002 — Desynchronize concurrent generation loaders

- **Status**: DONE
- **Commit**: f5aa1e4f
- **Severity**: LOW
- **Category**: Cohesion & tokens
- **Estimated scope**: 4 files, approximately 90 lines

## Problem

Every media Loader currently starts its CSS animations at phase zero:

```tsx
/* apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.tsx:267 — current */
{generatingMediaType ? (
  <AgentCanvasMediaGenerationLoader mediaType={generatingMediaType} />
) : null}
```

```css
/* apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.css:705 — current */
animation:
  agent-canvas-node-dots-morph 4.2s cubic-bezier(0.35, 1.55, 0.65, 1) infinite,
  agent-canvas-node-dots-breathe 1.9s cubic-bezier(0.66, 0, 0.34, 1) infinite;
```

Nodes often enter `working` within the same runtime refresh. Their bright regions then move and breathe together, making the canvas look like a synchronized dashboard animation rather than independent production tasks.

## Target

Derive stable negative animation delays from `node.node_id`. The same node must receive the same phase after rerender; different node IDs should normally receive different phases. Do not use `Math.random()`, timestamps, array indices, or persisted state.

Add this exact helper and prop shape to `AgentCanvasMediaGenerationLoader.tsx`:

```tsx
import type { CSSProperties } from "react";

const ORBIT_DURATION_SECONDS = 6.4;
const BREATHE_DURATION_SECONDS = 2.4;

type LoaderStyle = CSSProperties & {
  "--agent-canvas-loader-orbit-delay": string;
  "--agent-canvas-loader-breathe-delay": string;
};

export function mediaGenerationLoaderDelays(nodeId: string): LoaderStyle {
  let hash = 2166136261;
  for (let index = 0; index < nodeId.length; index += 1) {
    hash ^= nodeId.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  const phase = (hash >>> 0) / 0x1_0000_0000;
  return {
    "--agent-canvas-loader-orbit-delay": `-${(phase * ORBIT_DURATION_SECONDS).toFixed(3)}s`,
    "--agent-canvas-loader-breathe-delay": `-${(phase * BREATHE_DURATION_SECONDS).toFixed(3)}s`,
  };
}
```

`AgentCanvasMediaGenerationLoader` must require both `mediaType` and `nodeId`, apply the returned style to the root Loader, and `AgentCanvasNodeCard` must pass `node.node_id`.

After Plan 001, update the CSS declaration to:

```css
animation:
  agent-canvas-node-dots-morph 6.4s linear var(--agent-canvas-loader-orbit-delay, 0s) infinite,
  agent-canvas-node-dots-breathe 2.4s cubic-bezier(0.66, 0, 0.34, 1) var(--agent-canvas-loader-breathe-delay, 0s) infinite;
```

## Repo conventions to follow

- The Node already owns the authoritative stable identity at `node.node_id`; use it directly.
- The animation stays CSS-driven. JavaScript computes only two immutable CSS values during render.
- Existing `memo` behavior and node render identity must remain intact.
- Existing interaction pause and reduced-motion selectors act on the dynamic layer and require no new event handling.

## Steps

1. Add unit tests in a new `AgentCanvasMediaGenerationLoader.test.tsx` for deterministic output, different IDs, negative bounded delays, and rendered CSS custom properties.
2. Update `AgentCanvasNode.test.tsx` to require the Loader call to receive the node ID.
3. Run both tests and confirm they fail because the helper and `nodeId` prop do not exist.
4. Add `mediaGenerationLoaderDelays`, the `nodeId` prop, and the root `style` in `AgentCanvasMediaGenerationLoader.tsx` exactly as specified.
5. Pass `node.node_id` from `AgentCanvasNode.tsx`.
6. Add the two delay variables to the animation shorthand in `AgentCanvasNode.css` without changing Plan 001's durations or keyframes.
7. Re-run tests, typecheck, focused ESLint, and build.

## Boundaries

- Do NOT use random values or component mount order.
- Do NOT persist visual phase, add React state/effects, or change node/runtime identity.
- Do NOT change animation trajectories, opacity ranges, status logic, media loading, or backend contracts.
- Plan 001 must be complete first; if its `6.4s/2.4s` durations are absent, stop and execute Plan 001.

## Verification

- **Mechanical**: `npm run test -- AgentCanvasMediaGenerationLoader.test.tsx AgentCanvasNode.test.tsx`; `npm run typecheck`; focused ESLint; `npm run build`.
- **Feel check**: display at least four simultaneously working nodes. Confirm they begin at visibly different orbit and breathe phases, while a rerender that does not change `node_id` does not jump to a new phase.
- **Reduced motion**: emulate `prefers-reduced-motion: reduce`; all nodes must remain stationary at the existing `opacity: 0.7` regardless of delay variables.
- **Done when**: same-ID delays are byte-for-byte stable, different fixture IDs produce distinct delays, and concurrent nodes no longer move in lockstep.
