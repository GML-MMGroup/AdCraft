## Current Flow

The standalone backend contains the complete execution-result publication
boundary:

```text
provider result
-> canonical asset/version registration
-> pending selection recorded in execution state
-> execution-local selected overlay used by the scheduler
-> one terminal authoring revision published
-> selected_for_slot relation and event published
-> downstream dependency becomes ready
```

The migrated monorepo backend calls the publication collaborator but omits its
module, import, constructor initialization, and focused tests. Real provider
calls can complete, but scheduler terminal commit raises
`AttributeError`. The workflow projection then exposes failed main slots with
null selected IDs, while generated files and working-version metadata still
exist. Multi-view slots never call a provider because their selected-main
dependency is absent.

The Pi migration already defines typed Agent contexts and owner-specific
handoffs, but the final migration gate did not prove that the deployed package
preserved those boundaries together with the Python execution path.

## Target Flow

```text
POST /run
-> load canonical authoring state and execution base version
-> select only missing required slots
-> invoke isolated Pi expert context when cognition is required
-> compile one owner-local provider prompt
-> provider succeeds
-> register canonical asset/version
-> record pending selection durably
-> hydrate the execution-local workflow for downstream scheduling
-> continue eligible dependent slots
-> converge execution
-> publish all pending selections in one idempotent terminal authoring revision
-> publish selected_for_slot relations and selected-version events
-> rebuild workflow/runtime projections
```

Provider calls remain outside authoring transactions. Publication uses a short
canonical authoring commit after provider output is already durable. A repeated
publication attempt resolves the existing execution-result revision and does
not create a duplicate asset or selected relation.

## HTTP API Contract

### `POST /api/v2/workflows/{workflow_id}/run`

- **Request body:** Existing `WorkflowV2RunRequest`; unchanged.
- **Response body:** Existing `WorkflowV2RunStartResponse`; unchanged.
- **Behavior:** `fill_missing_required_slots` skips slots with valid selected
  versions. Successful provider results become execution-local selections and
  are published canonically at terminal convergence.
- **Errors:** Existing workflow-not-found, active-execution, provider, and
  runtime errors remain. Missing internal service wiring must be caught before
  runtime and must not appear as a provider-generation failure.
- **Compatibility:** No frontend change.

### `GET /api/v2/workflows/{workflow_id}`

- **Request body:** None.
- **Response body:** Existing `WorkflowV2`; unchanged.
- **Behavior:** After publication, successful slots expose non-null
  `selected_asset_id` and `selected_version_id`.
- **Errors/compatibility:** Unchanged.

### `GET /api/v2/workflows/{workflow_id}/assets`

- **Request body:** None.
- **Response body:** Existing workflow-scoped V2 asset list; unchanged.
- **Behavior:** Published selected versions resolve to canonical media URLs.
- **Errors/compatibility:** Unchanged.

### `GET /api/v2/workflows/{workflow_id}/runtime`

- **Request body:** None.
- **Response body:** Existing `WorkflowV2RuntimeSnapshot`; unchanged.
- **Behavior:** Runtime is derived from the latest canonical workflow and
  execution overlay. Terminal success cannot be replaced by an older queued or
  failed snapshot.
- **Errors/compatibility:** Unchanged.

### `GET /api/v2/workflows/{workflow_id}/events`

- **Request body:** None; existing cursor query is unchanged.
- **Response body:** Existing event-list contract; unchanged.
- **Behavior:** `slot_selected_version_updated` follows readable selected state.
- **Errors/compatibility:** Unchanged.

### `GET /api/v2/workflows/{workflow_id}/events/stream`

- **Request body:** None; existing `after_seq` query is unchanged.
- **Response body:** Existing SSE event contract; unchanged.
- **Behavior:** Corrected publication events are observable without requiring
  the Run request to remain open.
- **Errors/compatibility:** Unchanged.

### `POST /api/v2/workflows/plan-from-chat`

- **Request body:** Existing V2 planning request; unchanged.
- **Response body:** Existing planning response; unchanged.
- **Behavior:** Pi planning and expert calls consume typed context models only.
- **Errors:** Existing structured Agent errors remain.
- **Compatibility:** No frontend change.

### `POST /api/v2/workflows/{workflow_id}/chat-actions`

