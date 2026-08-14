# Restore Script Nodes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore Script cards, Script creation from canvas menus, graph participation, and inline Script editing without changing backend APIs.

**Architecture:** The shared visible-node registry is the single authority for menu and graph inclusion. The existing card and inline-workbench seams gain Script-specific text behavior while reusing status, model, patch, and run infrastructure.

**Tech Stack:** React 19, TypeScript 5.8, React Flow, Testing Library, Vitest.

## Global Constraints

- Preserve the backend contract `node_type: "script"`, `creative_role: "script"`, and `role_contract_version: "ad-media-role-v2"`.
- Prefer `structured_content.content`; remain compatible with `script_text` and `text`.
- Do not introduce a new API endpoint or new Script-only state model.
- Keep the recorded unrelated baseline failures out of this feature's production diff.

---

### Task 1: Restore Script to Node Creation and Graph Projection

**Files:**
- Modify: `apps/web/src/features/agent-canvas/model/nodeDefaults.ts`
- Modify: `apps/web/src/features/agent-canvas/model/nodeDefaults.test.ts`
- Modify: `apps/web/src/features/agent-canvas/canvas/AgentCanvasNodePicker.test.tsx`
- Modify: `apps/web/src/features/agent-canvas/canvas/AgentCanvasContextMenu.test.tsx`
- Modify: `apps/web/src/features/agent-canvas/canvas/canvasGraphModel.test.ts`

**Interfaces:**
- Produces: `AgentCanvasVisibleNodeTypeV2 = CanvasNodeTypeV2` and a visible registry containing all six canonical node types.
- Consumes: Existing `createDefaultCanvasNodeRequest`, picker, context menu, and graph projection functions.

- [ ] **Step 1: Write failing registry, menu, and graph tests**

Update expectations so the visible registry contains `script`, clicking `Add Script node` emits `"script"`, and graph projection retains Script nodes plus incident bindings and layout occupancy.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
npm test -- src/features/agent-canvas/model/nodeDefaults.test.ts src/features/agent-canvas/canvas/AgentCanvasNodePicker.test.tsx src/features/agent-canvas/canvas/AgentCanvasContextMenu.test.tsx src/features/agent-canvas/canvas/canvasGraphModel.test.ts
```

Expected: failures show Script is absent from the visible registry and graph.

- [ ] **Step 3: Restore Script in the shared registry**

Use:

```ts
export type AgentCanvasVisibleNodeTypeV2 = CanvasNodeTypeV2;

export const AGENT_CANVAS_VISIBLE_NODE_TYPES = [
  "text", "script", "image", "video", "audio", "editing",
] as const;

export function isAgentCanvasVisibleNodeType(
  nodeType: CanvasNodeTypeV2,
): nodeType is AgentCanvasVisibleNodeTypeV2 {
  return AGENT_CANVAS_VISIBLE_NODE_TYPES.includes(nodeType);
}
```

Retain the existing default request logic so Script receives `creative_role: "script"` and an empty `generation_prompt`.

- [ ] **Step 4: Run tests and verify GREEN**

Run the command from Step 2. Expected: all listed test files pass.

### Task 2: Render Backend Script Documents as Cards

**Files:**
- Modify: `apps/web/src/features/agent-canvas/canvas/AgentCanvasNodeContent.tsx`
- Modify: `apps/web/src/features/agent-canvas/canvas/AgentCanvasNodeTypeIcon.tsx`
- Modify: `apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.tsx`
- Modify: `apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.css`
- Modify: `apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.test.tsx`

**Interfaces:**
- Consumes: `CanvasNodeV2.structured_content`, shared Markdown renderer, shared status shell.
- Produces: A visible Script card whose body is compatible with current and legacy backend payloads.

- [ ] **Step 1: Write failing Script card tests**

Add tests proving a current Script with `{ content: "..." }` and a legacy Script with `{ script_text: "..." }` both render, while an empty Script renders a `script node type` placeholder.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
npm test -- src/features/agent-canvas/canvas/AgentCanvasNode.test.tsx
```

Expected: Script card queries fail because `AgentCanvasNodeCard` returns `null`.

- [ ] **Step 3: Implement Script card rendering**

Remove Script visibility guards from the card and renderer. Extend display-text selection:

