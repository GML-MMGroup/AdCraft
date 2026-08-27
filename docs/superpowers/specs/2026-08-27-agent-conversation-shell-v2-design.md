# Agent Conversation Shell v2 Design

## Summary

Unify the frontend Agent Canvas conversation experience into one coherent Conversation Shell without changing backend contracts. This phase combines the active Decision Dock, scoped error recovery, composer context visibility, and natural message typography while preserving Stage Threads, Canvas authority, and existing request payloads.

The frontend must use only existing backend facts such as timeline item type, message key, statuses, error codes, Guided Interaction state, active Skill, mentioned nodes, and selected assets. It must not infer semantic response blocks from natural-language text.

## Scope

This is one frontend release phase with four independently testable subprojects:

1. Conversation Shell layout and shared presentation models.
2. Decision Dock and interaction-local submission recovery.
3. Recovery Surface and Composer Context Tray.
4. Natural message typography, responsive behavior, and integrated regression coverage.

The subprojects may be delivered sequentially, but they share one visual system and one final acceptance gate.

## Existing Foundation

The phase builds on the current frontend:

- Stage Threads group planning, capability activity, proposal history, receipts, and document revisions.
- Guidance progress is already compact.
- Current Guided Interaction is already outside timeline scrolling and directly above the composer.
- Composer already supports a workflow Skill, mentioned Canvas nodes, and image assets.
- The API client already preserves HTTP status, backend code, details, violations, and suggested actions in `V2ApiError`.
- Natural Agent messages currently carry authoritative text rather than typed semantic blocks.

The detailed Decision Dock behavior remains defined by `docs/superpowers/specs/2026-08-27-agent-chat-decision-dock-design.md`, except that it is now one subproject of this larger frontend phase.

## Goals

1. Make the Agent panel read as one product surface instead of separate timeline, form, error, and composer widgets.
2. Preserve a clear hierarchy between natural conversation, historical production activity, current user action, recovery, and message context.
3. Keep interaction and message drafts intact during pending work and recoverable failure.
4. Show each error at the location where the user can resolve it.
5. Make Skill, asset, and node context visible before message submission.
6. Improve Agent message readability without inventing semantic structure.
7. Preserve the approved monochrome visual language.
8. Keep backend state and existing request payloads authoritative.
9. Support the normal 390px Agent rail, the existing 330px narrow rail, keyboard operation, and reduced motion.

## Non-goals

- Adding backend `message_blocks`, response sections, or any other typed-message contract.
- Parsing natural language to guess Summary, Decision, Result, or Next action.
- Changing Guided Interaction request unions, proposal actions, Stage Thread projection, or Canvas execution.
- Adding a global state library, markdown parser, animation library, analytics event, modal, or side sheet.
- Redesigning Skill discovery, asset library pages, node cards, document dialogs, or the Editing panel.
- Replacing backend validation or deciding retryability from HTTP text alone.
- Creating frontend-only success receipts or workflow state.

## Visual Direction

Use the existing Agent chat monochrome palette:

- canvas: `#0a0a0a`;
- panel: `#151515`;
- raised surface: `#202020`;
- selected surface: `#292929`;
- border: `#353535`;
- strong border: `#4a4a4a`;
- primary text: `#f5f5f5`;
- secondary text: `#a3a3a3`;
- muted text: `#707070`.

Do not add gradients, glow, colored severity fills, decorative status dots, oversized typography, or nested outer cards. Hierarchy comes from spacing, text weight, borders, selection state, and progressive disclosure.

## Shell Architecture

The conceptual composition is:

```text
AgentConversationShell
├── ConversationHeader
├── Timeline
│   ├── NaturalMessage
│   ├── StageThread
│   └── DocumentReference
├── DecisionDock
├── RecoverySurface
├── ContextTray
└── Composer
```

`AgentCanvasChatPanel` may remain the concrete composition component. The design does not require renaming the existing public component.

### Vertical order

```text
Header
Timeline
Active Decision Dock
Recovery Surface
Context Tray
Composer
```

Rules:

- Timeline is the primary scroll owner.
- Header and Composer remain fixed.
- Decision Dock remains outside Timeline and directly above the Composer area.
- Decision Dock owns only its middle body scroll and uses no more than approximately half the available panel height.
- Recovery Surface appears only when the error is not owned by a more specific region.
- Context Tray occupies one compact row when collapsed and disappears entirely when it has no visible context.
- Removing Decision Dock, Recovery Surface, or Context Tray removes its layout space immediately.
- Stage Threads, documents, and natural messages remain inside Timeline.

## State Ownership

`useAgentCanvasChat` remains the owner of authoritative chat state, pending operations, refresh, errors, notices, and submission actions. Existing workflow, runtime, asset, and Skill state remain owned by their current modules.

The new frontend models are projections only:

```ts
type DecisionDockIssue = {
  summary: string;
  detail: string | null;
  fieldId: string | null;
  retryable: boolean;
};

type ConversationRecoveryView = {
  scope: "interaction" | "composer" | "context" | "timeline" | "workflow";
  title: string;
  message: string;
  technicalDetail: string | null;
  action: "retry" | "refresh" | "review" | "none";
};

type ComposerContextView = {
  skill: ComposerSkillContext | null;
  assets: ComposerAssetContext[];
  nodes: ComposerNodeContext[];
  uploadState: "idle" | "uploading" | "failed";
};
```

These models may describe existing state but never become an alternate source of workflow truth.

## Decision Dock

The Decision Dock remains directly expanded while an authoritative open Guided Interaction exists.

It provides:

- one shared frame for concept choice, questionnaire, and media review;
- directly visible active options;
- complete selected summary and two-line unselected summaries;
- collapsed References and More sections;
- one primary submission action;
- pending lock that preserves all form values;
- backend-confirmed close behavior;
- local field and submission issues;
- technical details hidden by default.

The current Guided Interaction request union does not represent a concept `revise` action. The Dock must not expose an unsupported Revise request. Custom direction continues to represent a new user-authored direction, and Proposal revision remains on its existing Proposal action path.

## Error Ownership and Recovery

### Ownership map

- Decision Dock submission error: Decision Dock.
- Composer message submission error: Composer.
- Asset upload or attachment error: Context Tray.
- Timeline loading error: Timeline.
- Workflow contract or panel refresh error: panel-level Recovery Surface.
- Node execution error: node card and related Stage Thread.

An error must have one presentation owner. It must not appear simultaneously in Decision Dock, global error, and notice surfaces.

### Recovery presentation

Every owned error displays:

1. a user-facing title;
2. one concise explanation of what happened or what the user should do;
3. one allowed recovery action, or no action when none is valid;
4. a closed `Technical details` disclosure when raw data exists.

Examples of primary copy:

- `Response could not be submitted`;
- `Conversation could not be refreshed`;
- `Asset upload was interrupted`;
- `The workflow changed before this response was saved`.

Raw `Request failed with status 422`, `Request failed with status 500`, `Invalid proposal...`, schema paths, and backend codes may appear only inside Technical details.

### Recovery action rules

- Show Retry only when an existing action or backend state already permits retry.
- Use Refresh for stale authoritative data when refresh is safe.
- Use Review for conflicts that require the user to inspect a newer option or workflow state.
- Do not create Retry for contract validation, permissions, unsupported actions, or non-replayable operations.
- Preserve user text, selections, custom directions, replacement instructions, and selected references after recoverable failure.
- Clear an owned error when its source operation succeeds, its authority is replaced, or the user explicitly dismisses a dismissible informational state.

## Composer Context Tray

The Context Tray sits immediately above the Composer and shows the context that will accompany the next user message.

### Collapsed presentation

```text
Skill · Video Style    Assets · 2    Nodes · 1    ›
```

Do not render the Tray when there is no active Skill, attached asset, mentioned node, or upload state.

### Expanded groups

#### Skill

- Show Skill icon, user-facing title, and one short summary.
- Do not show version, run ID, category, digest, or backend source metadata.
- Opening Skill selection continues to use the existing selector.
- Skill is workflow-level context and remains selected after message acceptance.

