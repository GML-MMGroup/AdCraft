# Frontend V2 Contract Alignment Matrix

Date: 2026-08-27

Frontend baseline: `AdCraft/main@877b461`

Backend authority: `/data/wenwu.meng/adWorkflow` canonical `main@3370f5a5c9ad0602ba88373394c173826b009f2b`

Scope: frontend-only alignment. Backend repositories and backend OpenSpec files are read-only.

## Status Legend

- `IMPLEMENTED`: confirmed frontend gap in this change.
- `ALREADY SUPPORTED`: current frontend behavior matches the canonical contract; retain and add evidence where needed.
- `DEFERRED`: the required backend contract is not on canonical backend `main`; do not speculate.
- `BACKEND-ONLY`: backend-only behavior with no frontend surface change.

## Core Acceptance Matrix

| Capability | Backend endpoint and public types | Concurrency contract | Events and typed errors | Current frontend support | Required frontend work and coverage | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Product source upload | `POST /api/v2/workflows/{workflow_id}/assets/upload`; multipart `file` + `metadata`; `ProjectAssetUploadResponseV2 { workflow_id, asset, pending_handoff_id }` | Stable `Idempotency-Key`; no workflow ETag on upload | `guided_product_source_pending/materialized/failed`; upload and media validation errors remain exact | Generic workflow upload exists, but drops `pending_handoff_id` and creates a new key per attempt | Normalize the receipt, retain asset/version and handoff ID, provide a stable retry key, and add API/hook tests | IMPLEMENTED |
| Product source guided interaction | Existing `POST .../chat/interactions/{interaction_id}/submit`; `GuidedInteractionV1(kind/content_kind=product_source)` and `GuidedInteractionSubmissionV1(submission_kind=product_source)` | Stable `Idempotency-Key`; carry interaction, session, and guidance revisions; this endpoint does not use `If-Match` | `guided_interaction_stale`, `guided_product_*`, precise Product validation errors | Guided interaction supports questionnaire, concept, and media review only | Add strict types/normalizers and a Product Decision Dock for upload/generate. Submit only typed actions and authoritative IDs; never parse assistant prose | IMPLEMENTED |
| Direct Product input authority | `POST /api/v2/workflows/{workflow_id}/guided/product-inputs`; typed `GuidedProductInputRequest/ResponseV2` | Workflow `If-Match` plus stable `Idempotency-Key` | Product validation/revision errors and `guided_product_*` | Intentionally not called by the frontend; the canonical UI path is Guided Interaction Submit | No frontend work; retain as backend authority for non-guided callers without creating a second frontend state machine | BACKEND-ONLY |
| Immutable image binding source | Binding `source.kind=image_asset` with `source_asset_id` and nullable-on-read `source_asset_version_id` | Binding mutations use Workflow `If-Match` and idempotency where the endpoint requires it | Binding validation/conflict errors remain exact | Reads/writes only asset ID; project assets incorrectly expose `versionId=null` | Accept legacy null on reads. Require exact asset ID plus version ID for new writes. Refuse to create a new image binding when version is unavailable. Add normalizer and request tests | IMPLEMENTED |
| Product source-only node | Authoritative Workflow node with `execution_mode=source_only`, normally Ready and prompt-inapplicable | Node remains backend-owned; no client node creation | `source_only_not_runnable` if incorrectly run; backend `all_drafts` authority skips source-only nodes without creating Provider work | Inline workbench hides controls; this change adds per-node runtime, migration, prompt-readiness, and variation guards | Hide Prompt/model/Generate/Variation/Run for Product and Video source-only nodes. Keep mixed Global Run authoritative: the frontend submits `all_drafts`, and the backend skips source-only nodes. Add focused tests | IMPLEMENTED |
| Typed Guidance interactions | Existing interaction read/submit paths; questionnaire, concept proposal, media review, and Product source variants | Revisions from the interaction/session; stable key for one revision+payload; stale refreshes authority and requires resubmit | Typed waits and exact error codes; no prose-derived state | Existing three variants are typed; submitted authority was previously treated as closed and terminal async failures retained a failed operation key | Add Product variant, preserve the Dock through authoritative `submitted`, reuse keys for uncertain transport outcomes, and rotate the key after an explicit terminal failure. Preserve typed waits and prohibit prose parsing | IMPLEMENTED |
| Duration questionnaire | Existing Guided Interaction questionnaire; `question_id=production_duration_seconds` and backend-provided 15/30/45/60 options | Existing interaction revision and idempotency contract | `guided_duration_value_invalid`, `guided_interaction_stale` | Recommended marker, numeric custom value, non-skippable behavior, draft preservation already exist | Keep behavior and add focused regression evidence; do not auto-select 30 seconds | ALREADY SUPPORTED |
| Media review | Existing media-review Guided Interaction and submit path | Existing interaction/session revisions and stable-key semantics | Review-open waits, accepted/retry/replace terminal events, stale errors | Current Decision Dock supports Accept, Retry, Replace and suppresses automatic Guidance Advance while open | Preserve and include in typed-interaction and browser regression tests | ALREADY SUPPORTED |
| Character cardinality | Journey decisions/occurrences and persisted requirement data; canonical journey projections also expose `character_phase`, occurrence IDs, and action owner fields | Read-only projection; no frontend-generated occurrence IDs | Existing journey/activity events; unknown-field strict parsing is the main risk | Canvas can render multiple backend nodes, but strict projections miss new fields and progress UI only shows aggregate counts | Normalize new character fields and render 0/1/N persisted Character occurrences from authoritative occurrence data. Do not infer from prose, title, position, or array length | IMPLEMENTED |
| Character materialization authority | Untracked backend change `fix-character-count-occurrence-materialization-authority` | Not canonical | Not canonical | Must not consume | Record as explicit backend dependency and stop at canonical-main behavior | DEFERRED |
| Storyboard Sequence presentation | Authoritative Storyboard document, full 3x3 image node, Video nodes, and backend Bindings | Backend creates IDs and graph; standard Workflow ETags for graph mutation | Storyboard planning/materialization/fanout events | Types, documents, nodes, and binding rendering exist | Preserve; add regression fixture proving a 3x3 image is one asset and bindings are not inferred | ALREADY SUPPORTED |
| Native video audio | Editing manifest/clip `preserve_native_audio` and provider capabilities | Editing mutation contract and ETag behavior unchanged | Editing/export typed errors | UI exposes Source audio and preview honors it | Preserve and include in Editing browser acceptance | ALREADY SUPPORTED |
| Positioned single-track Editing | Editing manifest with `timeline_start_seconds`, trim bounds, fixed initial duration, one video track | PATCHes use authoritative revision/ETag; commit on pointer release | Editing validation/conflict errors | Existing free-position single-track timeline, trim handles, playhead, and BGM controls | Do not rewrite. Add regression evidence that positions survive refresh and no local graph data is created | ALREADY SUPPORTED |
| Editing export | Existing explicit Export endpoint and terminal export projection | Workflow/Editing authority and stable idempotency; user-triggered only | Export-not-ready and typed export failures | Export remains explicit and terminal status is rendered; this change stabilizes the key per workflow/node/manifest revision | Assert the explicit Export request, semantic idempotency key, terminal authority transition, and that not-ready does not trigger download/import | IMPLEMENTED |
| Export download | `GET /api/v2/assets/{asset_id}/content?download=true` | No mutation concurrency | HTTP/content errors remain exact | Existing client preserves filename and MIME | Preserve and exercise in Mock browser acceptance | ALREADY SUPPORTED |
| Import export to canvas | Existing Editing import endpoint returning authoritative Node/Binding/position | Workflow `If-Match` plus stable `Idempotency-Key`; handle 412 by refresh/retry UX, not overwrite | `editing_export_imported_to_canvas` and import/export errors | API/session integration and Add to Canvas UI exist; event is missing from runtime refresh policy | Add event type/refresh policy and browser test. Never create substitute Nodes or Bindings | IMPLEMENTED |
| Imported source-only Video | Import response contains authoritative `execution_mode=source_only` Video node | Same import ETag/idempotency contract | `source_only_not_runnable`; backend `all_drafts` skips it authoritatively | Node renders and inline workbench is hidden | Guard per-node Run, variation, migration, and prompt controls. Browser-assert an empty workbench and zero Provider requests; do not filter mixed Global Run client-side | IMPLEMENTED |
| SSE refresh/reconnect | Existing `/events/stream` | Event IDs/reconnect are authoritative; no client terminal inference | Product source and export-import events are missing from whitelist/policy | Existing dedupe and canonical refresh behavior | Subscribe to missing events and refresh Workflow, assets, chat/session, runtime in policy-defined order; add dedupe/reconnect tests | IMPLEMENTED |

