# Task 3 Report: Bounded Real Video Frame Sampling

## Delivered

Created a reusable `useVideoFrameStrip` hook and focused test suite.

- `apps/web/src/features/agent-canvas/editing/useVideoFrameStrip.ts`
- `apps/web/src/features/agent-canvas/editing/useVideoFrameStrip.test.tsx`

The module exposes the requested `VideoFrameSample` and `VideoFrameRequest` interfaces, `frameSampleTimes`, `frameCacheKey`, and `useVideoFrameStrip`.

## Behavior

- Requests are evenly spaced at visual cell midpoints and capped at 12 samples per strip.
- Sample cache keys use `assetId`, centisecond source time, and `80x45` dimensions.
- A module-level 120-entry LRU cache retains sampled blob URLs, promotes effect-time cache hits, and revokes evicted URLs after their final mounted lease is released.
- The production sampler creates one hidden video element and one reusable canvas for an active request, waits for metadata without blocking the initial render, and seeks samples serially.
- Initial and failed frames use `previewUrl`, including `null`; sampling errors are contained and never reject rendering.
- The sampling API accepts `AbortSignal`. Unmount, request changes, and hidden-document transitions abort the active run, remove media listeners, and dispose the video source when no shared consumer remains. Visibility resume starts a fresh run.
- Concurrent requests for the same cache key share one in-flight sampling task. Duplicate URLs retain the canonical cache entry and only an unused duplicate is revoked.
- Seek listeners attach before assigning `currentTime`; an already-current frame extracts immediately, and synchronous seek assignment failures settle without leaving listeners behind.
- Render-time output is fallback/state-only and does not mutate LRU recency.
- Request epochs and effect cleanup prevent stale request completions and unmounted hooks from writing React state.
- No API clients, backend routes, or backend writes were changed.

## TDD Evidence

1. Added the focused test before creating the hook.
2. Ran the required command and observed the expected RED failure: Vite could not resolve `./useVideoFrameStrip.ts` because the module did not exist.
3. Implemented the sampler/cache.
4. Added remediation regression tests and observed RED failures for null fallback, unmount cancellation, same-key deduplication, and seek API behavior.
5. Ran the focused test after the remediation: 13 tests passed.

The tests cover midpoint times and cache keys, cache reuse, preview fallback, null fallback, cache-bound eviction/revocation, unmount cancellation, request-change cancellation and stale-result protection, hidden pause/visible resume, same-key deduplication, seek listener ordering, already-current extraction, and synchronous seek failure settlement.

## Verification

From `apps/web`:

```text
npm test -- --run --reporter=verbose src/features/agent-canvas/editing/useVideoFrameStrip.test.tsx
13 passed

npm run typecheck
passed

npx eslint src/features/agent-canvas/editing/useVideoFrameStrip.ts src/features/agent-canvas/editing/useVideoFrameStrip.test.tsx
passed
```

`git diff --check` also passed.

## Self-Review

- Confirmed all requested requirements are implemented in the reusable module only; Task 5 remains responsible for timeline UI integration.
- Confirmed cached frames are available to later matching requests, while render paths never read or promote LRU entries.
- Confirmed the effect depends on a memoized scalar request value, preventing repeated work from callers that construct a new request object each render.
- Confirmed serial `await` execution prevents concurrent seeks on the request-local video element.
- Confirmed cache eviction cannot revoke a URL held by an active hook result, and shared work cannot create a second sampler for the same cache key.
