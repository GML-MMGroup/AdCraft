# Agent Conversation Shell v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Every behavior change follows RED, GREEN, refactor, and focused verification.

**Goal:** Turn the existing Agent Canvas chat rail into one coherent Conversation Shell with scoped recovery, visible next-message context, and readable natural messages while preserving backend authority and every existing Guided Interaction payload.

**Architecture:** Keep `AgentCanvasChatPanel` as the public composition module and `useAgentCanvasChat` as the authoritative chat-state owner. Add three deep presentation modules at explicit seams: recovery projection, composer-context projection/ownership, and natural-message presentation. The modules consume existing workflow, API error, timeline, Skill, node, and asset facts; they never infer workflow meaning from message text.

**Tech Stack:** React 19, TypeScript 5.8, Vitest 4, Testing Library, plain CSS, existing Agent Canvas V2 client/types, existing markdown renderer, and existing project-asset upload endpoint.

**Spec:** `docs/superpowers/specs/2026-08-27-agent-conversation-shell-v2-design.md`

## Global Constraints

- Execute in `/data/longwei.wu/AdCraft-worktrees/agent-conversation-shell-v2` on branch `feat/agent-conversation-shell-v2`, created from the plan commit on local `main`.
- Do not modify backend code, routes, schemas, actions, revisions, idempotency behavior, or request payloads.
- Do not parse message text for `Summary`, `Result`, `Next action`, Chinese equivalents, or any inferred semantic section.
- Preserve Stage Thread projection, document browsing, Decision Dock payloads, Canvas authority, execution mode, Skill activation, and Turn Retry behavior.
- Keep the approved monochrome palette and avoid gradients, glow, severity colors, decorative dots, nested outer cards, modals, and side sheets.
- Context assets and node mentions remain message-scoped; active Skill remains workflow-scoped.
- Clear message text, selected assets, and selected nodes only after the backend accepts the message.
- An error has exactly one presentation owner. Raw HTTP text, schema paths, and backend codes appear only in a closed Technical details disclosure.
- Use the backend/API error's existing retryability and existing actions. Do not invent automatic retries.
- Keep Timeline as the primary scroll owner. Expanding or removing lower Shell regions must not force-scroll historical content.
- Keep the normal 390px rail and 330px narrow rail usable without horizontal overflow.

## File Structure

### New production files

- `apps/web/src/features/agent-canvas/chat/conversationRecovery.ts`
  - Pure `ConversationRecoveryView` projection and scope/action mapping from existing errors.
- `apps/web/src/features/agent-canvas/chat/ConversationRecoverySurface.tsx`
  - Accessible recovery UI with one valid action and closed technical details.
- `apps/web/src/features/agent-canvas/chat/composerContext.ts`
  - Pure context projection, ID deduplication, and display-safe Skill/asset/node views.
- `apps/web/src/features/agent-canvas/chat/useComposerContext.ts`
  - Message-scoped selection and upload ownership behind one small interface.
- `apps/web/src/features/agent-canvas/chat/ComposerContextTray.tsx`
  - Collapsed counts, expanded groups, removals, node focus, and upload status.
- `apps/web/src/features/agent-canvas/chat/naturalMessagePresentation.ts`
  - Pure speaker-run projection; no text parsing.
- `apps/web/src/features/agent-canvas/chat/NaturalMessage.tsx`
  - User/Agent message rendering, markdown, timestamp details, and long-content expansion.

### New test files

- `apps/web/src/features/agent-canvas/chat/conversationRecovery.test.ts`
- `apps/web/src/features/agent-canvas/chat/ConversationRecoverySurface.test.tsx`
- `apps/web/src/features/agent-canvas/chat/composerContext.test.ts`
- `apps/web/src/features/agent-canvas/chat/useComposerContext.test.tsx`
- `apps/web/src/features/agent-canvas/chat/ComposerContextTray.test.tsx`
- `apps/web/src/features/agent-canvas/chat/naturalMessagePresentation.test.ts`
- `apps/web/src/features/agent-canvas/chat/NaturalMessage.test.tsx`

### Modified production files

