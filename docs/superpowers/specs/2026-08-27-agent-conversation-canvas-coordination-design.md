# Agent Conversation and Canvas Coordination

## Goal

Connect authoritative conversation records, runtime state, and canvas nodes without
inferring relationships from assistant prose. Users must be able to locate canvas
results from conversation and return from a selected node to its structured source.

## Data projection

`conversationCanvasLinks.ts` projects one shared relationship index from the rendered
stage timeline, raw timeline items, and typed guidance awaiting state.

Relationship sources, in descending authority, are:

1. Artifact `node_id`.
2. Receipt `created_node_ids` and `updated_node_ids`.
3. Message `linked_node_ids` and `script_node_id`.
4. Proposal application `created_node_ids`.
5. Guidance awaiting `node_ids`.

The reverse conversation source for a node is selected independently in this order:
creating receipt, latest updating receipt, latest linked message, latest artifact.
Proposal and guidance relationships support forward navigation but do not invent a
conversation source when none of those four authoritative records exists.

Each rendered conversation location has a stable key. Stage thread relationships are
coalesced under the stage key; standalone items retain their item key. Deleted node IDs
are reported as change counts but are excluded from canvas navigation.

## Coordination state

`AgentCanvasPage` owns:

- chat collapsed state;
- the latest node-to-conversation source index reported by the chat panel;
- a monotonic conversation reveal request;
- transient canvas node highlight IDs.

Conversation-to-canvas navigation uses the existing React Flow instance. One node is
centered; multiple nodes are fit together. The operation selects no workbench and does
not modify Composer context. Related nodes receive a neutral 1.5 second outline.

Canvas-to-conversation navigation is exposed only for a selected node with an indexed
source. It expands the chat panel, expands a target Stage Thread when necessary,
scrolls the stable location into view, focuses it, and applies a temporary neutral
outline.

## Current production step

`productionFocusProjection.ts` combines typed guidance awaiting and the runtime
snapshot. Priority is:

1. guidance interaction requiring user action;
2. failed nodes;
3. running nodes;
4. waiting or upstream-blocked nodes;
5. hidden.

Multiple nodes at the same priority are summarized as a group instead of selecting an
arbitrary node. Known phases are translated to concise user actions. Unknown waiting
reasons never expose raw backend strings in the primary UI.

## Visual and accessibility behavior

- Compact monochrome surfaces only; failure may use the existing muted red.
- Link actions are low-emphasis text buttons, not new cards.
- Canvas and conversation highlights use white/gray outlines for 1.5 seconds.
- Reveal targets use `tabIndex=-1`, receive keyboard focus, and retain visible focus.
- Reduced-motion users receive immediate viewport changes and static highlights.

## Non-goals

- No backend or contract changes.
- No node or binding synthesis.
- No text parsing to guess relationships, node names, or runtime meaning.
- No automatic node editor opening and no Composer context mutation.
- Legacy projects without structured relationships simply omit reverse navigation.
