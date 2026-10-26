# UI/UX Proposal: Make the AdCraft Workflow Easier to Discover

## Summary

This proposal recommends a focused, low-risk frontend improvement pass for AdCraft. The goal is to help a new user understand the path from project creation to final video without changing the existing generation architecture.

The proposal is based on the current web app structure: Home, Projects, Assets, API Space, and the Agent Canvas.

## Problems observed

- The homepage, Projects, Assets, and Agent Canvas have different surface, border, radius, and motion conventions. The product feels like several related screens rather than one continuous workflow.
- The first-run path is implicit. Users must discover how project creation, assets, API configuration, and the canvas relate to one another.
- The Agent Canvas places execution, layout, asset browsing, chat visibility, and runtime actions close together. The available actions are powerful, but their priority is not immediately clear.
- API and runtime indicators expose useful state, but a status such as “not configured” should also explain the next action and where to take it.
- Empty, loading, and error states generally describe what happened, but do not consistently provide a recovery action or an example of the expected input.
- The canvas uses a fixed chat column and a dense two-panel layout. At narrower widths, secondary controls compete with the primary workflow.

## Proposed changes

1. Establish a small set of shared UI tokens for surfaces, borders, radii, spacing, text hierarchy, and action emphasis. Apply them to the existing page styles rather than adding a new UI library.
2. Add a compact first-run guide to empty project and workflow states. It should show the recommended sequence: configure a provider, define the brief, review generated assets, and run the workflow.
3. Reorganize Agent Canvas actions into clear intent groups: edit, execute, layout, assets, and assistant visibility. Preserve all existing actions and keyboard access.
4. Make API, runtime, loading, and error states actionable by pairing the state message with a next step such as “Open API Space”, “Retry”, or “Run this node”.
5. On narrow viewports, collapse secondary panels and keep the primary canvas action, status, and navigation reachable without horizontal scrolling.
6. Keep navigation, data contracts, model providers, generation logic, React Flow behavior, and asset APIs unchanged.

## Acceptance criteria

- Home, Projects, Assets, and Agent Canvas share the same core visual tokens while retaining their individual purpose.
- An empty project/workflow view communicates the next step and provides a direct action.
- Agent Canvas makes the primary execution action clear in idle, running, success, and error states.
- API and runtime states include an understandable recovery or configuration path.
- The workflow remains usable at desktop, tablet, and narrow viewport widths without horizontal scrolling.
- Icon-only controls retain accessible names, visible focus, and useful tooltips where appropriate.

## Suggested implementation order

1. Define and apply shared tokens.
2. Improve empty and status states.
3. Rebalance Agent Canvas toolbar hierarchy.
4. Add narrow-screen panel behavior.
5. Run interaction, accessibility, and browser smoke checks.

## Scope and non-goals

This is an incremental frontend improvement. It does not introduce a new component library, replace React Flow, redesign the backend, change model providers, alter generation behavior, or change the visual identity of the product.

## Verification

- `npm run typecheck`
- `npm test`
- `npm run test:browser:agent-role:smoke` when browser test dependencies are available
- Manual checks for fresh start, API-not-configured, API-ready, empty project, populated project, asset browsing, canvas execution, keyboard navigation, and narrow viewport layouts

## Reviewer notes

This document is intentionally scoped as a proposal. It is designed to establish a shared UI direction before making broader visual changes, while keeping the implementation easy to review and easy to revert.
