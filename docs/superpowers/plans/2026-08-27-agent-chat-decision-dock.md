# Agent Chat Decision Dock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three inconsistent Guided Interaction layouts with one directly expanded, monochrome Decision Dock that preserves user input, exposes one primary submit action, and keeps interaction errors local.

**Architecture:** Keep `GuidedInteractionCard` as the public dispatcher and move shared frame, disclosure, footer, issue, and pending behavior into focused Decision Dock modules. Concept choice, questionnaire, and media review components continue to emit the existing `GuidedInteractionSubmitRequestV1` union, while `useAgentCanvasChat` remains the backend-authority owner and routes only Guided Interaction failures into a presentation-only issue model.

**Tech Stack:** React 19, TypeScript 5.8, Vitest 4, Testing Library, plain CSS, existing Agent Canvas V2 API client and types.

**Spec:** `docs/superpowers/specs/2026-08-27-agent-chat-decision-dock-design.md`

## Global Constraints

- At execution time, invoke `superpowers:using-git-worktrees` and create `/data/longwei.wu/AdCraft-worktrees/agent-chat-decision-dock` on branch `feat/agent-chat-decision-dock` from commit `d6da806` or its direct descendant.
- Do not change backend routes, schemas, Guided Interaction revisions, submission payloads, Stage Thread projection, Canvas behavior, composer tools, Skill selection, asset mentions, or document browsing.
- Do not add dependencies, analytics, modal behavior, side sheets, gradients, glow, accent colors, or decorative status dots.
- Preserve the existing Agent chat palette: `#0a0a0a`, `#151515`, `#202020`, `#292929`, `#353535`, `#4a4a4a`, `#f5f5f5`, `#a3a3a3`, and `#707070`.
- Keep the current active interaction outside timeline scrolling and directly above the composer.
- Keep `onSubmit(request): Promise<boolean>` and every `GuidedInteractionSubmitRequestV1` payload field unchanged.
- Do not expose `revise` in the Decision Dock. The current concept submission union cannot represent it; Proposal revision remains on the existing Proposal action path.
- Use backend interaction disappearance or replacement as success authority. Do not create a local success receipt.
- Preserve the current selection, answer, custom text, replacement instruction, and accepted references while pending and after recoverable failure.
- Raw HTTP status text, schema paths, error codes, locale, internal IDs, and revision metadata must not be primary visible copy.
- Every task follows RED, GREEN, refactor, focused verification, and a scoped commit.

---

## File Structure

### New production files

- `apps/web/src/features/agent-canvas/chat/decisionDockIssue.ts`
  - Presentation-only issue type, API error mapping, stale-error classification.
- `apps/web/src/features/agent-canvas/chat/DecisionDockFrame.tsx`
  - Shared title, context, body, issue, disclosure, fixed footer, and pending semantics.
- `apps/web/src/features/agent-canvas/chat/ConceptChoiceDecisionDock.tsx`
  - Concept option state, reference acceptance, More actions, confirmation, and canonical request creation.
- `apps/web/src/features/agent-canvas/chat/QuestionnaireDecisionDock.tsx`
  - Questionnaire answer state, field errors, completion count, and canonical answer request creation.
- `apps/web/src/features/agent-canvas/chat/MediaReviewDecisionDock.tsx`
  - Accept, Retry, Replace, Exclude selection and canonical media review request creation.

### New test files

- `apps/web/src/features/agent-canvas/chat/decisionDockIssue.test.ts`
- `apps/web/src/features/agent-canvas/chat/DecisionDockFrame.test.tsx`
- `apps/web/src/features/agent-canvas/chat/ConceptChoiceDecisionDock.test.tsx`
- `apps/web/src/features/agent-canvas/chat/QuestionnaireDecisionDock.test.tsx`
- `apps/web/src/features/agent-canvas/chat/MediaReviewDecisionDock.test.tsx`

### Modified production files

- `apps/web/src/features/agent-canvas/chat/GuidedInteractionCard.tsx`
  - Becomes a small interaction-kind dispatcher.
- `apps/web/src/features/agent-canvas/chat/ProposalOptionRow.tsx`
  - Adds optional radio semantics, custom marker, and selected check without changing default Proposal behavior.
- `apps/web/src/features/agent-canvas/chat/GuidedInteractionReferences.tsx`
  - Allows the surrounding References disclosure to own the visible heading.
- `apps/web/src/features/agent-canvas/chat/useAgentCanvasChat.ts`
  - Stores `DecisionDockIssue`, handles stale refresh, and keeps Guided Interaction failures out of global chat error.
- `apps/web/src/features/agent-canvas/chat/AgentCanvasChatPanel.tsx`
  - Passes the typed issue into the active Dock.
- `apps/web/src/features/agent-canvas/chat/agent-canvas-chat.css`
  - Replaces duplicate Guided Interaction card rules with Decision Dock hierarchy and responsive behavior.

### Modified test files

- `apps/web/src/features/agent-canvas/chat/GuidedInteractionCard.test.tsx`
- `apps/web/src/features/agent-canvas/chat/ProposalOptionRow.test.tsx`
- `apps/web/src/features/agent-canvas/chat/useAgentCanvasChat.test.tsx`
- `apps/web/src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx`

### Deleted production file

- `apps/web/src/features/agent-canvas/chat/ConceptChoiceSubmitControls.tsx`
  - Its state and buttons move into `ConceptChoiceDecisionDock`; no other module imports it.

---

### Task 1: Create the Decision Dock Issue Projection

**Files:**

- Create: `apps/web/src/features/agent-canvas/chat/decisionDockIssue.ts`
- Create: `apps/web/src/features/agent-canvas/chat/decisionDockIssue.test.ts`

**Interfaces:**

- Consumes: `unknown` request errors and the existing `isV2ApiError` type guard.
- Produces: `DecisionDockIssue`, `decisionDockIssueFromError(error)`, and `isDecisionDockStaleError(error)`.

- [ ] **Step 1: Write the failing issue-mapping tests**

Create the test file with a real `V2ApiError` helper:

```ts
import { describe, expect, it } from "vitest";

import { V2ApiError } from "../../../api/agentCanvasApi.ts";
import {
  decisionDockIssueFromError,
  isDecisionDockStaleError,
} from "./decisionDockIssue.ts";

function apiError(status: number, code: string | undefined, message: string) {
  return new V2ApiError({
    status,
    code,
    message,
    details: {},
    violations: [],
    suggestedActions: [],
    payload: null,
  });
}

describe("decisionDockIssueFromError", () => {
  it("maps duration validation to its field without exposing the code in summary", () => {
    const issue = decisionDockIssueFromError(apiError(
      422,
      "guided_duration_value_invalid",
      "Invalid questionnaire.answers[0].value",
    ));
    expect(issue).toEqual({
      summary: "Choose one of the supported duration values.",
      detail: "guided_duration_value_invalid: Invalid questionnaire.answers[0].value",
      fieldId: "production_duration_seconds",
      retryable: true,
    });
  });

  it("uses concise copy for generic validation and server failures", () => {
    expect(decisionDockIssueFromError(apiError(422, "guided_interaction_invalid", "Invalid field path")))
      .toMatchObject({ summary: "Review this response and try again.", retryable: true });
    expect(decisionDockIssueFromError(apiError(500, undefined, "Request failed with status 500")))
      .toMatchObject({ summary: "The agent could not submit this response. Try again.", retryable: true });
  });

  it("recognizes a network failure by its API error name", () => {
    const error = Object.assign(new Error("Failed to fetch"), { name: "V2NetworkError" });
    expect(decisionDockIssueFromError(error)).toMatchObject({
      summary: "Connection interrupted. Check your connection and try again.",
      retryable: true,
    });
  });

  it("classifies stale Guided Interaction authority", () => {
    expect(isDecisionDockStaleError(apiError(409, "guided_interaction_stale", "Stale"))).toBe(true);
    expect(isDecisionDockStaleError(apiError(409, "guidance_revision_conflict", "Conflict"))).toBe(true);
    expect(isDecisionDockStaleError(apiError(422, "guided_interaction_invalid", "Invalid"))).toBe(false);
  });
});
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run from `apps/web`:

```bash
npm test -- src/features/agent-canvas/chat/decisionDockIssue.test.ts
```

Expected: FAIL because `decisionDockIssue.ts` does not exist.

- [ ] **Step 3: Implement the issue model and exact mapping**

Create `decisionDockIssue.ts`:

```ts
import { isV2ApiError } from "../../../api/agentCanvasApi.ts";

export interface DecisionDockIssue {
  summary: string;
  detail: string | null;
  fieldId: string | null;
  retryable: boolean;
}

const STALE_CODES = new Set([
  "guided_interaction_stale",
  "guidance_revision_conflict",
  "journey_revision_conflict",
]);

function technicalDetail(error: unknown): string | null {
  if (isV2ApiError(error)) {
    return error.code ? `${error.code}: ${error.message}` : error.message;
  }
  return error instanceof Error && error.message.trim() ? error.message.trim() : null;
}

export function isDecisionDockStaleError(error: unknown): boolean {
  return isV2ApiError(error) && Boolean(error.code && STALE_CODES.has(error.code));
}

export function decisionDockIssueFromError(error: unknown): DecisionDockIssue {
  const detail = technicalDetail(error);
  if (isV2ApiError(error) && error.code === "guided_duration_value_invalid") {
    return {
      summary: "Choose one of the supported duration values.",
      detail,
      fieldId: "production_duration_seconds",
      retryable: true,
    };
  }
  if (isDecisionDockStaleError(error)) {
    return {
      summary: "The workflow changed before this response was saved. Review the latest options and try again.",
      detail,
      fieldId: null,
      retryable: true,
    };
  }
  if (error instanceof Error && error.name === "V2NetworkError") {
    return {
      summary: "Connection interrupted. Check your connection and try again.",
      detail,
      fieldId: null,
      retryable: true,
    };
  }
  if (isV2ApiError(error) && error.status === 422) {
    return {
      summary: "Review this response and try again.",
      detail,
      fieldId: null,
      retryable: true,
    };
  }
  if (isV2ApiError(error) && error.status >= 500) {
    return {
      summary: "The agent could not submit this response. Try again.",
      detail,
      fieldId: null,
      retryable: true,
    };
  }
  return {
    summary: "The guided response could not be submitted.",
    detail,
    fieldId: null,
    retryable: true,
  };
}
```

- [ ] **Step 4: Run the focused test and confirm GREEN**

```bash
npm test -- src/features/agent-canvas/chat/decisionDockIssue.test.ts
```

Expected: all issue projection tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/agent-canvas/chat/decisionDockIssue.ts apps/web/src/features/agent-canvas/chat/decisionDockIssue.test.ts
git commit -m "feat(agent-chat): model decision dock issues"
```

---

### Task 2: Build the Shared Decision Dock Frame

**Files:**

- Create: `apps/web/src/features/agent-canvas/chat/DecisionDockFrame.tsx`
- Create: `apps/web/src/features/agent-canvas/chat/DecisionDockFrame.test.tsx`

**Interfaces:**

- Consumes: `DecisionDockIssue | null`, user-facing title and context, body content, footer summary, submit label, pending state, and submit callback.
- Produces: `DecisionDockFrame`, `DecisionDockDisclosure`, and `DecisionDockFrameProps` for all three interaction components.

- [ ] **Step 1: Write failing frame and disclosure tests**

Create tests that exercise the shared contract:

```tsx
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DecisionDockDisclosure, DecisionDockFrame } from "./DecisionDockFrame.tsx";

afterEach(cleanup);

describe("DecisionDockFrame", () => {
  it("renders user-facing content and one primary action", () => {
    const submit = vi.fn();
    render(
      <DecisionDockFrame
        title="Choose a direction"
        context="Pick the visual approach."
        pending={false}
        issue={null}
        footerSummary="Selected: Warm"
        submitLabel="Submit selection"
        submitDisabled={false}
        onSubmit={submit}
      >
        <p>Choice content</p>
      </DecisionDockFrame>,
    );
    expect(screen.getByRole("article", { name: "Choose a direction" })).toBeTruthy();
    expect(screen.getByText("Choice content")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Submit selection" }));
    expect(submit).toHaveBeenCalledOnce();
  });

  it("locks its footer and announces busy state while submitting", () => {
    render(
      <DecisionDockFrame
        title="Review media"
        context="Choose the next action."
        pending
        issue={null}
        footerSummary="Accept this result"
        submitLabel="Accept"
        submitDisabled={false}
        onSubmit={vi.fn()}
      >
        <p>Media content</p>
      </DecisionDockFrame>,
    );
    expect(screen.getByRole("article").getAttribute("aria-busy")).toBe("true");
    expect((screen.getByRole("button", { name: "Submitting" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("keeps technical details closed behind human-readable error copy", () => {
    render(
      <DecisionDockFrame
        title="Choose"
        context="Pick one."
        pending={false}
        issue={{ summary: "Review this response and try again.", detail: "invalid.path: expected array", fieldId: null, retryable: true }}
        footerSummary="Selected: Warm"
        submitLabel="Submit selection"
        submitDisabled={false}
        onSubmit={vi.fn()}
      >
        <p>Body</p>
      </DecisionDockFrame>,
    );
    expect(screen.getByRole("alert").textContent).toContain("Review this response and try again.");
    const details = screen.getByText("Technical details").closest("details");
    expect(details?.open).toBe(false);
    fireEvent.click(screen.getByText("Technical details"));
    expect(details?.open).toBe(true);
    expect(screen.getByText("invalid.path: expected array")).toBeTruthy();
  });

  it("uses a controlled accessible disclosure", () => {
    const change = vi.fn();
    const { rerender } = render(
      <DecisionDockDisclosure id="references" label="References" count={3} expanded={false} disabled={false} onExpandedChange={change}>
        <p>Reference list</p>
      </DecisionDockDisclosure>,
    );
    const trigger = screen.getByRole("button", { name: "References · 3" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(trigger);
    expect(change).toHaveBeenCalledWith(true);
    rerender(
      <DecisionDockDisclosure id="references" label="References" count={3} expanded disabled={false} onExpandedChange={change}>
        <p>Reference list</p>
      </DecisionDockDisclosure>,
    );
    expect(screen.getByText("Reference list")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the focused test and confirm RED**

```bash
npm test -- src/features/agent-canvas/chat/DecisionDockFrame.test.tsx
```

Expected: FAIL because the frame module does not exist.

- [ ] **Step 3: Implement the shared frame contract**

Use this exact public prop shape:

```tsx
import { useEffect, useRef, type ReactNode } from "react";

import { ChevronDownIcon, ChevronRightIcon } from "../../../icons.tsx";
import type { DecisionDockIssue } from "./decisionDockIssue.ts";

export interface DecisionDockFrameProps {
  title: string;
  context: string;
  pending: boolean;
  issue: DecisionDockIssue | null;
  footerSummary: string;
  submitLabel: string;
  submitDisabled: boolean;
  onSubmit: () => void;
  children: ReactNode;
}

export function DecisionDockFrame(props: DecisionDockFrameProps) {
  const issueRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (props.issue && !props.issue.fieldId) issueRef.current?.focus();
  }, [props.issue]);
  return (
    <article className="agent-chat__decision-dock" aria-label={props.title} aria-busy={props.pending}>
      <header className="agent-chat__decision-dock-header">
        <strong>{props.title}</strong>
        <p>{props.context}</p>
      </header>
      <div className="agent-chat__decision-dock-body">{props.children}</div>
      {props.issue && !props.issue.fieldId ? (
        <div ref={issueRef} tabIndex={-1} className="agent-chat__decision-dock-issue" role="alert">
          <strong>{props.issue.summary}</strong>
          {props.issue.detail ? (
            <details>
              <summary>Technical details</summary>
              <code>{props.issue.detail}</code>
            </details>
          ) : null}
        </div>
      ) : null}
      <footer className="agent-chat__decision-dock-footer">
        <span>{props.footerSummary}</span>
        <button
          type="button"
          disabled={props.pending || props.submitDisabled}
          onClick={props.onSubmit}
        >
          {props.pending ? "Submitting" : props.submitLabel}
        </button>
      </footer>
    </article>
  );
}
```

In the same file, implement the controlled disclosure with the exact props used by the test. Its button label is `count === null ? label : `${label} · ${count}``, its button has `aria-expanded` and `aria-controls`, and its region has `id`, `role="region"`, and renders only when `expanded` is true.

- [ ] **Step 4: Run the focused test and confirm GREEN**

```bash
npm test -- src/features/agent-canvas/chat/DecisionDockFrame.test.tsx
```

Expected: all frame, pending, issue, and disclosure tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/agent-canvas/chat/DecisionDockFrame.tsx apps/web/src/features/agent-canvas/chat/DecisionDockFrame.test.tsx
git commit -m "feat(agent-chat): add decision dock frame"
```

---

### Task 3: Migrate Concept Choice into the Decision Dock

**Files:**

- Create: `apps/web/src/features/agent-canvas/chat/ConceptChoiceDecisionDock.tsx`
- Create: `apps/web/src/features/agent-canvas/chat/ConceptChoiceDecisionDock.test.tsx`
- Modify: `apps/web/src/features/agent-canvas/chat/ProposalOptionRow.tsx`
- Modify: `apps/web/src/features/agent-canvas/chat/ProposalOptionRow.test.tsx`
- Modify: `apps/web/src/features/agent-canvas/chat/GuidedInteractionReferences.tsx`

**Interfaces:**

- Consumes: an open concept `GuidedInteractionV1`, `DecisionDockIssue | null`, proposal references, reference media URLs, pending state, and the existing submit callback.
- Produces: `ConceptChoiceDecisionDock` and unchanged `GuidedInteractionSubmitRequestV1` concept payloads.

- [ ] **Step 1: Add failing radio semantics to ProposalOptionRow tests**

Add this test without changing the existing default-button and read-only tests:

```tsx
it("supports Decision Dock radio semantics and a letter marker", () => {
  render(
    <ProposalOptionRow
      index={1}
      marker="B"
      selectionRole="radio"
      optionId="option-b"
      title="Precise"
      summary="Clean product precision."
      selected
      onSelect={vi.fn()}
    />,
  );
  const option = screen.getByRole("radio", { name: /Precise/i });
  expect(option.getAttribute("aria-checked")).toBe("true");
  expect(option.getAttribute("aria-pressed")).toBeNull();
  expect(screen.getByText("B")).toBeTruthy();
  expect(screen.getByText("✓")).toBeTruthy();
});
```

