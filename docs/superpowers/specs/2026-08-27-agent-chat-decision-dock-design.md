# Agent Chat Decision Dock Design

## Summary

Redesign the current Guided Interaction area in Agent Canvas as one unified Decision Dock. The Dock remains fixed directly above the composer and shows the active choice without an extra opening step. Concept choices, questionnaires, and media reviews share the same visual frame, submission states, inline errors, references disclosure, secondary action menu, and responsive behavior.

This is the second Agent chat optimization round. Stage Thread history, compact Guidance progress, the composer, Skill selection, asset mentions, and backend workflow authority remain unchanged.

## Context

The Stage Thread implementation has already reduced historical execution noise. The current interaction area is now the strongest remaining visual and behavioral inconsistency:

- concept choices, questionnaires, and media reviews use different content and action arrangements;
- technical metadata such as response locale and option count receives visible space;
- proposal options, references, custom direction, and secondary actions compete at the same hierarchy;
- every action can display the same submitting label even when only one action was chosen;
- concept and media errors are not consistently displayed inside the active interaction;
- the current interaction can occupy a large nested card stack above the composer;
- selected content is not visually prioritized over unselected content.

## Goals

1. Give every active Guided Interaction one consistent monochrome frame.
2. Show active options directly without requiring another click.
3. Make the selected option the visual focus while keeping alternatives readable.
4. Keep references and secondary actions available without letting them dominate.
5. Provide one unambiguous primary submission action.
6. Preserve user input and selection while submitting and after recoverable failures.
7. Route interaction-specific errors back into the Decision Dock.
8. Keep backend interaction state authoritative.
9. Preserve keyboard access, narrow-rail usability, and reduced-motion support.

## Non-goals

- Changing backend Guided Interaction schemas, routes, actions, or revisions.
- Changing Stage Thread grouping or historical presentation.
- Redesigning the composer, Skill selector, asset mentions, or document browser.
- Changing Canvas nodes, execution behavior, or workflow progression.
- Replacing the application-wide error system.
- Adding a modal, side sheet, animation library, design-system dependency, or analytics event.
- Adding frontend-only success records before backend confirmation.

## Design Direction

The Decision Dock uses the approved Agent chat palette without new accent colors:

- canvas: `#0a0a0a`;
- panel: `#151515`;
- raised surface: `#202020`;
- border: `#353535`;
- strong border: `#4a4a4a`;
- primary text: `#f5f5f5`;
- secondary text: `#a3a3a3`;
- muted text: `#707070`.

Hierarchy comes from spacing, text weight, borders, expansion, and selection state. Do not add gradients, glow, color badges, decorative status dots, or nested outer cards.

## Component Architecture

Keep `GuidedInteractionCard` as the public data entry and interaction-kind dispatcher. Its children use one shared frame:

```text
GuidedInteractionCard
└── DecisionDockFrame
    ├── DecisionDockHeader
    ├── InteractionContent
    │   ├── ConceptChoiceContent
    │   ├── QuestionnaireContent
    │   └── MediaReviewContent
    ├── DecisionDockReferences
    ├── DecisionDockMoreMenu
    ├── DecisionDockError
    └── DecisionDockSubmitBar
```

### GuidedInteractionCard

Responsibilities:

- reject interactions whose status is not `open`;
- select the content component from `interaction.content.content_kind`;
- pass the interaction, pending state, issue, references, media URLs, and submit function into the shared frame;
- avoid owning type-specific form values.

### DecisionDockFrame

Responsibilities:

- render the title and user-facing context;
- own the middle scrolling region and fixed submission bar layout;
- expose References and More disclosures in a consistent position;
- apply pending lock and accessible busy state;
- render interaction-level issues;
- omit response locale, option count, proposal ID, interaction ID, and revision metadata.

### Interaction content components

Each content component owns only its form state and produces a submission intent for the shared footer. It does not create another outer card or its own global action layout.

### Existing component reuse

- Reuse `ProposalOptionRow` for concept option semantics after updating its compact and expanded presentation.
- Reuse `GuidedInteractionReferences` inside the References disclosure.
- Refactor `ConceptChoiceSubmitControls` into secondary action content or replace it with a Decision Dock specific control that keeps the same request construction rules.
- Keep the existing `onSubmit(request): Promise<boolean>` contract.

## Layout

The Decision Dock remains directly above the composer and is always open while an authoritative Guided Interaction is active.

```text
┌──────────────────────────────┐
│ Choose a creative direction  │
│ User-facing context          │
│                              │
│ A  First option              │
│    Two-line summary          │
│                              │
│ B  Selected option        ✓  │
│    Full selected summary     │
│                              │
│ C  Third option              │
│    Two-line summary          │
│                              │
│ References · 3           ›   │
│ More                     ›   │
│                              │
│ Selected: Selected option    │
│              Submit selection│
└──────────────────────────────┘
```

Layout rules:

