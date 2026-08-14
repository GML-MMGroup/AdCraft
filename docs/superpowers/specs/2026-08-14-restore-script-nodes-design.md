# Restore Script Nodes Design

## Goal

Restore Script as a first-class Agent Canvas node so backend-created Script documents remain visible and users can also create Script nodes from the canvas context menu.

## Existing Contract

The backend continues to expose Script nodes with `node_type: "script"` and `creative_role: "script"`. Generated Script documents store their editable body in `structured_content.content`; older persisted nodes may use `script_text` or `text`. Script nodes participate in text-context bindings and use the existing node create, patch, and run endpoints.

## Design

Script rejoins the shared visible-node registry. This makes it available to the context-menu node picker and causes graph projection, layout collision detection, and binding projection to treat Script exactly like the other authoring node types.

The shared card renderer displays Script text using this precedence: `structured_content.content`, `structured_content.script_text`, `structured_content.text`, then `generation_prompt` or `summary_prompt`. Fallback applies when a field is absent; an explicitly empty current `content` remains empty instead of resurrecting legacy text. An empty Script uses the existing text-family placeholder artwork. Script retains the standard Draft, Working, Ready, and Failed states.

Double-clicking a Script opens an inline Script workbench. Draft and Failed nodes edit `generation_prompt`, expose the existing model selector, and then run or retry through the existing node runtime callbacks. This keeps `structured_content` empty so the backend does not prematurely transition the node to Ready before execution. Ready nodes edit `structured_content.content` in place while preserving all other structured fields. The workbench consumes the same live runtime status as the card, so Working nodes remain read-only even before canonical workflow state catches up. No new API or backend behavior is introduced.

## Error Handling

Script uses the shared node error state and workbench error mapping. Missing content renders the placeholder rather than an empty card. Existing backend validation and retry semantics remain authoritative.

## Tests

Tests will prove that:

- Script appears in the shared node picker and context-menu creation callback.
- A default Script request uses the backend contract.
- Graph projection keeps Script nodes, incident bindings, and layout occupancy.
- Script cards render current and legacy structured text.
- The Script workbench edits and runs Draft/Failed prompts, saves Ready content, and prevents Working-state overwrites.

The repository baseline currently has two unrelated failing assertions and five unrelated unhandled browser-global errors. Script-specific tests, type checking, linting of touched files, and the production build will be used to evaluate this change while the baseline failures remain recorded.