- [ ] **Step 2: Run the ProposalOptionRow test and confirm RED**

```bash
npm test -- src/features/agent-canvas/chat/ProposalOptionRow.test.tsx
```

Expected: FAIL because `marker` and `selectionRole` do not exist.

- [ ] **Step 3: Extend ProposalOptionRow without changing its defaults**

Add optional props:

```ts
marker?: string;
selectionRole?: "button" | "radio";
```

Default `selectionRole` to `"button"`. Render `marker ?? String(index + 1).padStart(2, "0")`. On the interactive button set:

```tsx
role={selectionRole === "radio" ? "radio" : undefined}
aria-checked={selectionRole === "radio" ? selected : undefined}
aria-pressed={selectionRole === "button" ? selected : undefined}
```

Append this meaningful selected indicator only when `selectionRole === "radio"`, so existing Proposal and historical rows do not gain new chrome:

```tsx
{selectionRole === "radio" ? (
  <span className="agent-chat__proposal-option-check" aria-hidden="true">
    {selected ? "✓" : null}
  </span>
) : null}
```

- [ ] **Step 4: Run ProposalOptionRow tests and confirm GREEN**

```bash
npm test -- src/features/agent-canvas/chat/ProposalOptionRow.test.tsx src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx
```

Expected: the new radio test and existing Proposal card tests pass.

- [ ] **Step 5: Write failing Concept Choice Decision Dock tests**

Use the existing three-option concept fixture and proposal references from `GuidedInteractionCard.test.tsx`. Cover these exact behaviors:

```tsx
it("shows options directly, expands selection, and submits the existing payload", () => {
  const submit = vi.fn().mockResolvedValue(true);
  render(<ConceptChoiceDecisionDock interaction={interaction} pending={false} issue={null} proposalReferences={[]} referenceMediaUrls={{}} onSubmit={submit} />);
  expect(screen.getAllByRole("radio")).toHaveLength(3);
  expect(screen.queryByText("zh-CN")).toBeNull();
  expect(screen.queryByText("3 options")).toBeNull();
  fireEvent.click(screen.getByRole("radio", { name: /Warm/i }));
  expect(screen.getByText("Selected: Warm")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Submit selection" }));
  expect(submit).toHaveBeenCalledWith({
    submission_kind: "concept_choice",
    expected_interaction_revision: 2,
    expected_session_revision: 4,
    action: "select",
    option_id: "option-a",
    custom_text: null,
  });
});
```

Add separate tests for:

- References starts with `aria-expanded="false"`, hides reference names, then reveals them and submits accepted references unchanged.
- A selected option remains selected when More opens and Custom direction becomes active.
- Custom direction changes the primary label to `Submit direction` and sends `action: "custom"` with trimmed `custom_text`.
- Exclude requires selecting `Exclude this stage`, then shows Cancel plus primary `Confirm exclusion`; only the primary button submits `action: "exclude"`.
- Delegate and Defer use the same two-step confirmation rule.
- An allowed `revise` action is not rendered because the request union cannot submit it.
- References `null` allows option selection but disables submission and shows `Preparing references`.
- Pending disables every option, disclosure, alternative action, input, and primary action while retaining selected copy.
- A non-field issue appears in the frame and does not clear selection.

- [ ] **Step 6: Run the Concept test and confirm RED**

```bash
npm test -- src/features/agent-canvas/chat/ConceptChoiceDecisionDock.test.tsx
```

Expected: FAIL because `ConceptChoiceDecisionDock.tsx` does not exist.

- [ ] **Step 7: Implement ConceptChoiceDecisionDock**

Use this exact prop contract:

```ts
export interface ConceptChoiceDecisionDockProps {
  interaction: GuidedInteractionV1;
  pending: boolean;
  issue: DecisionDockIssue | null;
  proposalReferences: ProposedDraftReferenceV2[] | null;
  referenceMediaUrls: Record<string, string>;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
}
```

Guard `interaction.content.content_kind !== "concept_choice"` by returning `null`. Maintain:

```ts
type ConceptMode = "select" | "custom" | "defer" | "exclude" | "delegate";

const [optionId, setOptionId] = useState<string | null>(null);
const [mode, setMode] = useState<ConceptMode>("select");
const [customText, setCustomText] = useState("");
const [referencesOpen, setReferencesOpen] = useState(false);
const [moreOpen, setMoreOpen] = useState(false);
const [excludedOptionalReferenceKeys, setExcludedOptionalReferenceKeys] = useState<Set<string>>(() => new Set());
```

Reuse the current reference-signature reset and accepted-reference ordering logic verbatim. Render options inside `role="radiogroup"` with `selectionRole="radio"` and markers `A`, `B`, `C`, then `String(index + 1)` after `Z`.

Derive footer state with explicit branches:

```ts
const selectedOption = content.options.find((option) => option.option_id === optionId) ?? null;
const customReady = Boolean(customText.trim());
const selectionReady = Boolean(selectedOption) && proposalReferences !== null;
const confirmationMode = mode === "defer" || mode === "exclude" || mode === "delegate";
const submitDisabled = mode === "select"
  ? !selectionReady
  : mode === "custom"
    ? !customReady
    : !confirmationMode;
```

The primary request builder must remain:

```ts
const request: GuidedInteractionSubmitRequestV1 = {
  submission_kind: "concept_choice",
  expected_interaction_revision: interaction.revision,
  expected_session_revision: interaction.expected_session_revision,
  action: mode,
  option_id: mode === "select" ? optionId : null,
  custom_text: mode === "custom" ? customText.trim() : null,
  ...(mode === "select" && content.proposal_id
    ? { accepted_references: acceptedReferences }
    : {}),
};
```

Use `DecisionDockDisclosure` for References and More. Pass `showHeader={false}` to `GuidedInteractionReferences`; add that optional prop with default `true` and omit only its visible header when false. Do not remove its `aria-label="Proposal references"` section.

- [ ] **Step 8: Run focused Concept tests and confirm GREEN**

```bash
npm test -- src/features/agent-canvas/chat/ConceptChoiceDecisionDock.test.tsx src/features/agent-canvas/chat/ProposalOptionRow.test.tsx src/features/agent-canvas/chat/guidedInteractionReferences.test.ts
```

Expected: option, payload, disclosure, confirmation, pending, and compatibility tests pass.

