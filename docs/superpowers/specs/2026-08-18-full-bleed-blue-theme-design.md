# Full-Bleed Application Shell And Blue Brand Theme

## Summary

Remove the visible rounded application frame from every route, including Workflow, while preserving the existing layout structure, navigation, background imagery, and page-specific content spacing. Replace purple brand-interaction styling with the agreed blue `#9DAFE6`. Preserve semantic colors and the Discover gallery's purple selection glow.

## Goals

- Make every route feel full-bleed instead of placing content inside a rounded floating shell.
- Keep the existing top navigation, side navigation, route structure, and page content hierarchy.
- Use `#9DAFE6` as the shared brand interaction color.
- Keep color meaning stable for node types, statuses, and media categories.
- Keep the Discover cards' existing purple hover and selected glow unchanged.

## Non-Goals

- Redesigning page content, cards, dialogs, inputs, or navigation controls.
- Removing useful inner component borders or radii.
- Changing node type colors, status colors, media artwork, or the Hero accent treatment.
- Changing Workflow behavior, canvas interactions, or persistence.
- Replacing the background artwork.

## Shell Design

The existing `.app-shell` element remains in the DOM as the common layout boundary. Its visual frame is removed:

- full viewport width;
- no outer margin;
- no border;
- no border radius;
- no shell shadow;
- no translucent shell fill;
- no shell-level backdrop blur;
- no frame-shaped clipping.

The shell continues to own the top bar and route content so existing positioning and route behavior do not need to be rebuilt. Page-specific content wrappers retain their current max widths and horizontal padding. Removing the shell must not make ordinary page content touch the viewport edges.

Workflow uses the same full-bleed shell rule. Its canvas fills the available area beneath the top bar without the current inset margin or bottom gap. Canvas-owned clipping remains local to the canvas where required; the application shell must not create a rounded crop.

## Background And Navigation

The current cosmic background remains fixed behind the application and is no longer visually dependent on the rounded shell. Scrolling moves page content while the background stays stationary.

The top bar remains sticky and keeps its translucent surface. It spans the viewport without being cropped by the former shell radius. The floating side navigation remains in its current position and retains its current clear-glass treatment.

## Brand Color System

The brand token family changes from purple to the agreed blue:

| Token | Value or derivation | Purpose |
| --- | --- | --- |
| `--brand` | `#9DAFE6` | Primary brand interaction color |
| `--brand-hover` | `#B2C0ED` | Hovered brand controls |
| `--brand-subtle` | `#20283F` | Selected backgrounds and quiet emphasis |
| `--focus-ring` | `#CAD4F5` | Keyboard focus |
| legacy brand aliases | Point to the new brand tokens | Compatibility for existing components |

The implementation should prefer centralized tokens over adding more hard-coded blue values. Existing hard-coded purple values should only be changed when they represent generic brand interaction styling.

Brand-color replacement includes:

- active buttons and tabs;
- selected navigation items;
- links and interactive emphasis;
- keyboard focus rings;
- generic loading and progress accents;
- form control accent colors;
- generic selected-state borders and backgrounds.

The following colors remain unchanged:

- Text, Image, Video, Audio, Script, and Editing node type colors;
- success, warning, error, and informational semantic colors;
- media-category colors;
- colors inside images, video, and decorative artwork;
- the Hero `Ad film` gold treatment;
- the Discover gallery's purple hover and selected glow.

## Discover Exception

The Discover gallery selection glow must no longer inherit the global brand token. The local Discover scope owns explicit purple values matching the current design:

- `--discover-selection-glow: rgba(171, 143, 247, 0.22)`;
- `--discover-selection-shadow: rgba(49, 35, 92, 0.32)`;
- `--discover-focus-ring: rgba(190, 167, 252, 0.88)`.

Hover and user-selected states continue to show that purple glow. Merely reaching the center during automatic movement does not introduce a new selected state.

This local exception prevents future brand palette changes from altering the Discover interaction unintentionally.

## Responsive Behavior

- Desktop and web-client layouts remain the primary target.
- Existing page max widths and responsive content breakpoints remain unchanged.
- The application shell has no viewport inset at any supported width.
- The sticky top bar must not create horizontal overflow.
- Workflow must continue to consume the full remaining viewport height.

## Accessibility

- Keyboard focus remains clearly visible after the palette change.
- The new focus color must maintain sufficient contrast against dark surfaces.
- Color is not introduced as the only indicator for status or selection.
- Reduced-motion behavior is unaffected.

## Verification

Automated verification should cover:

- shell styling has no border, radius, shadow, inset margin, or frame background;
- Workflow and non-Workflow routes both receive the full-bleed shell;
- the global brand token is `#9DAFE6` and its aliases use the blue family;
- Discover selection glow remains purple and independent of `--brand`;
- semantic red, green, and yellow tokens remain unchanged;
- node type color declarations remain unchanged;
- existing route and theme style tests continue to pass.

Manual browser verification should inspect Home, Projects, Assets, Trash, API Space, and Workflow at representative desktop sizes. Confirm:

- no outer rounded frame is visible;
- the background remains fixed and continuous;
- top and side navigation remain usable;
- ordinary page content keeps its intended inner spacing;
- Workflow has no outer gap and the canvas remains interactive;
- generic interactive accents are blue;
- Discover card glow is still purple;
- no content is clipped or causes unintended horizontal scrolling.

## Implementation Boundaries

The expected implementation is centered on the shared shell and theme styles. Page-specific edits are permitted only to remove remaining brand-purple hard-coding or to preserve layout after the shell becomes full-bleed. Broad component rewrites and unrelated visual refactors are outside this change.