- one Dock surface, no card inside card framing;
- header and submit bar remain visible;
- only the middle content region scrolls;
- maximum Dock height is approximately half of the available Agent panel height;
- natural timeline remains visible above the Dock;
- the composer remains outside and below the Dock;
- opening References or More expands within the middle scrolling region;
- closing the current interaction removes the whole Dock without leaving an empty spacer.

## Typography and Density

- Dock title: 13px to 14px, medium or semibold, primary text.
- User-facing context: 12px to 13px, secondary text.
- Option title: 13px, medium, primary text.
- Option summary: 12px, 1.45 to 1.5 line height, secondary text.
- Metadata and counts that are useful to the user: 10px to 11px, muted text.
- Remove visible locale, internal IDs, backend revisions, and raw option count labels.
- Do not uppercase long labels or use letter spacing as decoration.

## Concept Choice

### Option presentation

- Render options in one vertical list separated by 1px dividers.
- Do not give every option an independent outer card.
- An unselected option shows its marker, title, and at most two summary lines.
- A selected option uses the raised gray surface, a 1px primary border, and a check icon.
- The selected option expands to the full summary.
- A recommended option displays a small muted `Recommended` label beside its title.
- Selection must remain clear without relying on color.

### Selection behavior

- Selecting a different option updates the expanded option immediately.
- Only one option can be selected.
- The submit bar shows `Selected: <option title>` when ready.
- The primary label is `Submit selection`.
- When proposal references are still loading, selection remains possible but submission stays disabled with `Preparing references` in the footer.

### References

- Default collapsed row label: `References · <count>`.
- The expanded region reuses the current media previews and required or optional reference controls.
- Required references remain selected and cannot be silently removed.
- Optional reference choices remain part of the submitted `accepted_references` payload.
- References reset only when the authoritative reference signature changes, matching current behavior.

### More actions

Place Custom direction, Revise, Defer, Exclude, and Delegate in a `More` disclosure when allowed by the interaction.

- Custom direction or Revise opens one inline text input above the submit bar.
- Activating Custom direction changes the primary label to `Submit direction`.
- Defer, Exclude, and Delegate require an inline confirmation step before submission.
- Opening a secondary action clears any incompatible action mode but does not discard the selected option.
- Returning to the main choice restores `Submit selection` with the previous selection intact.

## Questionnaire

- Render questions as divider-separated sections rather than nested cards.
- Keep the first incomplete required question expanded.
- Completed questions may compress to their prompt and selected answer.
- Radio options use the same monochrome selected treatment as concept options.
- Custom values remain directly below their question.
- Field-level validation appears under the relevant input.
- The submit bar shows `<answered> of <total> answered`.
- Disable submission until all required answers are valid.
- The primary label is `Submit answers`.
- Optional Skip remains attached to its question rather than becoming a global primary action.

## Media Review

- Show the media review title and summary at the top of the content region.
- Use Accept as the default primary action when allowed.
- Present Retry and Replace as secondary actions near the footer.
- Selecting Replace opens the replacement instruction input and changes the primary label to `Submit replacement`.
- Exclude lives in More and requires inline confirmation.
- Only the selected action displays its submitting state.
- Do not make every action button display `Submitting` simultaneously.

## Submission State Model

The visual state is derived from backend interaction status, local form validity, `pending`, references readiness, and the current issue:

```text
Waiting
  ↓ valid user input
Ready
  ↓ submit
Submitting
  ├─ backend confirms and refreshes → Dock disappears → history updates
  └─ request fails → Error → input is preserved → user may retry
```

### Waiting

- Required input is incomplete or references required for the payload are not ready.
- Primary action is disabled.
- The footer explains the missing condition without showing an error.

### Ready

- Required input is valid.
- The footer names the selected option or active action.
- One primary submit button is enabled.

### Submitting

- Set `aria-busy="true"` on the Dock.
- Lock options, inputs, References, More, and secondary actions.
- Preserve every local value.
- Show `Submitting` only in the active primary button.
- Do not optimistically close the Dock.

### Success

- Success is authoritative only when refreshed guidance no longer exposes the open interaction or replaces it with a newer interaction.
- The existing history and Stage Thread projection render the confirmed result.
- No frontend-only success receipt is created.

### Error

- Restore interactivity after `pending` ends.
- Preserve selected option, questionnaire answers, custom text, replacement instruction, and accepted references.
- Place the issue immediately above the submit bar.
- Keep Retry as the same primary submission action when the request can be resubmitted safely.

## Frontend Issue Model

Introduce a presentation-only issue shape:

```ts
type DecisionDockIssue = {
  summary: string;
  detail: string | null;
  fieldId: string | null;
  retryable: boolean;
};
```

This shape does not change API types.

Error routing rules:

- known field validation errors set `fieldId` and render below that field;
- Guided Interaction request failures render as a Dock issue instead of a global chat error;
- stale or revision conflict errors refresh authoritative guidance and keep local draft state when the same interaction remains current;
- network and server failures use concise user-facing summaries;
- backend code or raw message may appear in a closed `Technical details` disclosure;
- raw `Request failed with status 422`, `Request failed with status 500`, or schema paths must not be the primary visible error message;
- unrelated conversation loading, message submission, and workflow errors continue to use the global chat error surface.

