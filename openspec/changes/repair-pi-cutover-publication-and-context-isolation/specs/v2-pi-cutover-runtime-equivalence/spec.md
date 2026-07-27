## ADDED Requirements

### Requirement: The deployed V2 package shall include every referenced production collaborator

The deployed backend package SHALL include, import, and initialize every
service referenced by `WorkflowV2Service` production execution paths. This
includes `V2ExecutionResultPublicationService`.

#### Scenario: Workflow service is constructed

- **WHEN** the deployed `WorkflowV2Service` is constructed with isolated V2
  persistence
- **THEN** `_execution_result_publication` exists
- **AND** it exposes `uses_pending_publication`, `record_pending_selection`,
  `apply_pending_selections`, and `publish_terminal`
- **AND** no workflow execution is required to discover missing wiring

#### Scenario: A production symbol references an absent module or collaborator

- **WHEN** the migration parity test scans the bounded Pi/V2 production roots
- **THEN** verification fails before merge
- **AND** the missing dependency cannot be classified as a provider failure

### Requirement: Successful provider results shall publish selected versions exactly once

The backend SHALL publish a successful Global Run provider result exactly once.
After the result is registered as a canonical asset version, the owning
execution shall durably record the pending selection and publish it through at
most one execution-result authoring revision.

#### Scenario: A main-image provider succeeds

- **WHEN** the canonical main-image asset version is registered
- **THEN** the execution records its `slot_id`, `asset_id`, and `version_id` in
  `pending_selections`
- **AND** the execution-local scheduler can resolve that selection
- **AND** terminal publication writes the slot selected IDs
- **AND** one `selected_for_slot` relation exists
- **AND** `slot_selected_version_updated` is observable after the selected
  state is readable

#### Scenario: Terminal publication is repeated

- **WHEN** the same execution is recovered or terminal publication is invoked
  more than once
- **THEN** the existing execution-result revision is reused
- **AND** no duplicate asset version or selected relation is created

#### Scenario: Authoring advances during execution

- **WHEN** the current authoring state version differs from
  `authoring_base_state_version`
- **THEN** terminal publication is deferred
- **AND** user authoring changes are not overwritten
- **AND** `execution_result_revision_deferred` identifies the pending slot IDs

### Requirement: Published successful state shall be monotonic

A successfully published selected version SHALL NOT be erased by an older
queued, running, waiting, failed, or selected-null workflow/execution snapshot.

#### Scenario: A stale failure writer finishes after success

- **WHEN** successful publication is committed before a stale failure path
  attempts to persist its older snapshot
- **THEN** the slot remains selected and usable
- **AND** the successful asset remains visible through
  `GET /api/v2/workflows/{workflow_id}/assets`
- **AND** runtime does not regress the slot to failed

### Requirement: Fill-missing execution shall preserve selected assets and unlock dependencies

The backend SHALL preserve valid selected assets during fill-missing execution.
`POST /api/v2/workflows/{workflow_id}/run` in
`fill_missing_required_slots` mode shall not submit a provider call for a slot
with a valid selected asset version.

#### Scenario: A selected main image already exists

- **WHEN** a later Global Run evaluates the workflow
- **THEN** the main-image slot is skipped
- **AND** its matching multi-view slot may become ready
- **AND** an unrelated sibling multi-view slot cannot consume that main image

#### Scenario: A main image succeeds during the active execution

- **WHEN** its pending selection is visible in the execution-local overlay
- **THEN** the matching multi-view slot can be scheduled in the same execution
- **AND** its typed reference bundle contains the selected matching main
  version

### Requirement: Pi expert contexts shall remain structurally isolated

Every Pi expert invocation SHALL receive one fresh typed context containing
only target-owned fields, permitted compact canonical summaries, and selected
reference summaries.

#### Scenario: Independent Product, Character, Scene, and BGM experts run

- **WHEN** expert planning is executed in parallel
- **THEN** each child has a distinct invocation identity and immutable context
- **AND** no child context contains another child's complete prompt, provider
  payload, tool history, or mutable message object

#### Scenario: A Character expert context is built

- **WHEN** Product, Scene, and sibling Character prompts contain unique
  sentinels
- **THEN** none of those full-prompt sentinels appears in the Character Pi
  input or Character provider prompt
- **AND** compact screenplay facts and selected Character references may remain

#### Scenario: A Scene expert context is built

- **WHEN** Character, Product, and sibling Scene prompts contain unique
  sentinels
- **THEN** none of those full-prompt sentinels appears in the Scene Pi input or
  Scene provider prompt

#### Scenario: Unsafe context is supplied

- **WHEN** a context contains an unknown field, full workflow document, media
  bytes, base64/data URL, credential, absolute path, or sibling full prompt
- **THEN** deterministic validation rejects it before the Pi or media provider
  call

### Requirement: Pi migration equivalence shall include a real V2 media acceptance

Migration SHALL NOT be declared complete solely from fake Pi, protocol,
source-scan, or media-free planning evidence.

#### Scenario: Merge readiness is evaluated

- **WHEN** focused and relevant deterministic suites pass
- **THEN** one new workflow is run through main images, multi-views,
  storyboard cells, shot videos, and Final Composition using configured real
  providers
- **AND** generated multi-views are visually and structurally distinct from
  duplicate main images
- **AND** provider audit metadata proves each multi-view referenced its matching
  selected main version
- **AND** canonical media URLs return successfully through the active frontend
  proxy

#### Scenario: Historical evidence contradicts the prior equivalence record

- **WHEN** a production workflow exposes a missing migrated dependency
- **THEN** the prior verification record is corrected with dated evidence
- **AND** migration remains incomplete until this change passes