## Archived Frontend Handoffs and Client Contracts Since 2026-08-21

Each public change below is classified against current canonical backend `main` and the frontend baseline.

| Public change | Endpoint/type surface | ETag / idempotency | Events / errors | Frontend evidence and remaining work | Tests | Classification |
| --- | --- | --- | --- | --- | --- | --- |
| `fix-guided-media-resume-single-flight-supersession` | Existing interaction/continuation APIs | Existing stable operation identity | superseded/recovery events and typed waits | Existing typed wait and retry flow; preserve | Chat refresh/replay regression | ALREADY SUPPORTED |
| `adaptive-production-recipe` | Journey/session projections | Read-only revisions | Journey events | Existing Journey projection; no new UI state machine | Journey normalizer regression | ALREADY SUPPORTED |
| `auto-media-execution` | Agent settings/runtime endpoints | Settings ETag and operation idempotency | auto-run events/errors | Existing Manual/Automatic setting and runtime refresh | Existing settings/runtime tests | ALREADY SUPPORTED |
| `command-control` | Existing command/turn APIs | Turn revisions and idempotency | command lifecycle events | Existing typed command/turn flow | Preserve retry/refresh tests | ALREADY SUPPORTED |
| `add-editing-export-download-and-source-video-node` | Export, asset download, import-to-canvas, source-only node projection | Import Workflow ETag plus idempotency; export explicit | export/import errors; import event | Core UI exists; add missing import event and end-to-end evidence | Editing Vitest + Mock Playwright | IMPLEMENTED |
| `global-video-style-skill-runtime` | Existing Skill catalog/activation APIs | Catalog/activation authority | Skill activation errors/events | Existing style selector and activation flow | Preserve existing selector tests | ALREADY SUPPORTED |
| `asset-reference-rendition-delivery` | Asset content/rendition URLs | Read-only | asset delivery errors | Existing content URL and normalizers | Asset URL regression | ALREADY SUPPORTED |
| `guided-product-upload-client-contract` | Workflow upload, Product guided interaction, direct Product input endpoint | Upload/submit stable keys; direct endpoint also uses Workflow ETag | `guided_product_*` and Product typed errors | Main implementation area of this change | API, normalizer, Dock, reconnect tests | IMPLEMENTED |
| `add-v2-guided-product-image-upload` | Workflow asset upload plus `product_source` Guided Interaction; Main and Multiview typed source actions | Upload and submit require stable `Idempotency-Key`; interaction carries session, interaction, and guidance revisions | `guided_product_*`, stale revision, unreadable asset, and multiview compilation errors | ProductSourceDecisionDock uses the deployed guided submit path, preserves ordered AssetVersions and pending handoff IDs, and never routes through Media Review | Product selection, normalizer, Dock, typed wait, replay, and Mock Playwright coverage | IMPLEMENTED |
| `bgm-provider-routing` | Existing BGM node/provider policy | Existing Node run authority | provider capability/errors | Existing BGM model and Editing integration | Preserve BGM tests | ALREADY SUPPORTED |
| `production-integrity` | Runtime/checkpoint projections | Read-only revisions | integrity/recovery errors | Existing runtime authority; no inference | Runtime policy regression | ALREADY SUPPORTED |
| `fix-agent-canvas-project-catalog-resilience` | Project catalog endpoints | Catalog authority | exact catalog errors | Existing Workspace provider resilience | Existing Workspace tests | ALREADY SUPPORTED |
| `typed-binding-runtime` | Binding source/target union | Workflow ETag | binding lifecycle/errors | Generic typed binding exists; immutable image version is missing | Binding normalizer/request tests | IMPLEMENTED |
| `structured-contract-registry-parity` | Schema/registry generation | N/A | strict unknown-field behavior | Handwritten types remain vulnerable; this matrix supplies real-contract tests for touched surfaces | Realistic fixture normalizer tests | IMPLEMENTED |
| `paid-continuation-attempt-identity` | Turn/continuation projections | Attempt identity and stable retry keys | continuation retry/replay errors | Existing failed-Turn Retry; do not auto-resend | Preserve Retry tests | ALREADY SUPPORTED |
| `paid-golden-journey-resume-orchestration` | Creative session/timeline/runtime | Session revisions | resume/recovery events | Existing refresh/reconnect authority | Reconnect/dedupe regression | ALREADY SUPPORTED |
| `provider-model-policy-parity` | Model catalog/capability fields | Read-only/model selection revisions | provider policy errors | Existing per-node media model selectors | Existing model tests | ALREADY SUPPORTED |
| `harden-agent-canvas-specialist-operation-recovery` | Expert activity/turn recovery projections | Operation identity | expert/operation recovery events | Existing activity dedupe and Retry | Preserve activity/retry tests | ALREADY SUPPORTED |
| `make-agent-canvas-guidance-optional-and-deferrable` | Typed proposal/interaction actions | Existing interaction revisions | defer/exclude typed actions | Existing backend-returned action rendering | Proposal action tests | ALREADY SUPPORTED |
| `curated-video-style-skill-catalog` | Skill catalog | Catalog authority | catalog errors | Existing style rail; no contract work | Existing style tests | ALREADY SUPPORTED |
| `refine-agent-canvas-guided-creative-control` | Guided interaction/creative session | Existing revisions | typed guidance waits | Existing typed flow; Product kind missing | Product-specific tests | IMPLEMENTED |
| `guided-session-runtime` | Creative session, timeline, runtime | Monotonic stage/session revisions | journey/runtime events | Existing canonical refresh and monotonic journey handling | Preserve journey tests | ALREADY SUPPORTED |
| `simplify-agent-canvas-world-setting-context` | World Setting text node and bindings | Workflow ETag | node/binding events | Existing node/workbench behavior | Existing World Setting tests | ALREADY SUPPORTED |
| `stabilize-single-model-agent-intake` | Timeline/turn projections | Turn/session authority | `agent_turn_waiting` | Existing waiting state and refresh policy | Existing waiting/reconnect tests | ALREADY SUPPORTED |