- [ ] **Step 9: Commit**

```bash
git add apps/web/src/features/agent-canvas/chat/ConceptChoiceDecisionDock.tsx apps/web/src/features/agent-canvas/chat/ConceptChoiceDecisionDock.test.tsx apps/web/src/features/agent-canvas/chat/ProposalOptionRow.tsx apps/web/src/features/agent-canvas/chat/ProposalOptionRow.test.tsx apps/web/src/features/agent-canvas/chat/GuidedInteractionReferences.tsx
git commit -m "feat(agent-chat): redesign concept decisions"
```

---

### Task 4: Migrate Questionnaires into the Decision Dock

**Files:**

- Create: `apps/web/src/features/agent-canvas/chat/QuestionnaireDecisionDock.tsx`
- Create: `apps/web/src/features/agent-canvas/chat/QuestionnaireDecisionDock.test.tsx`

**Interfaces:**

- Consumes: an open questionnaire `GuidedInteractionV1`, `DecisionDockIssue | null`, pending state, and the existing submit callback.
- Produces: `QuestionnaireDecisionDock` and unchanged questionnaire answer payloads.

- [ ] **Step 1: Write failing questionnaire tests**

Create a two-question fixture: required production duration plus an optional tone question that allows Skip. Test:

```tsx
it("tracks answered progress and submits the canonical answer union", () => {
  const submit = vi.fn().mockResolvedValue(true);
  render(<QuestionnaireDecisionDock interaction={interaction} pending={false} issue={null} onSubmit={submit} />);
  expect(screen.getByText("0 of 2 answered")).toBeTruthy();
  fireEvent.click(screen.getByRole("radio", { name: /30 seconds/i }));
  fireEvent.click(screen.getByRole("button", { name: /Skip .*tone/i }));
  expect(screen.getByText("2 of 2 answered")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Submit answers" }));
  expect(submit).toHaveBeenCalledWith({
    submission_kind: "questionnaire",
    expected_interaction_revision: interaction.revision,
    expected_session_revision: interaction.expected_session_revision,
    answers: [
      { answer_kind: "option", question_id: "production_duration_seconds", option_id: "duration_seconds_30" },
      { answer_kind: "skip", question_id: "tone" },
    ],
  });
});
```

Add separate tests for:

- recommended options are not preselected;
- duration custom input remains `type="number"` and trims the submitted value;
- a `DecisionDockIssue` whose `fieldId` is `production_duration_seconds` renders below that input with `aria-invalid="true"` and does not render a second frame alert;
- a general issue renders in the shared frame;
- pending rerender retains all answers and disables fieldsets plus primary action;
- Skip is visible only when both `question.allow_skip` and `interaction.allowed_actions.includes("skip")` are true;
- primary submission remains disabled until every required answer is valid.

- [ ] **Step 2: Run the focused test and confirm RED**

```bash
npm test -- src/features/agent-canvas/chat/QuestionnaireDecisionDock.test.tsx
```

Expected: FAIL because the questionnaire module does not exist.

- [ ] **Step 3: Implement QuestionnaireDecisionDock**

Use this local answer type and exact props:

```ts
type QuestionnaireAnswer = {
  kind: "option" | "custom" | "skip";
  value?: string;
};

export interface QuestionnaireDecisionDockProps {
  interaction: GuidedInteractionV1;
  pending: boolean;
  issue: DecisionDockIssue | null;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
}
```

Guard the content kind. Keep `answers` keyed by `question_id`. Derive:

```ts
const answeredCount = questions.filter((question) => Boolean(answers[question.question_id])).length;
const complete = questions.every((question) => {
  if (!question.required) return true;
  const answer = answers[question.question_id];
  return Boolean(answer) && (answer?.kind !== "custom" || Boolean(answer.value?.trim()));
});
```

Render divider-separated `fieldset` sections inside `DecisionDockFrame`. Use native radio inputs. For a custom input, set `aria-invalid={issue?.fieldId === question.question_id}` and connect its error with `aria-describedby`. Give Skip the accessible name `Skip ${question.prompt}` except duration, where Skip remains absent under the backend contract.

Build `answersPayload` with the same three union members already used in `GuidedInteractionCard.tsx`. Footer summary is `${answeredCount} of ${questions.length} answered`; primary label is `Submit answers`.

- [ ] **Step 4: Run the focused test and confirm GREEN**

```bash
npm test -- src/features/agent-canvas/chat/QuestionnaireDecisionDock.test.tsx
```

Expected: all answer, validation, pending, progress, and payload tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/agent-canvas/chat/QuestionnaireDecisionDock.tsx apps/web/src/features/agent-canvas/chat/QuestionnaireDecisionDock.test.tsx
git commit -m "feat(agent-chat): redesign guided questionnaires"
```

---

### Task 5: Migrate Media Review into the Decision Dock

**Files:**

- Create: `apps/web/src/features/agent-canvas/chat/MediaReviewDecisionDock.tsx`
- Create: `apps/web/src/features/agent-canvas/chat/MediaReviewDecisionDock.test.tsx`

**Interfaces:**

- Consumes: an open media-review `GuidedInteractionV1`, `DecisionDockIssue | null`, pending state, and the existing submit callback.
- Produces: `MediaReviewDecisionDock` and unchanged media review payloads.

- [ ] **Step 1: Write failing media-review tests**

Use a fixture with `allowed_actions: ["accept", "retry", "replace", "exclude"]`. Cover:

```tsx
it("defaults to Accept and submits the existing media review payload", () => {
  const submit = vi.fn().mockResolvedValue(true);
  render(<MediaReviewDecisionDock interaction={interaction} pending={false} issue={null} onSubmit={submit} />);
  expect(screen.getByText("The generated video is ready for review.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Accept" }));
  expect(submit).toHaveBeenCalledWith({
    submission_kind: "media_review",
    expected_interaction_revision: interaction.revision,
    expected_session_revision: interaction.expected_session_revision,
    action: "accept",
    instruction: null,
  });
});
```

Add tests proving:

- Retry is a secondary mode selector and becomes the one primary footer action after selection.
- Replace opens `Describe the replacement`, keeps primary disabled while blank, trims instruction, and submits `action: "replace"`.
- Exclude lives inside More and requires `Confirm exclusion` before submission.
- pending retains the selected mode and replacement instruction; exactly one element contains `Submitting` while Retry, Replace, and More remain non-submitting labels.
- actions absent from `allowed_actions` are not shown.
- a general issue appears inside the shared frame and input remains intact.

- [ ] **Step 2: Run the focused test and confirm RED**

```bash
npm test -- src/features/agent-canvas/chat/MediaReviewDecisionDock.test.tsx
```

Expected: FAIL because the media-review module does not exist.

- [ ] **Step 3: Implement MediaReviewDecisionDock**

Use this mode and prop contract:

```ts
type MediaReviewMode = "accept" | "retry" | "replace" | "exclude";

