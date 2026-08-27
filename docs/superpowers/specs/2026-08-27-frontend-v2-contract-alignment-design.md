# Frontend V2 Contract Alignment Design

## Objective

Align the web client with canonical Agent Canvas V2 contracts without introducing a second client authority, rebuilding Editing, or generating graph data in the browser.

## Design Principles

1. Strict public contracts remain strict. New backend fields are modeled and normalized rather than silently stripped.
2. Read compatibility and write authority are different. Legacy image bindings may omit a version, but every new image binding must carry an exact `asset_id + version_id` pair.
3. Guided Interaction is the only guided UI state machine. Product upload feeds its typed Submit action; the direct Product endpoint is not used as a parallel flow.
4. An HTTP 202 response means accepted, not completed. Pending UI remains until authoritative interaction/event refresh closes or fails it.
5. Stable idempotency keys identify one logical submission. A changed interaction revision or payload creates a new key.
6. ETags are endpoint-specific. Binding, node, and import mutations use Workflow ETags; Guided Interaction Submit uses typed interaction/session/guidance revisions and no invented `If-Match` header.
7. Source-only nodes are visible graph artifacts, not generation candidates. All prompt/model/run/variation controls and runtime execution paths reject them.
8. Character cardinality comes from persisted Journey occurrences and requirements. The UI supports zero, one, or many without special-casing a default Character.
9. Editing remains authoritative and explicit. Export is user-triggered; download and import consume terminal backend responses; imported Nodes and Bindings are never synthesized locally.

## Product Source Interaction

The Product Decision Dock renders one typed `product_source` interaction at a time.

- `input_kind=main`: one image source.
- `input_kind=multiview`: backend-provided minimum/maximum asset count.
- `choice=upload`: upload selected files, retain every upload receipt, then submit exact immutable references and the pending handoff ID when returned.
- `choice=generate`: submit the typed generate action without uploading.
- Upload failure leaves the interaction open and preserves selected files where the browser permits.
- A 202 Submit moves the Dock to pending and keeps it there until canonical refresh reports closed or failed.

The generic upload hook exposes the full upload receipt and accepts a caller-provided stable idempotency key. Existing asset-library behavior continues to consume only the returned asset when that is all it needs.

## Immutable Image References

`CanvasBindingSourceImageAssetV2` accepts `source_asset_version_id: string | null` for legacy reads. A separate new-write type requires a non-empty version ID. Asset browser items expose `asset.version_id` instead of replacing it with null.

The binding mutation boundary validates both identifiers before issuing a request. Missing version identity is a visible capability gap, not permission to bind a mutable asset head.

## Source-Only Nodes

One shared predicate defines source-only behavior. It is used by:

- inline workbench rendering;
- node Run/Generate/Variation controls;
- single-node runtime execution;
- Global Run selection;
- parameter migration selection.

The node card still renders media, metadata, status, and bindings.

## Character Occurrences

A pure projection maps Journey decisions to rows:

- filter `element_kind=character`;
- preserve backend occurrence IDs and occurrence indexes;
- sort by persisted occurrence index;
- display persisted `requirements.role` and `requirements.identity_summary`;
- use `Character {occurrence_index}` only when public persisted labels are absent.

No row is shown for zero occurrences. One occurrence uses the same list component as many occurrences.

## Editing and Browser Acceptance

Existing single-track Editing remains unchanged. The change adds:

- runtime refresh for `editing_export_imported_to_canvas`;
- Mock-media acceptance proving explicit Export, terminal Download, authoritative Add to Canvas, source-only Video preview, downstream Binding display, and absence of Provider Task requests;
- assertions for native audio and free-position timeline restoration.

## Error and Recovery Behavior

Typed backend error codes are retained. A stale Product interaction refreshes the interaction/session/workflow and keeps local choices so the user can resubmit against the new authority. A Workflow 412 refreshes canonical Workflow state and asks for retry; it never silently overwrites.

SSE disconnect does not fail interactions or nodes. Reconnect uses existing dedupe and canonical refresh behavior.

## Out of Scope

- Backend changes or OpenSpec edits.
- Real/paid provider execution.
- A second Product state machine based on assistant text or the direct endpoint.
- Client-generated Nodes, Bindings, occurrence IDs, or placement.
- Untracked backend character-count behavior not present on canonical `main`.
