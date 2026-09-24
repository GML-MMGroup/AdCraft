# UI Polish Proposal: Improve Workflow Discoverability

## Summary

This proposal focuses on a low-risk UI polish pass for the AdCraft web app. It keeps the current React, React Flow, asset catalog, and generation workflow architecture intact while making the product easier to understand on first use.

## Problems observed

- The homepage, Projects, Assets, and Agent Canvas use related but noticeably different visual languages. The cinematic homepage, glass-heavy library views, and dark canvas do not always feel like one product.
- The first-run path is not explicit. A new user must infer how Home, Projects, Assets, API Space, and a workflow canvas fit together.
- The Agent Canvas exposes several high-value actions at the same visual level: run all, run a node, layout, assets, chat, and runtime controls. This increases decision cost before the user understands the workflow.
- API and runtime status indicators communicate state, but not always the next action required from the user.
- Empty, loading, and error states are functional but could do more to explain what to do next.
- The canvas keeps a two-column layout with a fixed chat panel and limited responsive adaptation, which can make the workflow difficult to use at narrower widths.

## Proposed changes

1. Align shared visual tokens across `theme.css`, `projects.css`, `assets.css`, and the Agent Canvas styles: surface colors, borders, radii, spacing, and action emphasis.
2. Add concise onboarding guidance to the first empty project/workflow state, including the recommended sequence from brief to generated video.
3. Group Agent Canvas actions by intent: create/edit, execute, layout, assets, and assistant visibility. Keep destructive or expensive actions visually distinct.
4. Update API, runtime, loading, and error messages to include a short next step or recovery action.
5. Improve narrow-screen behavior by collapsing secondary panels and preserving access to the primary canvas actions without changing the underlying workflow model.
6. Preserve existing navigation, data contracts, generation logic, React Flow behavior, and asset APIs.

## Acceptance criteria

- The main pages share a recognizable color, type, spacing, and control language.
- A new user can identify the next step from an empty project or workflow state without consulting external documentation.
- The primary Agent Canvas action is visually clear in idle, running, success, and error states.
- API and runtime status messages explain both the current state and the next available action.
- The workflow remains usable on desktop, tablet, and narrow viewport widths.
- Keyboard focus, visible focus states, tooltips, and accessible labels remain available for icon-only actions.

## Scope and non-goals

This is intended as an incremental frontend improvement. It does not introduce a new component library, replace React Flow, redesign the backend, change model providers, or alter generation behavior.

## Verification

- `npm run typecheck`
- `npm test`
- `npm run test:browser:agent-role:smoke` when browser test dependencies are available
- Manual checks for fresh start, API-not-configured, API-ready, empty project, populated project, asset browsing, canvas execution, keyboard navigation, and narrow viewport layouts