export interface MediaReviewDecisionDockProps {
  interaction: GuidedInteractionV1;
  pending: boolean;
  issue: DecisionDockIssue | null;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
}
```

Choose the initial mode from the first allowed action in this preference order: Accept, Retry, Replace, Exclude. Retry and Replace buttons only change local mode. Exclude is selected from a controlled More disclosure and renders a confirmation row with Cancel. Replace renders the instruction input.

The one primary handler emits:

```ts
const request: GuidedInteractionSubmitRequestV1 = {
  submission_kind: "media_review",
  expected_interaction_revision: interaction.revision,
  expected_session_revision: interaction.expected_session_revision,
  action: mode,
  instruction: mode === "replace" ? instruction.trim() : null,
};
```

Footer labels are `Accept`, `Retry`, `Submit replacement`, and `Confirm exclusion`. Disable only from invalid form state or `pending`; `DecisionDockFrame` owns the visible Submitting label.

- [ ] **Step 4: Run the focused test and confirm GREEN**

```bash
npm test -- src/features/agent-canvas/chat/MediaReviewDecisionDock.test.tsx
```

Expected: all action selection, confirmation, pending, issue, and payload tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/agent-canvas/chat/MediaReviewDecisionDock.tsx apps/web/src/features/agent-canvas/chat/MediaReviewDecisionDock.test.tsx
git commit -m "feat(agent-chat): redesign media review"
```

---

### Task 6: Integrate the Dispatcher and Route Guided Errors Locally

**Files:**

- Modify: `apps/web/src/features/agent-canvas/chat/GuidedInteractionCard.tsx`
- Modify: `apps/web/src/features/agent-canvas/chat/GuidedInteractionCard.test.tsx`
- Modify: `apps/web/src/features/agent-canvas/chat/useAgentCanvasChat.ts`
- Modify: `apps/web/src/features/agent-canvas/chat/useAgentCanvasChat.test.tsx`
- Modify: `apps/web/src/features/agent-canvas/chat/AgentCanvasChatPanel.tsx`
- Delete: `apps/web/src/features/agent-canvas/chat/ConceptChoiceSubmitControls.tsx`

**Interfaces:**

- Consumes: the three Decision Dock content components and `decisionDockIssueFromError`.
- Produces: a small `GuidedInteractionCard` dispatcher, `state.guidedInteractionIssue`, and local Guided Interaction failure behavior.

- [ ] **Step 1: Rewrite GuidedInteractionCard tests as dispatcher and contract tests**

Retain the existing fixtures but update the prop from `error` to `issue`. The integrated tests must prove:

```tsx
it("dispatches an open concept interaction without technical metadata", () => {
  render(<GuidedInteractionCard interaction={conceptInteraction} pending={false} issue={null} onSubmit={vi.fn().mockResolvedValue(true)} />);
  expect(screen.getByRole("article", { name: conceptInteraction.title })).toBeTruthy();
  expect(screen.getAllByRole("radio")).toHaveLength(3);
  expect(screen.queryByText(conceptInteraction.response_locale)).toBeNull();
});

it("does not render a closed interaction", () => {
  const { container } = render(<GuidedInteractionCard interaction={{ ...conceptInteraction, status: "closed" }} pending={false} issue={null} onSubmit={vi.fn().mockResolvedValue(true)} />);
  expect(container.firstChild).toBeNull();
});
```

Add one dispatch test each for questionnaire and media review, plus the existing proposal-reference fallback test: `proposal_id !== null` and omitted `proposalReferences` means pending references; `proposal_id === null` means an empty ready reference list.

- [ ] **Step 2: Add failing hook tests for local issue routing**

Update the existing invalid-duration assertion:

```ts
expect(result.current.state.guidedInteractionIssue).toMatchObject({
  summary: "Choose one of the supported duration values.",
  fieldId: "production_duration_seconds",
});
expect(result.current.state.error).toBeNull();
```

Add tests for:

- a `{ status: 500, code: "agent_runtime_unavailable", message: "Request failed with status 500" }` rejection produces a Decision Dock issue and no global error;
- `guided_interaction_stale` refreshes timeline and workflow authority, keeps the same interaction issue when the refreshed interaction ID is unchanged, and leaves `actingInteractionId` null;
- changing from interaction ID A to B clears an old issue;
- an unrelated command-plan or proposal failure still uses global `state.error` and leaves `guidedInteractionIssue` null;
- successful submission clears the previous issue before sending and still refreshes timeline, workflow, and runtime.

- [ ] **Step 3: Run integrated tests and confirm RED**

```bash
npm test -- src/features/agent-canvas/chat/GuidedInteractionCard.test.tsx src/features/agent-canvas/chat/useAgentCanvasChat.test.tsx
```

Expected: FAIL because the dispatcher still owns all content and the hook exposes `guidedInteractionError: string | null`.

- [ ] **Step 4: Replace GuidedInteractionCard with the small dispatcher**

Use this public contract:

```ts
export interface GuidedInteractionCardProps {
  interaction: GuidedInteractionV1;
  pending: boolean;
  issue?: DecisionDockIssue | null;
  proposalReferences?: ProposedDraftReferenceV2[] | null;
  referenceMediaUrls?: Record<string, string>;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
}
```

Return `null` unless status is open. Dispatch by `content_kind`. Preserve the current reference fallback exactly:

```ts
const references = proposalReferences === undefined
  ? interaction.content.proposal_id ? null : []
  : proposalReferences;
```

Pass `issue ?? null` to each content component. Remove all old local interaction components and imports from this file. Delete `ConceptChoiceSubmitControls.tsx` after `rg -n "ConceptChoiceSubmitControls" apps/web/src` shows only that file itself.

