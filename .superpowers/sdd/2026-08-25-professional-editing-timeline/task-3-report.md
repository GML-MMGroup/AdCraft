# Task 3 Report: Bounded Real Video Frame Sampling

## Delivered

Created a reusable `useVideoFrameStrip` hook and focused test suite.

- `apps/web/src/features/agent-canvas/editing/useVideoFrameStrip.ts`
- `apps/web/src/features/agent-canvas/editing/useVideoFrameStrip.test.tsx`

The module exposes the requested `VideoFrameSample` and `VideoFrameRequest` interfaces, `frameSampleTimes`, `frameCacheKey`, and `useVideoFrameStrip`.

## Behavior

- Requests are evenly spaced at visual cell midpoints and capped at 12 samples per strip.
- Sample cache keys use `assetId`, centisecond source time, and `80x45` dimensions.
- A module-level 120-entry LRU cache retains sampled blob URLs, promotes hits, and revokes evicted blob URLs.
- The production sampler creates one hidden video element and one reusable canvas for an active request, waits for metadata without blocking the initial render, and seeks samples serially.
- Initial and failed frames use `previewUrl`; sampling errors are contained and never reject rendering.
- Sampling does not begin or continue scheduling while `document.hidden` is true; it resumes on `visibilitychange`.
- Request epochs and effect cleanup prevent stale request completions and unmounted hooks from writing React state. A stale blob result is revoked before it can leak.
- No API clients, backend routes, or backend writes were changed.

## TDD Evidence

1. Added the focused test before creating the hook.
2. Ran the required command and observed the expected RED failure: Vite could not resolve `./useVideoFrameStrip.ts` because the module did not exist.
3. Implemented the sampler/cache.
4. Ran the focused test after implementation: 4 tests passed.

The tests cover the brief's requested midpoint times and cache key, cache reuse across matching hook instances, and preview fallback for every requested frame after sampler rejection.

## Verification

From `apps/web`:

```text
npm test -- --run --reporter=verbose src/features/agent-canvas/editing/useVideoFrameStrip.test.tsx
4 passed

npm run typecheck
passed

npx eslint src/features/agent-canvas/editing/useVideoFrameStrip.ts src/features/agent-canvas/editing/useVideoFrameStrip.test.tsx
passed
```

`git diff --check` also passed.

## Self-Review

- Confirmed all requested requirements are implemented in the reusable module only; Task 5 remains responsible for timeline UI integration.
- Confirmed cached frames are immediately available on later matching requests and cache access updates LRU recency.
- Confirmed the effect depends on a memoized scalar request value, preventing repeated work from callers that construct a new request object each render.
- Confirmed serial `await` execution prevents concurrent seeks on the request-local video element.
