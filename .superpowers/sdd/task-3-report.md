# Task 3 Report: Workflow-Scoped Chat Pointer Cache

## Scope

- Added workflow-scoped promise caches for proposal and decision-bundle pointer hydration.
- Added in-flight capability-turn hydration tracking and completed-turn tracking.
- Cache failures are evicted so the next timeline refresh retries hydration.
- All hydration tracking is cleared when the active workflow changes.
- Runtime terminal turn refresh behavior and existing session/chat state remain unchanged.

## RED

Command:

```bash
cd apps/web && npm test -- src/features/agent-canvas/chat/useAgentCanvasChat.test.tsx
```

Observed output:

```text
FAIL  src/features/agent-canvas/chat/useAgentCanvasChat.test.tsx > useAgentCanvasChat > reuses pointer hydration while refreshing the same timeline twice
AssertionError: expected "vi.fn()" to be called once, but got 2 times
 ❯ src/features/agent-canvas/chat/useAgentCanvasChat.test.tsx:1410:37
```

Result summary:

```text
Test Files  1 failed (1)
Tests  1 failed | 40 passed (41)
```

## GREEN

Command:

```bash
cd apps/web && npm test -- src/features/agent-canvas/chat/useAgentCanvasChat.test.tsx
```

Observed output:

```text
Test Files  1 passed (1)
Tests  41 passed (41)
```

Additional verification:

```bash
cd apps/web && npm run typecheck && git diff --check
```

Observed output:

```text
> ad-workflow-frontend@1.0.0 typecheck
> tsc -p tsconfig.json
```

Both commands exited successfully.