- [ ] **Step 5: Replace hook string error with DecisionDockIssue**

In `useAgentCanvasChat.ts`:

```ts
const [guidedInteractionIssue, setGuidedInteractionIssue] = useState<DecisionDockIssue | null>(null);
```

Import `decisionDockIssueFromError`, `isDecisionDockStaleError`, and the type. Remove Guided Interaction branches from `handleStructuredActionError`; that function continues to handle non-Dock guided actions and proposal conflicts.

Add a previous-interaction-ID effect so an issue survives same-ID stale refresh but clears when authority changes:

```ts
const currentInteractionId = guidanceSession?.interaction?.interaction_id ?? null;
const previousInteractionIdRef = useRef<string | null>(null);

useEffect(() => {
  if (previousInteractionIdRef.current === currentInteractionId) return;
  previousInteractionIdRef.current = currentInteractionId;
  setGuidedInteractionIssue(null);
}, [currentInteractionId]);
```

Remove the unconditional issue clear from successful timeline refresh. Clear it immediately before a new Guided Interaction submission. Replace the catch body with:

```ts
const issue = decisionDockIssueFromError(interactionError);
setGuidedInteractionIssue(issue);
if (isDecisionDockStaleError(interactionError)) {
  await refresh();
  await onWorkflowRefresh?.();
}
guidedInteractionSubmitSeqRef.current = null;
setActingInteractionId(null);
return false;
```

Expose `guidedInteractionIssue` from state and pass it from `AgentCanvasChatPanel` as `issue={chat.state.guidedInteractionIssue}`. Do not set global `error` in this catch.

- [ ] **Step 6: Run focused integration tests and confirm GREEN**

```bash
npm test -- src/features/agent-canvas/chat/GuidedInteractionCard.test.tsx src/features/agent-canvas/chat/useAgentCanvasChat.test.tsx src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx
```

Expected: dispatcher, local issues, stale refresh, global error separation, and current interaction placement tests pass.

- [ ] **Step 7: Run typecheck before committing the contract migration**

```bash
npm run typecheck
```

Expected: no stale `guidedInteractionError` or `error` prop references remain.

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/features/agent-canvas/chat/GuidedInteractionCard.tsx apps/web/src/features/agent-canvas/chat/GuidedInteractionCard.test.tsx apps/web/src/features/agent-canvas/chat/useAgentCanvasChat.ts apps/web/src/features/agent-canvas/chat/useAgentCanvasChat.test.tsx apps/web/src/features/agent-canvas/chat/AgentCanvasChatPanel.tsx apps/web/src/features/agent-canvas/chat/ConceptChoiceSubmitControls.tsx
git commit -m "feat(agent-chat): route guided interactions through decision dock"
```

---

### Task 7: Apply the Monochrome Decision Dock Visual System

**Files:**

- Modify: `apps/web/src/features/agent-canvas/chat/agent-canvas-chat.css`
- Modify: `apps/web/src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx`

**Interfaces:**

- Consumes: the final Decision Dock class names from Tasks 2 through 6.
- Produces: one-surface visual hierarchy, fixed header and footer, scrolling body, narrow rail behavior, focus states, and reduced motion.

- [ ] **Step 1: Add failing CSS contract assertions**

Extend the existing source-based CSS tests to assert:

```ts
expect(css).toContain(".agent-chat__decision-dock");
expect(css).toContain(".agent-chat__decision-dock-body");
expect(css).toContain(".agent-chat__decision-dock-footer");
expect(css).toContain("max-height: min(50vh, 480px)");
expect(css).toContain("overflow-y: auto");
expect(css).toMatch(/\.agent-chat__proposal-option:not\(\.is-selected\)[\s\S]*-webkit-line-clamp: 2/);
expect(css).toMatch(/\.agent-chat__proposal-option\.is-selected[\s\S]*border-color: var\(--agent-chat-primary\)/);
expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*\.agent-chat__decision-dock/);
expect(css).not.toContain(".agent-chat__guided-proposal-intro");
expect(css).not.toContain("#e6a34a");
expect(css).not.toContain("#77c9c2");
```

Also assert the palette token values remain unchanged and `.agent-chat__current-interaction` no longer owns vertical scrolling.

- [ ] **Step 2: Run the panel style tests and confirm RED**

```bash
npm test -- src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx
```

Expected: FAIL because Decision Dock selectors and layout do not exist.

- [ ] **Step 3: Replace old Guided Interaction CSS with Decision Dock CSS**

Remove both duplicate blocks that style `.agent-chat__guided-interaction`, `.agent-chat__guided-proposal-intro`, `.agent-chat__concept-submit`, `.agent-chat__guided-options`, and `.agent-chat__guided-questions`. Preserve `.agent-chat__guided-actions` rules because `GuidedActionsCard` in `AgentCanvasChatPanel.tsx` still uses that class outside the Decision Dock. Give the new concept and media controls dedicated `.agent-chat__decision-dock-secondary-actions` selectors. Keep unrelated Proposal, historical option, Decision Bundle, and Stage Thread styles.

Implement these exact layout rules:

```css
.agent-chat__current-interaction {
  min-height: 0;
  padding: 10px 12px;
  overflow: visible;
  border-top: 1px solid var(--agent-chat-border);
}

.agent-chat__decision-dock {
  display: grid;
  max-height: min(50vh, 480px);
  grid-template-rows: auto minmax(0, 1fr) auto auto;
  overflow: hidden;
  border: 1px solid var(--agent-chat-border);
  border-radius: 10px;
  background: var(--agent-chat-raised);
  color: var(--agent-chat-primary);
}

