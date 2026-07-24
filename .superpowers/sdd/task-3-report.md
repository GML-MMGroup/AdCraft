# Task 3 Report

Status: complete with a documented pre-existing bundle-budget failure.
SHA: `HEAD` after commit `perf(web): bound collection and media loading`.
Base: `3e808c7`.

## RED

- Added failing coverage for deterministic collection-query keys, in-flight dedupe, recovery after failure, invalidation, and stale completion guards.
- Added failing hook coverage for the 250 ms search debounce, request abort propagation, stale asset result rejection, and scope/category/cursor isolation.
- Added failing project-list coverage for observer-gated cover loading and a shared four-request concurrency limit.
- Added a configuration test for immutable hashed assets, revalidated `index.html`, and preserved `/media/` proxy handling.

## GREEN

- `createSettledQueryResource` caches settled requests by canonical structured key, deduplicates concurrent readers, aborts invalidated work, and removes failed entries for recovery.
- Project covers are observer-gated, share a stable request cache, retain the existing resolver/fallback behavior, and use a global four-slot queue.
- Asset-library searches debounce only text changes for 250 ms; every list request carries an `AbortSignal`, stale completions are ignored, and pagination remains scoped to the active query.
- Asset cards use `DeferredVideo` with a poster instead of eagerly loading video metadata.
- Nginx caches hashed `/assets/` for one year with `immutable`, revalidates `index.html`, and leaves `/media/` proxy semantics unchanged.

## Files

- `apps/web/src/collections/settledQueryResource.ts`
- `apps/web/src/collections/requestQueue.ts`
- `apps/web/src/features/assets/useV2AssetLibrary.ts`
- `apps/web/src/api/v2Client.ts`
- `apps/web/src/pages/projects/ProjectList.tsx`
- `apps/web/src/components/Cards.tsx`
- `apps/web/src/pages/AssetsPage.tsx`
- Task 3 tests under `apps/web/src/collections`, `features/assets`, `pages/projects`, and `quality`
- `deploy/nginx.conf`

## Verification

- Focused tests: 29 passing tests across 5 files.
- Full frontend suite: 143 passing tests across 27 files.
- `npm run typecheck`: pass.
- `npm run lint`: pass.
- `npm run build`: pass.
- `git diff --check`: pass.

## Review

- Scope is limited to Task 3 frontend collection/media modules and nginx static-cache configuration.
- Existing asset viewer, upload, recommended catalog, pagination, project-cover resolver, and fallback behavior remain intact.
- No bundle budget threshold or unrelated CSS was changed.

## Concerns

- `npm run perf:bundle` still fails without any budget change: core JS is 1312 KiB versus 1281 KiB, final-composition JS is 97 KiB versus 96 KiB, and core CSS is 197 KiB versus 180 KiB. `src/styles.css` and `scripts/perf/check-build-budget.mjs` are byte-for-byte identical to base `3e808c7`; the final-composition editor is outside Task 3. This is recorded rather than waived or hidden.