#### Assets

- Show thumbnail, display name, and media type.
- Reuse the existing asset library and upload capability.
- Allow removal from the next message context without deleting the library asset.
- Show upload progress and upload failure beside the affected asset.
- Show Retry only when the existing upload operation is safely retryable.
- Do not show bindings, semantic reference roles, source IDs, or storage metadata.

#### Nodes

- Show node icon and user-facing node title.
- Clicking focuses the Canvas node.
- Removing a node removes only the next-message mention.
- Do not show node ID, revision, binding type, or execution ID.

### Context lifecycle

- Deduplicate assets and nodes by their authoritative IDs.
- Keep all context visible before sending.
- Preserve message-scoped assets and node mentions when message submission fails.
- Clear message-scoped assets and node mentions only after backend acceptance.
- Keep workflow Skill after message acceptance.
- At narrow width, collapse to counts and stack expanded groups vertically.

## Composer

The Composer remains the only free-form message input.

It continues to provide:

- multiline text input;
- node and asset entry;
- Skill entry;
- one Send action;
- existing disabled and pending behavior.

The Composer must not duplicate full asset, node, or Skill details after the Context Tray is introduced. Composer tools become entry actions; Context Tray becomes the review and removal surface.

Message draft and context clear only after backend acceptance. A failed send leaves both intact and presents its Recovery View in the Composer region.

## Natural Message Presentation

### User messages

- Right aligned.
- Compact raised gray bubble.
- 13px text with readable wrapping.
- No redundant user label on every consecutive message.

### Agent messages

- Left aligned.
- Plain content on the panel surface rather than a large bubble.
- Show Agent identity only on the first item in a consecutive Agent-message run.
- Use smaller spacing inside a run and larger spacing when speaker changes.
- Keep authoritative backend text unchanged.

### Markdown

Improve the existing markdown-aware renderer and CSS for:

- headings;
- paragraphs;
- ordered and unordered lists;
- block quotes;
- links;
- inline code;
- code and JSON blocks.

Rules:

- headings use modest weight and spacing, not display typography;
- long links wrap;
- code blocks use a dark inset surface and horizontal scrolling;
- very long messages expose `Show more` without deleting or changing text;
- timestamps appear only on hover, focus, or explicit detail expansion;
- never create semantic cards by matching `Summary:`, `Result:`, `Next action:`, Chinese equivalents, or any other keywords.

### Non-natural items

Planning progress, capability activity, proposals, receipts, and documents continue to use their typed presentation components. They must not be converted back into ordinary Agent messages.

## Scroll and Update Coordination

- Follow new Timeline content only when the user is already following the latest item.
- Do not force-scroll when the user is reading historical Stage Threads.
- Opening Decision Dock, Context Tray, More, References, or Technical details must not change Timeline scroll ownership.
- Removing an accepted Decision Dock may reveal more Timeline space without jumping historical scroll position.
- Context Tray expansion may reduce Timeline height but must not reset its scroll offset.

## Responsive Behavior

### 390px normal rail

- Maintain one-row collapsed Context Tray.
- Keep readable option and message width.
- Keep Decision Dock header and footer visible.
- Keep one primary button visually dominant.

### 330px narrow rail

- Stack Decision Dock footer summary and primary action.
- Collapse Context Tray to counts.
- Stack expanded context groups.
- Wrap Recovery Surface copy and action without horizontal overflow.
- Keep reference thumbnails and text within available width.

At both widths:

- no horizontal panel scrollbar;
- long node, asset, Skill, and option names truncate or wrap predictably;
- Composer remains reachable;
- Timeline retains nonzero usable height.

## Accessibility