.agent-chat__decision-dock-body {
  min-height: 0;
  padding: 0 12px 10px;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.agent-chat__decision-dock-footer {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 10px 12px;
  border-top: 1px solid var(--agent-chat-border);
  background: var(--agent-chat-raised);
}
```

Add:

- 13px to 14px Dock title, 12px context, 12px option summaries, 10px to 11px footer and metadata;
- transparent unselected option rows separated by 1px borders;
- two-line clamp only for `.agent-chat__proposal-option:not(.is-selected) .agent-chat__proposal-option-copy > span`;
- selected row raised background, primary border, visible check, and unclamped summary;
- muted Recommended text with no filled badge;
- full-width disclosure triggers with chevron and visible `:focus-visible` outline;
- compact confirmation, More, reference, media action, questionnaire, and issue rows;
- `details` technical content in muted monospace without exposing it until opened;
- no outer shadow and no nested option card shadows;
- a 4px maximum opacity and translate animation for selected details and disclosures;
- full-width footer button and stacked footer content under the existing `@media (max-width: 1180px)` 330px rail rule;
- wrapping reference rows without horizontal scrolling.

Include `.agent-chat__decision-dock`, disclosure regions, option summaries, and issue focus transitions in `prefers-reduced-motion: reduce` with `animation`, `transition`, and `transform` disabled.

- [ ] **Step 4: Run all Decision Dock component and CSS tests**

```bash
npm test -- src/features/agent-canvas/chat/DecisionDockFrame.test.tsx src/features/agent-canvas/chat/ConceptChoiceDecisionDock.test.tsx src/features/agent-canvas/chat/QuestionnaireDecisionDock.test.tsx src/features/agent-canvas/chat/MediaReviewDecisionDock.test.tsx src/features/agent-canvas/chat/GuidedInteractionCard.test.tsx src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx
```

Expected: shared frame, all interaction kinds, panel placement, and style contracts pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/agent-canvas/chat/agent-canvas-chat.css apps/web/src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx
git commit -m "style(agent-chat): finish decision dock visual system"
```

---

### Task 8: Verify the Complete Decision Dock

**Files:**

- Verification only unless a failing command reveals a scoped defect in files already listed above.

**Interfaces:**

- Consumes: Tasks 1 through 7.
- Produces: verified feature branch ready for review and integration.

- [ ] **Step 1: Run every focused Decision Dock suite**

From `apps/web`:

```bash
npm test -- src/features/agent-canvas/chat/decisionDockIssue.test.ts src/features/agent-canvas/chat/DecisionDockFrame.test.tsx src/features/agent-canvas/chat/ConceptChoiceDecisionDock.test.tsx src/features/agent-canvas/chat/QuestionnaireDecisionDock.test.tsx src/features/agent-canvas/chat/MediaReviewDecisionDock.test.tsx src/features/agent-canvas/chat/GuidedInteractionCard.test.tsx src/features/agent-canvas/chat/ProposalOptionRow.test.tsx src/features/agent-canvas/chat/useAgentCanvasChat.test.tsx src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx
```

Expected: all focused tests pass without act warnings or unhandled rejections.

- [ ] **Step 2: Run full frontend quality checks**

```bash
npm test
npm run typecheck
npm run lint
npm run build
npm run check:agent-canvas-contract
```

Expected: every command exits with status 0; the build emits the Vite manifest; the Agent Canvas contract check reports no frontend/backend mismatch.

- [ ] **Step 3: Start the frontend for manual verification**

```bash
npm run dev -- --port 5190
```

Open `http://localhost:5190`, enter Projects, and open a current project that exposes each Guided Interaction kind. Use workflow `adwf_v2_cab9e8634af86330` for concept-history context, then use a fresh current workflow to reach active concept, questionnaire, and media review interactions.

- [ ] **Step 4: Verify Concept Choice manually**

Confirm:

1. options are visible without another click;
2. locale, option count, IDs, and revisions are absent;
3. unselected summaries clamp to two lines;
4. selected summary expands fully with monochrome checked state;
5. References and More start closed;
6. Custom direction and confirmation modes preserve the option selection;
7. exactly one primary submit action exists;
8. submitting locks the Dock and keeps selected copy;
9. backend success removes the Dock and updates Stage Thread history;
10. failure keeps input and shows concise local error.

- [ ] **Step 5: Verify Questionnaire and Media Review manually**

Confirm:

- questionnaire progress and required validation are correct;
- duration error appears beside the duration field;
- Accept is the default media action;
- Retry and Replace select a mode without submitting immediately;
- Replace preserves its instruction while pending;
- only the chosen primary action says Submitting;
- Exclude requires confirmation.

- [ ] **Step 6: Verify responsive, keyboard, scroll, and motion behavior**

At the normal 390px rail and the existing 330px narrow rail:

- header and footer remain visible while only the body scrolls;
- timeline remains visible above the Dock;
- footer stacks without clipping text;
- no horizontal scrollbar appears;
- Tab reaches options, References, More, secondary modes, Cancel, and primary action in logical order;
- Space and Enter operate options and disclosures;
- focus moves to a newly displayed interaction issue;
- reduced-motion mode removes new animation without hiding state.

- [ ] **Step 7: Stop the dev server and inspect the branch**

From the worktree root:

```bash
git diff --check main...HEAD
git status --short
git log --oneline --decorate main..HEAD
```

Expected:

- `git diff --check` prints nothing;
- the worktree is clean;
- the branch contains the seven scoped commits from Tasks 1 through 7.

- [ ] **Step 8: Request review and prepare integration**

Invoke `superpowers:requesting-code-review` against `main...feat/agent-chat-decision-dock`. Resolve only verified findings, rerun Steps 1 and 2, then invoke `superpowers:finishing-a-development-branch` to present merge, PR, or cleanup choices.

---

## Final Acceptance Checklist

- [ ] All three Guided Interaction kinds use `DecisionDockFrame`.
- [ ] Active interaction stays directly above the composer and outside timeline scrolling.
- [ ] Concept options open directly and selected content expands.
- [ ] References and More default to collapsed.
- [ ] Unsupported `revise` is not exposed through the Guided Interaction request path.
- [ ] Questionnaire progress, custom values, Skip, and field errors preserve the existing request union.
- [ ] Media Accept, Retry, Replace, and Exclude preserve the existing request union.
- [ ] Exactly one primary action is present in each Dock state.
- [ ] Pending locks controls and preserves every local value.
- [ ] Backend authority removes or replaces the Dock after success.
- [ ] Guided Interaction failures are local; unrelated failures remain global.
- [ ] Raw HTTP, schema, locale, ID, and revision metadata are not primary visible copy.
- [ ] Existing palette values, Stage Threads, composer tools, Skill selector, assets, and document behavior are unchanged.
- [ ] Keyboard operation, issue focus, 390px and 330px rails, scroll ownership, and reduced motion pass.
- [ ] Focused tests, full tests, typecheck, lint, build, and Agent Canvas contract check pass.