## Data Flow

1. `AgentCanvasChatPanel` selects the standalone authoritative Guided Interaction exactly as it does now.
2. The panel passes interaction, pending, issue, proposal references, media URLs, and submit callback to `GuidedInteractionCard`.
3. `GuidedInteractionCard` chooses the type-specific content component.
4. The content component owns form values and derives one submission intent.
5. `DecisionDockSubmitBar` renders readiness, selected summary, and one primary action.
6. Submission calls the existing `submitGuidedInteraction` action with the existing request union.
7. `useAgentCanvasChat` keeps `actingInteractionId` authoritative for pending and routes interaction failures into the presentation issue.
8. Timeline, workflow, and runtime refresh continue to determine when the Dock disappears.

## Timeline Coordination

- The Dock remains outside the scrolling timeline.
- When a confirmed submission removes the Dock and appends new history, follow the latest timeline only when the user was already following the latest content.
- Do not force-scroll a user who is reviewing older Stage Threads.
- Current `useChatTimelineScroll` ownership remains unchanged unless a focused regression proves a missing transition signal.

## Responsive Behavior

- At the normal Agent rail width, option marker, text, and selection icon share one row structure.
- At 390px and narrower, summary text keeps the available width and action rows stack vertically.
- The primary button becomes full width when horizontal space cannot preserve a useful selected summary.
- References previews wrap without creating horizontal scrolling.
- Header and footer remain visible while the Dock body scrolls.
- Avoid viewport-fixed overlays and mobile modal behavior.

## Accessibility

- The Dock is an `article` labeled by its visible title.
- Set `aria-busy` during submission.
- Option selection uses native radio semantics or an equivalent fully keyboard-operable radiogroup.
- Selected state is exposed through `checked` or `aria-checked`, not visual styling alone.
- References and More use native buttons with `aria-expanded` and `aria-controls`.
- Confirmation steps announce their purpose and provide Cancel.
- Field errors use `aria-invalid` and `aria-describedby`.
- Interaction-level issues use `role="alert"` only when newly introduced.
- Focus remains on the submitting action during pending and moves to the issue summary after failure.
- Reduced motion removes expansion and selection transitions without removing information.

## Motion

- Selected summary expansion uses opacity and no more than 4px vertical movement.
- References and More use a short opacity and height transition only when the measured layout remains stable.
- Do not animate the entire panel, composer, or timeline.
- `prefers-reduced-motion: reduce` disables all new transitions.

## Testing Strategy

### Pure presentation tests

- issue mapping distinguishes field, stale, network, server, and unknown errors;
- readiness derives correctly from required input and references state;
- only one submission intent is active at a time;
- request payloads remain identical to current backend contracts.

### Component tests

- Concept: direct option visibility, two-line unselected summary, full selected summary, References disclosure, More modes, confirmation, pending lock, and preserved retry state.
- Questionnaire: incomplete question focus, answer progress, field errors, custom value retention, and valid submission.
- Media review: Accept primary, Retry and Replace secondary, replacement input, selected pending label, and Exclude confirmation.
- Shared frame: metadata omission, one primary action, inline issue, aria-busy, disclosure semantics, and keyboard operation.

### Hook tests

- Guided Interaction errors route to the Dock instead of the global error.
- Unrelated errors remain global.
- stale refresh keeps the draft when the same interaction stays active.
- successful submit continues to refresh timeline, workflow, and runtime authority.

### Panel and CSS tests

- current interaction remains outside history and above the composer;
- no locale or raw internal metadata is visible;
- 390px layout does not overflow;
- palette tokens stay unchanged;
- reduced motion covers every new transition.

### Final verification

- focused Vitest suites;
- full frontend tests;
- TypeScript typecheck;
- ESLint;
- production build;
- manual concept, questionnaire, and media review walkthrough at normal and narrow rail widths.

## Acceptance Criteria

1. Concept choices, questionnaires, and media reviews share one Decision Dock frame.
2. The active interaction opens directly above the composer without an extra click.
3. Response locale, raw option count, internal IDs, and revisions are not visible.
4. Unselected concept options show at most two summary lines; the selected option shows its full summary.
5. The selected option has a clear monochrome checked state.
6. References and More are collapsed by default and keyboard accessible.
7. The Dock exposes exactly one primary submission action.
8. Submitting locks the Dock and preserves every form value.
9. Only the chosen action displays `Submitting`.
10. Backend confirmation, not local optimism, removes the Dock.
11. Recoverable failures retain user input and render inside the Dock.
12. Raw HTTP and schema error strings are hidden behind concise user-facing copy and optional technical details.
13. Current backend request payloads and authority rules remain unchanged.
14. Stage Threads, composer tools, Skill selection, and asset mentions retain existing behavior.
15. The Dock works at 390px width, with keyboard navigation, and with reduced motion.
16. Focused tests, full tests, typecheck, lint, and build pass.
