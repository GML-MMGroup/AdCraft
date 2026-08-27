# Agent Chat Stage Threads Design

## Scope

The first optimization round compresses the Agent Canvas timeline without changing backend authority or interaction behavior. It groups execution records into readable stage threads, collapses completed proposals to their selected result, deduplicates document references, and aggregates repeated Script Writer activity.

Out of scope: new workflow APIs, a new journey state machine, arbitrary frontend translation, changes to Guided Interaction submission, and macro production dashboards beyond a compact guidance summary.

## Design Principles

- Treat backend identifiers and statuses as authoritative.
- Group by typed relationships such as `capability_id`, `proposal_id`, `receipt_id`, and `document_id`; never infer stages from message text, node position, or bindings.
- Keep current Guided Interaction fixed above the composer and fully interactive.
- Keep failed activities and failed receipts visible with their existing recovery controls.
- Use one pure projection module so timeline compression is independently testable.
- Keep the monochrome visual system and use spacing, typography, and expansion state for hierarchy.

## Projection Model

`buildStageThreadTimeline(items)` converts normalized `ChatTimelineItemV2[]` into display units:

- `message`: real user and Agent conversation.
- `stage_thread`: one capability thread containing its latest activity, related proposals, related planning records, and related receipts.
- `document`: the highest revision for each `document_id`.
- `standalone`: artifacts, command plans, decisions, and unassociated or failed receipts that must remain independently visible.

Planning entries retain a frontend-only provenance marker during normalization. The marker distinguishes backend `planning_progress` from genuine conversation messages and carries typed `capability_id` and `proposal_id` metadata when available.

## Thread Behavior

- A working or failed thread is expanded.
- A completed thread is collapsed by default.
- A completed proposal shows only the applied option title and a short summary.
- Expanding history reveals the existing activity, proposal, and receipt details.
- Repeated `script_authoring` activities are one thread with a revision count.
- Successful receipts represented by an applied proposal are absorbed into the thread summary.
- Failed, rejected, `not_applied`, and `applied_with_run_error` receipts remain visible inside the thread.
- An open proposal that is not the active Guided Interaction remains visible as history, but never creates a second interactive card.

## Guidance Summary

Replace the large journey card with a compact progress strip showing the current stage and three counts derived from the authoritative journey state:

- Creative decisions.
- Storyboard progress.
- Delivery progress.

It does not infer completion from canvas nodes or chat text and does not expose the old metadata list.

## Components

- `stageThreadProjection.ts`: pure grouping and deduplication.
- `StageThread.tsx`: collapsed and expanded thread presentation.
- `GuidanceSessionProgress.tsx`: compact authoritative progress summary.
- `AgentCanvasChatPanel.tsx`: renders projected units while preserving the pinned current interaction and existing handlers.

## Accessibility And Motion

- Threads use native buttons for expand/collapse and expose `aria-expanded`.
- Status text remains available without relying on color.
- Transitions are limited to opacity and small vertical movement.
- `prefers-reduced-motion` disables transitions.

## Verification

- Planning, activity, proposal, and receipt collapse into one capability thread.
- Completed proposals expose only the selected result until expanded.
- Three Script Writer activities render as one thread with three revisions.
- Document references keep only the newest revision per `document_id`.
- Failed operations and recovery controls remain visible.
- Current Guided Interaction remains directly above the composer.
- Focused tests, typecheck, and build pass.