- `apps/web/src/features/agent-canvas/chat/useAgentCanvasChat.ts`
  - Replace the undifferentiated error string with scoped recovery projections while preserving exact technical detail and failed message drafts.
- `apps/web/src/features/agent-canvas/chat/AgentCanvasChatPanel.tsx`
  - Compose the ordered Shell regions and delegate context/message/recovery rendering to focused modules.
- `apps/web/src/features/agent-canvas/chat/useChatTimelineScroll.ts`
  - Only if a regression test shows missing scroll retention; do not change its interface speculatively.
- `apps/web/src/features/agent-canvas/chat/agent-canvas-chat.css`
  - Shell hierarchy, context/recovery/message typography, responsive layout, focus, and reduced motion.

### Modified test files

- `apps/web/src/features/agent-canvas/chat/useAgentCanvasChat.test.tsx`
- `apps/web/src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx`
- `apps/web/src/features/agent-canvas/chat/useChatTimelineScroll.test.tsx` if present or created only after a failing scroll regression is demonstrated.

---

## Task 1: Add Pure Conversation Presentation Models

**Files:**

- Create: `apps/web/src/features/agent-canvas/chat/conversationRecovery.ts`
- Create: `apps/web/src/features/agent-canvas/chat/conversationRecovery.test.ts`
- Create: `apps/web/src/features/agent-canvas/chat/composerContext.ts`
- Create: `apps/web/src/features/agent-canvas/chat/composerContext.test.ts`
- Create: `apps/web/src/features/agent-canvas/chat/naturalMessagePresentation.ts`
- Create: `apps/web/src/features/agent-canvas/chat/naturalMessagePresentation.test.ts`

**Interfaces:**

```ts
export type ConversationRecoveryScope =
  | "interaction"
  | "composer"
  | "context"
  | "timeline"
  | "workflow";

export interface ConversationRecoveryView {
  scope: ConversationRecoveryScope;
  title: string;
  message: string;
  technicalDetail: string | null;
  action: "retry" | "refresh" | "review" | "none";
}

export function conversationRecoveryFromError(
  scope: Exclude<ConversationRecoveryScope, "interaction">,
  error: unknown,
  options?: { retryable?: boolean },
): ConversationRecoveryView;

export interface ComposerContextView {
  skill: ComposerSkillContext | null;
  assets: ComposerAssetContext[];
  nodes: ComposerNodeContext[];
  uploadState: "idle" | "uploading" | "failed";
}

export function buildComposerContextView(input: ComposerContextInput): ComposerContextView;

export interface NaturalMessagePresentation {
  messageId: string;
  showAgentIdentity: boolean;
  startsSpeakerRun: boolean;
}

export function projectNaturalMessagePresentation(
  items: ChatTimelineItemV2[],
): Map<string, NaturalMessagePresentation>;
```

- [ ] **Step 1: Write failing recovery projection tests**
  - Message-send rejection maps to `composer`, concise copy, allowed Retry, and closed raw detail.
  - Timeline fetch failure maps to Refresh.
  - Contract/permission failures do not invent Retry.
  - Stale authority maps to Review or Refresh using existing backend code/status.
  - Primary copy never contains `Request failed with status`, `Invalid ...`, or a schema path.

- [ ] **Step 2: Run the recovery test and confirm RED**

```bash
npm test -- src/features/agent-canvas/chat/conversationRecovery.test.ts
```

- [ ] **Step 3: Implement the smallest recovery projection and confirm GREEN**

- [ ] **Step 4: Write failing context projection tests**
  - Deduplicate assets and nodes by authoritative ID while preserving first-seen order.
  - Resolve display name, media type, thumbnail, node title, node type, Skill title, and Skill summary.
  - Exclude Skill version, run ID, category, digest, node revision, binding metadata, asset storage data, and provider metadata from the public view.
  - Return `null`/empty groups when selected IDs no longer exist in current authority.
  - Context is hidden only when Skill, assets, nodes, and upload state are all empty/idle.

- [ ] **Step 5: Run the context test and confirm RED, implement, then confirm GREEN**