- Shell regions use clear accessible names.
- Decision Dock uses `aria-busy`, radio semantics, field error associations, and controlled disclosures.
- Context Tray and each group use buttons with `aria-expanded` and `aria-controls`.
- Asset and node removal controls include the visible display name in their accessible name.
- Recovery Surface uses `role="alert"` only for newly introduced blocking failures.
- Focus moves to a local error summary after failed submission.
- Retry, Refresh, Review, removal, option, disclosure, and Send controls are keyboard reachable.
- Selected state, pending state, and severity never rely on color alone.
- Reduced motion removes new transitions without hiding content or state.

## Motion

- Use opacity and no more than 4px translation for message entry, selection detail, and disclosure expansion.
- Do not animate panel dimensions, Timeline scroll position, or Composer position.
- Do not animate every context chip independently.
- Disable new motion under `prefers-reduced-motion: reduce`.

## Delivery Sequence

### Subproject 1: Shell foundation

- establish region order and scroll ownership;
- add pure presentation models;
- preserve existing Stage Thread and Composer behavior.

### Subproject 2: Decision Dock

- apply the approved Decision Dock design;
- route Guided Interaction issues locally;
- verify concept, questionnaire, and media review submissions.

### Subproject 3: Recovery and Context Tray

- map error ownership and human-readable recovery;
- introduce Context Tray from existing Skill, asset, node, and upload state;
- preserve drafts and context across failure.

### Subproject 4: Message presentation and integration

- refine natural message grouping and markdown typography;
- complete responsive and reduced-motion rules;
- run integrated current-workflow regressions.

The sequence is mandatory because later subprojects consume the layout and presentation boundaries established earlier. It remains one release phase with one final integrated acceptance gate.

## Testing Strategy

### Pure model tests

- issue ownership and recovery action mapping;
- Decision Dock issue mapping;
- Context Tray deduplication, visibility, and lifecycle;
- natural-message run grouping without semantic text parsing.

### Component tests

- Decision Dock concept, questionnaire, media, pending, and error states;
- Recovery Surface title, technical details, valid action, and focus behavior;
- Context Tray collapsed, expanded, removal, focus-node, upload, and Skill states;
- Natural Message user and Agent runs, markdown, long content, and Show more.

### Hook and integration tests

- Guided Interaction failures stay local;
- Composer failures preserve draft and context;
- Timeline failures own Timeline recovery;
- workflow failures own panel recovery;
- the same error is not rendered twice;
- accepted sends clear message-scoped context but retain Skill;
- Stage Threads and current interaction placement remain unchanged.

### Visual and accessibility verification

- 390px and 330px rail widths;
- keyboard-only flow from Context Tray through Composer and Decision Dock;
- focus after error;
- Timeline scroll retention while regions expand or disappear;
- reduced motion;
- monochrome token audit.

### Quality gates

- focused tests;
- full frontend tests;
- typecheck;
- lint;
- production build;
- existing Agent Canvas backend contract check.

## Acceptance Criteria

1. Conversation Shell renders Header, Timeline, optional Decision Dock, optional Recovery Surface, optional Context Tray, and Composer in the defined order.
2. Timeline remains the primary scroll owner.
3. Stage Threads and document references keep existing behavior.
4. Concept, questionnaire, and media review use one Decision Dock frame and unchanged request payloads.
5. Decision Dock exposes one primary submit action and preserves form state after failure.
6. Every error has one presentation owner.
7. Raw HTTP, schema, and backend code text is hidden behind Technical details.
8. Recovery actions appear only when supported by existing state or actions.
9. Context Tray shows active Skill, message-scoped assets, node mentions, and upload state without internal metadata.
10. Failed message submission preserves draft, assets, and node mentions.
11. Accepted message submission clears message-scoped assets and nodes but retains workflow Skill.
12. User messages remain compact raised bubbles; Agent messages remain plain timeline content.
13. Natural message markdown is readable without semantic keyword parsing.
14. Locale, internal IDs, revisions, digests, bindings, and semantic roles are not visible in normal panel presentation.
15. The 390px and 330px rail layouts do not overflow and retain usable Timeline height.
16. Keyboard, focus, accessible state, and reduced motion requirements pass.
17. No backend schema, route, action, or payload changes are introduced.
18. Focused tests, full tests, typecheck, lint, build, and contract check pass.