```ts
if (node.node_type === "script") {
  return nonEmptyString(node.structured_content.content)
    ?? nonEmptyString(node.structured_content.script_text)
    ?? nonEmptyString(node.structured_content.text)
    ?? nonEmptyString(node.generation_prompt)
    ?? nonEmptyString(node.summary_prompt);
}
```

Map Script placeholder artwork to `/imgs/text.webp` and give Script the text-family accent in CSS.

- [ ] **Step 4: Run tests and verify GREEN**

Run the command from Step 2. Expected: the Script cases and existing card suite pass.

### Task 3: Restore Inline Script Editing and Run Controls

**Files:**
- Create: `apps/web/src/features/agent-canvas/workbench/ScriptWorkbench.tsx`
- Modify: `apps/web/src/features/agent-canvas/workbench/AgentCanvasInlineWorkbench.tsx`
- Modify: `apps/web/src/features/agent-canvas/workbench/useNodeWorkbenchDraft.ts`
- Modify: `apps/web/src/features/agent-canvas/workbench/AgentCanvasInlineWorkbench.test.tsx`

**Interfaces:**
- Consumes: `NodeWorkbenchDraft`, existing provider-model props, `patchNode`, and `onRun`.
- Produces: `ScriptWorkbench` with `Script content` textarea and existing save/run semantics.

- [ ] **Step 1: Write failing Script workbench tests**

Replace the retired-node assertion with tests that render `Script content`, preserve existing structured fields when saving, and call `onRun` after patching edited content.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
npm test -- src/features/agent-canvas/workbench/AgentCanvasInlineWorkbench.test.tsx
```

Expected: the Script workbench is empty.

- [ ] **Step 3: Restore Script workbench and draft semantics**

Treat Script as editable structured text and a provider-backed node:

```ts
const editsTextContent = node.node_type === "text" || node.node_type === "script";
const usesProvider = !isWorldSetting
  && ["text", "script", "image", "video", "audio"].includes(node.node_type);
```

Render `ScriptWorkbench` for Script nodes. Its run button uses `draft.run()` for Draft/Failed and `draft.save()` for Ready, matching existing node lifecycle behavior.

- [ ] **Step 4: Run tests and verify GREEN**

Run the command from Step 2. Expected: all workbench tests pass.

### Task 4: Verify the Restored Authoring Path

**Files:**
- Review all files changed by Tasks 1–3.

**Interfaces:**
- Consumes: All restored Script behavior.
- Produces: Verification evidence and a clean feature diff.

- [ ] **Step 1: Run all Script-adjacent tests**

```bash
npm test -- src/features/agent-canvas/model/nodeDefaults.test.ts src/features/agent-canvas/canvas/AgentCanvasNodePicker.test.tsx src/features/agent-canvas/canvas/AgentCanvasContextMenu.test.tsx src/features/agent-canvas/canvas/canvasGraphModel.test.ts src/features/agent-canvas/canvas/AgentCanvasNode.test.tsx src/features/agent-canvas/workbench/AgentCanvasInlineWorkbench.test.tsx
```

- [ ] **Step 2: Run static verification**

```bash
npm run typecheck
npx eslint src/features/agent-canvas/model/nodeDefaults.ts src/features/agent-canvas/model/nodeDefaults.test.ts src/features/agent-canvas/canvas/AgentCanvasNodePicker.test.tsx src/features/agent-canvas/canvas/AgentCanvasContextMenu.test.tsx src/features/agent-canvas/canvas/canvasGraphModel.test.ts src/features/agent-canvas/canvas/AgentCanvasNodeContent.tsx src/features/agent-canvas/canvas/AgentCanvasNodeTypeIcon.tsx src/features/agent-canvas/canvas/AgentCanvasNode.tsx src/features/agent-canvas/canvas/AgentCanvasNode.test.tsx src/features/agent-canvas/workbench/ScriptWorkbench.tsx src/features/agent-canvas/workbench/AgentCanvasInlineWorkbench.tsx src/features/agent-canvas/workbench/useNodeWorkbenchDraft.ts src/features/agent-canvas/workbench/AgentCanvasInlineWorkbench.test.tsx
npm run build
```

- [ ] **Step 3: Compare the full suite with the recorded baseline**

Run `npm test`. Expected: no Script-related failures; only the two recorded unrelated baseline assertions and the recorded browser-global errors may remain.

- [ ] **Step 4: Inspect the diff**

Run `git diff --check` and `git diff --stat`. Confirm there are no unrelated production changes.
