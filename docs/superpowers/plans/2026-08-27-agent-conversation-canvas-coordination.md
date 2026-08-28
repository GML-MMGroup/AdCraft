# Agent Conversation and Canvas Coordination Implementation Plan

1. Add failing unit tests for relationship indexing, source priority, deleted-node
   exclusion, proposal/guidance forward links, and node display labels.
2. Implement `conversationCanvasLinks.ts` and expose stable item keys from the existing
   stage projection.
3. Add failing unit tests for typed production-step priority, aggregation, known phase
   copy, and unknown-reason fallback.
4. Implement `productionFocusProjection.ts` and `CurrentProductionStep.tsx`.
5. Extend the node focus hook with one-node/multi-node canvas navigation and transient
   neutral highlight state; cover viewport calls and timeout cleanup.
6. Add `ConversationNodeLinks.tsx` to Stage Thread, natural messages, artifacts, and
   receipts. Exclude deleted nodes from navigation while preserving their count.
7. Make chat collapse and Stage Thread reveal externally controllable. Add stable
   conversation boundaries that expand, scroll, focus, and highlight the requested
   source.
8. Add `NodeConversationAction.tsx` to selected nodes with an authoritative source and
   wire it to the page-level reveal request.
9. Add compact monochrome styles, visible keyboard focus, and reduced-motion handling.
10. Run focused Vitest suites, full frontend typecheck, production build, lint, and a
    targeted browser mock acceptance for both navigation directions. Review the final
    diff before committing the isolated branch.
