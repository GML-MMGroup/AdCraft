# Agent Canvas Runtime And Drag Performance Design

## Goal

Keep Agent Canvas responsive while runtime and chat events are arriving, and make every drag session terminate safely even when the browser cancels the pointer sequence.

## Scope

This is a frontend-only change. Backend contracts, event names, and persistence endpoints remain unchanged.

## Runtime Refresh Policy

Runtime events that repeatedly describe the same non-terminal state must not trigger another canonical runtime request. The frontend will derive a stable refresh identity from the workflow, execution, node, event type, and meaningful progress payload. Repeated identities are ignored while terminal and materially changed events still refresh immediately.

Canonical runtime responses will be compared by their presentation-relevant fields. Changes limited to `events_cursor` or `updated_at` will retain the existing React state object so React Flow is not rebuilt for a timestamp-only response.

## Canvas Coordination

React Flow remains the owner of transient drag coordinates. Canonical workflow snapshots continue to be deferred during an active drag, but a drag session will now replace any stale active identifiers when it starts and will be cancelled on `pointercancel`, window blur, document hiding, or unmount.

Cancellation clears drag state and reconciles the latest canonical snapshot without persisting an incomplete position. A normal stop persists only finite coordinates. Layout persistence failures trigger a canonical workflow refresh instead of being silently ignored.

Node reconciliation will retain existing node object references when the canonical node, selection, position, and drag state are unchanged. This prevents unchanged cards from rerendering after an idempotent snapshot.

## Chat Hydration

Proposal and decision-bundle entity reads are reused by identifier while the chat revision is unchanged. The current pointer's sequence and timestamp are always retained, and mutable entity caches are invalidated after local actions or a new chat revision. Terminal capability turns that have already been hydrated will not be fetched again by every full timeline refresh; live turn events remain authoritative for later status changes. All caches are cleared when the workflow changes.

## Failure Handling

- Runtime request failures continue to use the existing runtime error surface.
- A cancelled drag never writes layout data.
- A failed layout write requests the canonical workflow and leaves the existing authoring error visible.
- Failed pointer hydration is not cached, allowing a later refresh to retry.

## Verification

- Unit tests cover repeated runtime events, timestamp-only runtime responses, pointer hydration reuse, drag cancellation, stale drag identifiers, structural sharing, and layout-save recovery wiring.
- Existing Agent Canvas runtime, chat, layout, and canvas tests remain green.
- Type checking, linting, and production build must pass.
- A browser stress test uses `adwf_v2_e90fd91e37c280af` and verifies that repeated dragging leaves nine visible nodes with no console exception.
