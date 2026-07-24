# Assets Discover Cards Design

**Date:** 2026-07-23

## Goal

Make the Assets page card grid visually consistent with the Home page Discover
section while fixing the absolute-positioning bug that lets card media cover
tabs, controls, and neighboring content.

The page must also remove the Recommended Assets save action and omit the empty
detail placeholder until a real asset is selected.

## Scope

- Render asset cards as full-bleed, rounded image cards with a bottom gradient
  and the asset `display_name`.
- Do not render a play button on asset cards.
- Keep each card as an accessible button that opens the asset detail panel.
- Contain all absolutely positioned card content inside its own card.
- Remove the `Save to My Assets` button, callback, request, success message, and
  error path from the Assets page.
- Render no detail panel when no asset is selected.
- Let the asset grid use the full content width while no detail is shown.
- Render the existing detail panel only while detail data is loading or loaded.
- Preserve editing, favorite, trash, restore, upload, catalog, search, category,
  pagination, and detail-member behavior.

## Non-Goals

- The twelve images under the repository-root `assets/` directory are README
  and GitHub presentation resources. They must not be imported into or indexed
  by Recommended Assets.
- Do not change the recommended catalog ingestion or backend asset endpoints.
- Do not redesign the Home page Discover section.
- Do not address unrelated catalog, accessibility, or asset-data issues outside
  the requested card and detail-panel behavior.

## Considered Approaches

### 1. Patch the missing positioning rule only

Add `position: relative` to the existing card and remove the save button.

This is low risk but leaves duplicated Discover styling, internal IDs on the
card, and the always-present empty detail column. It does not meet the requested
complete interaction.

### 2. Extract a generic shared React card component

Create a generic Discover card component and migrate both Home and Assets to it.

This maximizes component reuse, but the Home card has masonry sizing, a play
control, and modal behavior that Assets does not share. Migrating Home increases
the regression surface without improving the requested Assets workflow.

### 3. Share the visual contract and keep page-specific behavior

Keep the Home and Assets JSX separate, but make the Assets card follow the same
visual structure and CSS contract: positioned overflow container, full-bleed
media, bottom gradient, and title overlay. Assets retains its own selection and
detail behavior and omits the play affordance.

This is the selected approach. It reuses the established visual language without
coupling two different interactions.

## UI Design

### Card

- The button is the containing block with `position: relative`,
  `overflow: hidden`, stable aspect ratio, and inherited rounded corners.
- Image or video preview fills the card with `object-fit: cover`.
- A non-interactive dark gradient sits above the media.
- The asset `display_name` is shown as a single bottom title. Internal entity IDs
  and type labels are not displayed on the card.
- The accessible name includes the display name.
- Hover, focus, and selected states use contained elevation/border treatment and
  do not expand media beyond the card.
- No central play icon is rendered, including for video assets.

### Detail Layout

- With no selected entity, the detail component renders nothing and the layout
  uses one full-width grid column.
- As soon as an entity is selected, the layout exposes the detail column and
  shows its loading state.
- Once loaded, the existing member previews, provenance, editable fields, and
  lifecycle actions continue to work according to asset scope.
- Closing the detail panel restores the full-width card grid.
- Recommended details show provenance only; they have no save action.

### Responsive Behavior

- Desktop uses the current right-side detail column only when detail is active.
- Narrow viewports keep the existing stacked detail layout.
- Card dimensions remain stable while images load and while selection changes.
- Controls, tabs, cards, and detail content must remain independently clickable.

## State and Data Flow

- `selectedEntityId` remains the source of truth for whether detail UI is active.
- Selecting a card sets the entity ID and triggers the existing detail fetch.
- Scope or category changes clear selection and remove the detail column.
- Closing detail clears both selected ID and detail data.
- The Recommended save function and callback chain are deleted.
- Existing `v2Api` usage remains for My Assets update, trash, restore, and upload
  workflows.

## Error Handling

- Detail-fetch failures continue to use the lightweight page feedback message.
- A failed detail request must not leave media or invisible overlays covering the
  grid controls.
- Removing the Recommended save action also removes its save-specific success
  and failure messages.

## Verification

- Add a focused regression test for the Assets card contract:
  - title uses `display_name`;
  - internal ID/type labels are absent;
  - no play control is rendered;
  - Recommended save UI and callback path are absent;
  - the empty detail placeholder is absent;
  - layout state reflects whether detail is active;
  - the card establishes a positioned, clipped containing block.
- Run the frontend React lint and production build.
- Run existing asset-library and recommended-catalog tests.
- Verify the running page at desktop and mobile widths:
  - tabs and category buttons are clickable;
  - cards do not intercept clicks outside their bounds;
  - no detail panel appears before selection;
  - selecting and closing a card toggles the detail layout;
  - all card previews stay clipped and titles remain readable.