```bash
npm test -- src/features/agent-canvas/chat/composerContext.test.ts
```

- [ ] **Step 6: Write failing natural-message run tests**
  - The first Agent message in a consecutive Agent run shows identity; subsequent Agent messages do not.
  - A user message or any typed non-message timeline item breaks the Agent run.
  - Consecutive user messages remain distinct bubbles without redundant labels.
  - Text content does not affect grouping.

- [ ] **Step 7: Run RED, implement the run projection, then confirm GREEN**

```bash
npm test -- src/features/agent-canvas/chat/naturalMessagePresentation.test.ts
```

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/features/agent-canvas/chat/conversationRecovery* \
  apps/web/src/features/agent-canvas/chat/composerContext* \
  apps/web/src/features/agent-canvas/chat/naturalMessagePresentation*
git commit -m "feat(agent-chat): model conversation shell presentation"
```

---

## Task 2: Build the Recovery Surface

**Files:**

- Create: `apps/web/src/features/agent-canvas/chat/ConversationRecoverySurface.tsx`
- Create: `apps/web/src/features/agent-canvas/chat/ConversationRecoverySurface.test.tsx`

**Interface:**

```ts
export interface ConversationRecoverySurfaceProps {
  recovery: ConversationRecoveryView;
  onAction?: () => void;
  onDismiss?: () => void;
}
```

- [ ] **Step 1: Write failing component tests**
  - Render title and concise message.
  - Keep technical details closed until explicitly expanded.
  - Render exactly one Retry, Refresh, or Review action when allowed; render none for `action: "none"`.
  - Newly introduced blocking recovery uses `role="alert"` and receives focus.
  - Raw detail is absent from visible text before disclosure expansion.

- [ ] **Step 2: Run RED**

```bash
npm test -- src/features/agent-canvas/chat/ConversationRecoverySurface.test.tsx
```

- [ ] **Step 3: Implement the accessible monochrome surface and confirm GREEN**

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/features/agent-canvas/chat/ConversationRecoverySurface*
git commit -m "feat(agent-chat): add scoped recovery surface"
```

---

## Task 3: Own Message Context and Upload Lifecycle

**Files:**

- Create: `apps/web/src/features/agent-canvas/chat/useComposerContext.ts`
- Create: `apps/web/src/features/agent-canvas/chat/useComposerContext.test.tsx`
- Reuse: `apps/web/src/features/agent-canvas/assets/useAgentCanvasAssets.ts`

**Interface:**

```ts
export function useComposerContext(options: {
  workflow: AgentCanvasWorkflowV2;
  onWorkflowRefresh?: () => Promise<void> | void;
}) {
  return {
    view: ComposerContextView;
    selectedNodeIds: string[];
    selectedAssetIds: string[];
    availableImageAssets: ProjectAssetSummaryV2[];
    uploadIssue: ConversationRecoveryView | null;
    actions: {
      toggleNode(id: string): void;
      toggleAsset(id: string): void;
      removeNode(id: string): void;
      removeAsset(id: string): void;
      upload(files: Iterable<File>): Promise<void>;
      clearMessageContext(): void;
      clearUploadIssue(): void;
    };
  };
}
```

- [ ] **Step 1: Write failing hook tests**
  - Toggle and remove IDs without duplicates.
  - Upload uses the existing workflow-scoped asset upload endpoint and current operation-key helper.
  - Successful upload adds the returned image asset to next-message context and refreshes workflow authority.
  - Uploading and failed states project into Context Tray state.
  - Failed upload preserves existing selected context.
  - `clearMessageContext()` clears assets/nodes but never the workflow Skill.
  - Workflow replacement drops IDs absent from the new authority and resets transient upload state.

- [ ] **Step 2: Run RED**

```bash
npm test -- src/features/agent-canvas/chat/useComposerContext.test.tsx
```

- [ ] **Step 3: Implement using the existing upload client and pure context projection**
  - Do not persist `File` data.
  - Do not auto-retry uploads.
  - Do not introduce another global store.

- [ ] **Step 4: Confirm GREEN and commit**