- **Request body:** Existing chat-action request; unchanged.
- **Response body:** Existing chat-action response; unchanged.
- **Behavior:** Targeted Character or Scene work receives only the exact target
  context, bounded conversation summary, permitted screenplay slice, style
  scope, and reference summaries.
- **Errors/compatibility:** Unchanged.

## Internal Service Interface Contract

### `V2ExecutionResultPublicationService`

The deployed backend SHALL include the canonical implementation and its direct
dependencies.

#### `record_pending_selection()`

- **Inputs:** `workflow_id`, `execution_id`, `slot_id`, `asset_id`,
  `version_id`.
- **Output:** Updated execution state or `None` when the execution does not
  exist.
- **Invariant:** Updates only `pending_selections`; it does not mutate public
  authoring state.
- **Ordering:** After canonical asset/version registration and before terminal
  publication.

#### `uses_pending_publication()`

- **Inputs:** `workflow_id`, optional `execution_id`.
- **Output:** Boolean.
- **Invariant:** Returns true only for an execution with a positive
  `authoring_base_state_version`.
- **Ordering:** Before applying execution-local overlay or terminal publishing.

#### `apply_pending_selections()`

- **Inputs:** current `WorkflowV2`, `execution_id`.
- **Output:** Deep-copied execution-local `WorkflowV2`.
- **Invariant:** Public authoring state remains unchanged. The copy may expose
  pending selected IDs to downstream dependency evaluation.

#### `publish_terminal()`

- **Inputs:** `workflow_id`, `execution_id`, optional candidate workflow.
- **Output:** Current or newly published `WorkflowV2`.
- **Invariants:**
  - at most one execution-result authoring revision per execution;
  - publication uses optimistic `authoring_base_state_version`;
  - repeated calls are idempotent;
  - selected relations are not duplicated;
  - concurrent authoring advancement defers publication instead of overwriting
    user edits.
- **Ordering:** After scheduler convergence and before the execution is exposed
  as fully published.

### `WorkflowV2Service`

- **Constructor invariant:** Every collaborator referenced by a production
  method is imported and initialized, including
  `_execution_result_publication`.
- **Provider-result ordering:** register asset/version, record pending
  selection, hydrate execution-local state, transition slot, then continue
  scheduling.
- **Terminal ordering:** converge latest slot runtime, publish terminal
  selections, rebuild/read canonical projection, persist terminal execution
  state, and emit terminal execution event.
- **Failure invariant:** An old in-memory workflow or execution snapshot cannot
  overwrite a selected version already committed by publication.

### `V2AgentContextBuilder` and typed operation contexts

- **Inputs:** canonical workflow identifiers, exact target identifiers,
  normalized user instruction, bounded conversation source, and canonical
  selected reference metadata.
- **Outputs:** one Pydantic context subtype such as
  `ProductExpertAgentContext`, `CharacterExpertAgentContext`,
  `SceneExpertAgentContext`, `BgmExpertAgentContext`,
  `TargetedRevisionAgentContext`, or `QuickMediaAgentContext`.
- **Invariants:**
  - `extra="forbid"` remains enabled;
  - contexts contain no media bytes, base64/data URLs, credentials, absolute
    paths, full workflow JSON, or sibling full prompts;
  - each invocation receives a fresh immutable serialized value;
  - parallel expert calls never share a mutable context object;
  - only compact canonical screenplay/style/continuity slices and reference
    summaries may be shared.

### Pi Sidecar operation boundary

- **Inputs:** one operation name, one invocation identity, and one typed context
  payload.
- **Output:** existing structured Agent result and runtime events.
- **Invariant:** A child expert cannot inherit another child expert's complete
  prompt, tool history, or operation messages. Expert handoff remains bounded
  through the approved star topology.

## Pydantic Schema Contract

No public request or response model changes.

Existing internal models remain canonical:

- `WorkflowV2RunRequest`
- `WorkflowV2RunStartResponse`
- `WorkflowV2`
- `WorkflowV2RuntimeSnapshot`
- `ProductExpertAgentContext`
- `CharacterExpertAgentContext`
- `SceneExpertAgentContext`
- `BgmExpertAgentContext`
- `TargetedRevisionAgentContext`
- `QuickMediaAgentContext`

Production Agent contexts SHALL continue to use canonical English field names
and `ConfigDict(extra="forbid")`. Adding an arbitrary context dictionary as a
compatibility escape hatch is prohibited.

Execution state continues to carry:

```text
authoring_base_state_version: positive integer
pending_selections: map[slot_id, {slot_id, asset_id, version_id}]
execution_result_revision_status:
  pending | published | no_change | deferred
execution_result_revision_no: optional positive integer
```

## Event/Error Contract

Successful execution preserves two observable phases:

```text
asset_version_created
-> slot_working_version_updated
-> slot_generation_completed
-> downstream slot lifecycle events through the execution-local selection overlay

terminal authoring commit
-> selected state becomes readable
-> slot_selected_version_updated
-> terminal execution event
```

Exact intermediate ordering may retain current implementation details.
`slot_selected_version_updated` must not precede readable canonical selected
state, while downstream scheduling within the active execution may use the
durable pending-selection overlay.

Stable behavior:

- `execution_result_revision_deferred` remains the non-destructive response to
  concurrent authoring advancement.
- Provider hard failures remain provider errors.
- Publication infrastructure failure remains an internal execution error and
  must preserve already durable provider output for retry; it must not be
  mislabeled as media-generation failure.
- Missing module/import/constructor wiring is a build/test failure and must
  never reach a user workflow.

## Persistence/Metadata Contract

- SQLite is the canonical V2 authoring source of truth.
- `workflow.json` remains a rebuildable operational projection.
- Provider output remains in canonical `data/assets/` storage.
- Execution runtime remains under
  `data/v2/runs/{workflow_id}/executions/{execution_id}/`.
- Pending selections remain execution metadata until terminal publication.
- Selected media remains represented by slot selected IDs and a
  `selected_for_slot` relation carrying `version_id` and
  `source_execution_id`.
- No legacy directory or historical workflow recovery is introduced.

## Test Strategy

### Focused failing tests first

1. Construct the deployed `WorkflowV2Service` and assert the publication
   collaborator exists and has the required callable interface.
2. Simulate provider success and assert pending selection, terminal selected
   IDs, selected relation, and selected-version event.
3. Publish the same execution twice and assert one authoring revision and one
   selected relation.
4. Apply an older failed/queued snapshot after success and assert selected
   state remains successful.
5. Run fill-missing twice and assert a valid selected main slot is not sent to
   the provider again.
6. Assert a selected main image unlocks only its matching multi-view slot.

### Agent isolation tests

- Place unique sentinel strings in Product, Character, Scene, BGM, Shot, and
  sibling item prompts.
- Capture each serialized Pi input and final provider prompt.
- Assert only target-owned text and permitted compact summaries are present.
- Run independent expert calls concurrently and assert contexts and traces
  retain distinct invocation identities.
- Assert context models reject arbitrary full workflow dictionaries, media
  bytes, base64/data URLs, and unknown fields.

### Critical-path verification

- Run deterministic fake providers through main images, multi-views,
  storyboard cells, shot videos, and Final Composition.
- Run the relevant integration/media suites.
- Run the full backend suite once at the merge gate because this change touches
  shared scheduling, authoring publication, asset selection, and the V2
  generation pipeline.
- After merge readiness and runtime quiescence, run one new real-provider
  workflow. Inspect the actual media and prove multi-view provider requests
  referenced the selected matching main versions.

## Rollout

1. Implement in a dedicated branch/worktree targeting the monorepo backend
   package.
2. Restore only production-reachable missing dependencies; do not bulk-copy
   unrelated repository differences.
3. Complete focused and layered verification.
4. Record a dated correction in the historical Pi equivalence verification:
   the prior gate did not detect deployment-package dependency omission.
5. Merge only when no workflow execution is active.
6. Restart the backend/Pi supervisor once.
7. Create a new workflow and complete real acceptance.

The historical failed workflow is retained only as diagnostic evidence and is
not repaired.

## Risks

- **Blind file synchronization may overwrite newer monorepo behavior.**
  Mitigation: restore symbols and direct dependencies intentionally, compare
  call contracts, and keep the patch scoped.
- **Publication retry may duplicate selected relations.**
  Mitigation: retain execution-result revision and relation idempotency tests.
- **Optimistic publication may conflict with user edits during a long run.**
  Mitigation: preserve existing deferred-publication behavior.
- **Context-isolation tests may reject harmless shared summaries.**
  Mitigation: test forbidden full-prompt sentinels and structural payloads, not
  generic words.
- **A fake critical path may miss provider-specific behavior.**
  Mitigation: perform one controlled real-provider acceptance after
  deterministic correctness is established.