## Additional Current Contracts

| Contract | Result |
| --- | --- |
| `establish-guided-duration-question-and-sequence-authority` | Duration interaction already supported; sequence authority remains backend-owned. |
| `complete-storyboard-fanout-and-production-closure` | Storyboard documents, full-grid image, fanout events, and Editing preparation already supported. |
| `editing-single-track-free-position-backend-handoff` | Existing timeline behavior is the implementation baseline; this change only adds acceptance evidence. |
| Canonical character commits on backend `main` | Consume persisted character projection fields and render 0/1/N occurrences. |
| Untracked character-count OpenSpec | Explicit dependency; not a public canonical contract and not implemented here. |

## Completion Rule

Alignment is complete only when every `IMPLEMENTED` row has code and automated evidence, every `ALREADY SUPPORTED` row retains cited behavior, every `DEFERRED` row remains unimplemented without inference, and no backend repository has changed.

## Verification Evidence

- Product upload, Product Guided Interaction, immutable AssetVersion references, source-only guards, typed waits, event replay, Character 0/1/N projections, Storyboard single-grid presentation, and Editing behavior: 8 focused Vitest files, 203 tests passed.
- Product Main upload, ordered Multiview upload, Generate with empty source authority, pending handoff propagation, source-only Product state, and zero Provider/Guidance Advance calls: 3 Product Mock Playwright tests passed.
- Editing export/download/import acceptance: Playwright Mock-media test passed for an explicit 30-second export, authoritative completion, download, source-only Video import, empty source-only workbench, preview, downstream Binding, Workflow ETags, stable idempotency, and zero Provider execution requests.
- Static contract safety: `npm run typecheck` passed.
- Production packaging: `npm run build` passed with 820 modules transformed.
- Backend integrity: read-only inspection found `/data/wenwu.meng/adWorkflow` on `main@3370f5a5c9ad0602ba88373394c173826b009f2b`; this frontend change made no backend edits. A pre-existing untracked backend OpenSpec directory was left untouched.
- Real-provider acceptance: intentionally deferred. This change stops before any real or paid provider request, as required.