```bash
git add apps/web/src/features/agent-canvas/chat/useComposerContext*
git commit -m "feat(agent-chat): own next-message context"
```

---

## Task 4: Build the Composer Context Tray

**Files:**

- Create: `apps/web/src/features/agent-canvas/chat/ComposerContextTray.tsx`
- Create: `apps/web/src/features/agent-canvas/chat/ComposerContextTray.test.tsx`
- Reuse: `apps/web/src/features/agent-canvas/canvas/AgentCanvasNodeIcon.tsx`

**Interface:**

```ts
export interface ComposerContextTrayProps {
  view: ComposerContextView;
  uploadIssue: ConversationRecoveryView | null;
  onFocusNode(nodeId: string): void;
  onRemoveNode(nodeId: string): void;
  onRemoveAsset(assetId: string): void;
  onClearUploadIssue(): void;
}
```

- [ ] **Step 1: Write failing component tests**
  - Render nothing for empty idle context.
  - Collapsed row shows `Skill · title`, `Assets · count`, `Nodes · count`, and controlled expansion.
  - Expanded Skill contains only icon/title/summary.
  - Expanded assets show thumbnail/display name/media type and accessible remove controls.
  - Expanded nodes show canonical node icon/title and focus/remove controls.
  - Uploading and failed upload are shown inside the Tray, never as global panel errors.
  - Long names do not expose IDs as fallback when an authoritative display value exists.

- [ ] **Step 2: Run RED**

```bash
npm test -- src/features/agent-canvas/chat/ComposerContextTray.test.tsx
```

- [ ] **Step 3: Implement one compact Tray surface with controlled group disclosures**

- [ ] **Step 4: Confirm GREEN and commit**

```bash
git add apps/web/src/features/agent-canvas/chat/ComposerContextTray*
git commit -m "feat(agent-chat): add composer context tray"
```

---

## Task 5: Build Natural Message Presentation

**Files:**

- Create: `apps/web/src/features/agent-canvas/chat/NaturalMessage.tsx`
- Create: `apps/web/src/features/agent-canvas/chat/NaturalMessage.test.tsx`
- Reuse: `apps/web/src/features/agent-canvas/canvas/AgentCanvasMarkdown.tsx`

**Interface:**

```ts
export interface NaturalMessageProps {
  message: ChatMessageV2;
  presentation: NaturalMessagePresentation;
}
```

- [ ] **Step 1: Write failing component tests**
  - User messages are bubbles without repeated user labels.
  - Only the first Agent message in a run displays `AdCraft Video Agent`.
  - Plain text remains unchanged.
  - Existing markdown renderer handles headings, lists, quotes, links, inline code, and fenced JSON/code blocks.
  - Unsafe links remain blocked by the existing renderer.
  - Long content is initially collapsed, `Show more` reveals the complete unchanged text, and `Show less` restores the compact state.
  - Timestamp is present for accessibility but visually revealed only on hover/focus/detail state through CSS.
  - Strings containing `Summary:` or `结果：` remain ordinary message text.

- [ ] **Step 2: Run RED**

```bash
npm test -- src/features/agent-canvas/chat/NaturalMessage.test.tsx
```

- [ ] **Step 3: Implement without adding a parser or semantic classifier**

- [ ] **Step 4: Confirm GREEN and commit**

```bash
git add apps/web/src/features/agent-canvas/chat/NaturalMessage*
git commit -m "feat(agent-chat): refine natural message presentation"
```

---

## Task 6: Route Errors to One Owner and Preserve Composer State

**Files:**

- Modify: `apps/web/src/features/agent-canvas/chat/useAgentCanvasChat.ts`
- Modify: `apps/web/src/features/agent-canvas/chat/useAgentCanvasChat.test.tsx`

**State changes:**

```ts
state: {
  composerRecovery: ConversationRecoveryView | null;
  timelineRecovery: ConversationRecoveryView | null;
  workflowRecovery: ConversationRecoveryView | null;
  // guidedInteractionIssue and proposalIssues remain local owners.
}
```

- [ ] **Step 1: Add failing hook tests**
  - Guided Interaction errors remain only in `guidedInteractionIssue`.
  - Message submission errors produce only `composerRecovery`, preserve `failedDraft`, and return `false`.
  - Successful message submission clears `composerRecovery`, returns `true`, and does not synthesize a success receipt.
  - Timeline refresh errors produce only `timelineRecovery` with Refresh.
  - Other workflow/session authority failures produce only `workflowRecovery`.
  - Proposal-specific failures remain in `proposalIssues`.
  - A successful replacement operation clears only its owned recovery.
  - Technical detail preserves the backend code/message exactly without exposing it as primary copy.

- [ ] **Step 2: Run focused hook tests and confirm RED**

```bash
npm test -- src/features/agent-canvas/chat/useAgentCanvasChat.test.tsx
```

- [ ] **Step 3: Replace generic error ownership incrementally**
  - Keep legacy retryable Turn behavior but project it into Timeline recovery.
  - Keep `failedDraft` for the existing safe first-send retry only.
  - Do not change accepted Turn Retry endpoint behavior.

- [ ] **Step 4: Confirm GREEN and commit**

```bash
git add apps/web/src/features/agent-canvas/chat/useAgentCanvasChat.ts \
  apps/web/src/features/agent-canvas/chat/useAgentCanvasChat.test.tsx
git commit -m "feat(agent-chat): scope conversation recovery"
```

---

## Task 7: Compose the Conversation Shell

**Files:**

- Modify: `apps/web/src/features/agent-canvas/chat/AgentCanvasChatPanel.tsx`
- Modify: `apps/web/src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx`

- [ ] **Step 1: Write failing integration tests for region order**
  - DOM order is Header, Timeline, active Decision Dock, panel/composer Recovery Surface, Context Tray, Composer.
  - Missing optional regions remove their layout space.
  - Timeline recovery renders inside Timeline ownership, not again below Decision Dock.
  - Interaction error renders only inside Decision Dock.

- [ ] **Step 2: Write failing composer lifecycle tests**
  - Send failure preserves textarea, asset IDs, node IDs, and Context Tray content.
  - Send success clears textarea/assets/nodes only after `submit()` resolves `true`.
  - Active Skill remains visible after accepted send.
  - Retry uses the preserved failed draft without duplicating a visible user message.

- [ ] **Step 3: Write failing context entry tests**
  - `@` remains the node/asset entry action.
  - Existing image assets remain selectable.
  - Upload entry uses the context hook and reflects upload state in the Tray.
  - Composer no longer duplicates selected chips internally.

- [ ] **Step 4: Run panel tests and confirm RED**

```bash
npm test -- src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx
```

- [ ] **Step 5: Integrate the focused modules**
  - Use `NaturalMessage` only for typed `message` items.
  - Preserve all non-natural typed item renderers.
  - Use `projectNaturalMessagePresentation` without message-text inspection.
  - Keep active Decision Dock directly above recovery/context/composer.
  - Call `context.actions.clearMessageContext()` and clear draft only after accepted submit.

- [ ] **Step 6: Confirm GREEN and commit**

```bash
git add apps/web/src/features/agent-canvas/chat/AgentCanvasChatPanel.tsx \
  apps/web/src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx
git commit -m "feat(agent-chat): compose conversation shell v2"
```

---

## Task 8: Complete Visual, Responsive, Scroll, and Accessibility Behavior

**Files:**

- Modify: `apps/web/src/features/agent-canvas/chat/agent-canvas-chat.css`
- Modify: `apps/web/src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx`
- Modify only if a failing test proves necessary: `apps/web/src/features/agent-canvas/chat/useChatTimelineScroll.ts`

- [ ] **Step 1: Add failing style and behavior assertions**
  - Shell uses the approved monochrome tokens only.
  - Timeline is the only outer scrolling region; Decision Dock body owns only its bounded internal scroll.
  - Natural Agent messages are plain; user messages remain compact raised bubbles.
  - Markdown headings, paragraphs, lists, quotes, links, inline code, and code blocks have readable hierarchy.
  - Long links wrap and code blocks scroll horizontally.
  - Recovery and Context Tray use one surface each, not nested cards.
  - Focus-visible styles exist for all actions.
  - 390px retains one collapsed context row; 330px uses count labels and stacked expanded groups.
  - No horizontal panel overflow; Timeline keeps `min-height: 0` and nonzero flex/grid space.
  - New motion is disabled under `prefers-reduced-motion`.

- [ ] **Step 2: Run RED**

```bash
npm test -- src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx \
  src/features/agent-canvas/chat/NaturalMessage.test.tsx \
  src/features/agent-canvas/chat/ComposerContextTray.test.tsx \
  src/features/agent-canvas/chat/ConversationRecoverySurface.test.tsx
```

- [ ] **Step 3: Implement CSS from the existing token system**
  - Motion uses opacity and at most 4px translation.
  - Do not animate dimensions, Timeline scroll, Composer position, or individual context chips.

- [ ] **Step 4: Add a scroll-retention regression only if current hook behavior fails**
  - When not following latest, expanding/removing lower Shell regions does not reset `scrollTop`.
  - When following latest, new Timeline content still follows the bottom.

- [ ] **Step 5: Confirm GREEN and commit**

```bash
git add apps/web/src/features/agent-canvas/chat/agent-canvas-chat.css \
  apps/web/src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx \
  apps/web/src/features/agent-canvas/chat/useChatTimelineScroll.ts \
  apps/web/src/features/agent-canvas/chat/useChatTimelineScroll.test.tsx
git commit -m "style(agent-chat): finish conversation shell v2"
```

---

## Task 9: Integrated Verification, Review, and Local Main Merge

**Files:** Verification only unless a scoped defect is found.

- [ ] **Step 1: Run focused Shell suites**

```bash
npm test -- \
  src/features/agent-canvas/chat/conversationRecovery.test.ts \
  src/features/agent-canvas/chat/ConversationRecoverySurface.test.tsx \
  src/features/agent-canvas/chat/composerContext.test.ts \
  src/features/agent-canvas/chat/useComposerContext.test.tsx \
  src/features/agent-canvas/chat/ComposerContextTray.test.tsx \
  src/features/agent-canvas/chat/naturalMessagePresentation.test.ts \
  src/features/agent-canvas/chat/NaturalMessage.test.tsx \
  src/features/agent-canvas/chat/decisionDockIssue.test.ts \
  src/features/agent-canvas/chat/DecisionDockFrame.test.tsx \
  src/features/agent-canvas/chat/ConceptChoiceDecisionDock.test.tsx \
  src/features/agent-canvas/chat/QuestionnaireDecisionDock.test.tsx \
  src/features/agent-canvas/chat/MediaReviewDecisionDock.test.tsx \
  src/features/agent-canvas/chat/GuidedInteractionCard.test.tsx \
  src/features/agent-canvas/chat/useAgentCanvasChat.test.tsx \
  src/features/agent-canvas/chat/AgentCanvasChatPanel.test.tsx
```

- [ ] **Step 2: Run quality gates**

```bash
npm run typecheck
npm run lint -- --quiet
npm run build
npm test
npm run check:agent-canvas-contract -- /tmp/adworkflow-openapi.json
```

Record existing baseline failures separately. Do not claim full success when a command fails, and do not fix unrelated baseline debt in this feature branch.

- [ ] **Step 3: Run browser verification from the feature worktree**
  - Start an unused Vite port.
  - Verify 390px and 330px rail widths with real or contract-faithful data.
  - Verify keyboard flow, focus after error, Decision Dock body scroll, Context Tray expansion, long markdown, and no horizontal overflow.
  - Verify Timeline scroll remains stable while lower Shell regions expand/disappear.
  - Verify reduced motion.

- [ ] **Step 4: Request code review and resolve only substantiated findings**

- [ ] **Step 5: Stop the feature dev server and merge locally**

From `/data/longwei.wu/AdCraft`:

```bash
git merge --no-ff feat/agent-conversation-shell-v2 -m "merge: agent conversation shell v2"
```

- [ ] **Step 6: Re-run focused tests and typecheck on local `main`**

Do not push a remote branch or create a PR unless the user explicitly requests it.
