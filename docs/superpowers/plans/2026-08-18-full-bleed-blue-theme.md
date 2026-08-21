# Full-Bleed Application Shell And Blue Brand Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the rounded application frame from every route and replace generic purple brand interactions with `#9DAFE6` blue while preserving semantic colors and the Discover gallery's purple glow.

**Architecture:** Keep `Layout` and `.app-shell` as stable structural boundaries, but make the shell visually transparent and full-viewport. Move the shared cosmic background to the page root, centralize the new blue palette in theme tokens, and keep Discover's purple selection treatment behind local variables so it cannot inherit future brand changes.

**Tech Stack:** React 19, TypeScript, CSS, Vitest, Testing Library, Vite, Playwright/Chromium for manual browser verification.

## Global Constraints

- Apply the full-bleed shell to Home, Projects, Assets, Trash, API Space, and Workflow.
- Use `#9DAFE6` for `--brand`, `#B2C0ED` for `--brand-hover`, `#20283F` for `--brand-subtle`, and `#CAD4F5` for `--focus-ring`.
- Preserve existing page content max widths and inner padding.
- Preserve the current background artwork, sticky top bar, and floating side navigation.
- Preserve node-type colors, media-category colors, `--success: #9CD38E`, `--warning: #E1A750`, `--error: #CA6F6F`, and `--info: #7F9FE8`.
- Preserve Discover purple values `rgba(171, 143, 247, 0.22)`, `rgba(49, 35, 92, 0.32)`, and `rgba(190, 167, 252, 0.88)`.
- Do not modify backend code or API contracts.
- Do not push to a remote repository.

---

### Task 1: Make The Shared Application Shell Full-Bleed

**Files:**
- Modify: `apps/web/src/styles/base.css:138-159,720-725`
- Modify: `apps/web/src/styles/theme.css:72-98,245-248`
- Modify: `apps/web/src/styles/themeStyles.test.ts:145-177`
- Modify: `apps/web/src/quality/routeStyles.test.ts:1-110`
- Modify: `apps/web/src/features/agent-canvas/agent-canvas-page.css:1-20`
- Modify: `apps/web/src/features/agent-canvas/AgentCanvasPage.chrome.test.ts:27-42`

**Interfaces:**
- Consumes: Existing `.app-shell`, `.app-shell--workflow`, `.app-shell--cosmic`, `.topbar`, and route classes emitted by `Layout.tsx`.
- Produces: A structural shell that is full viewport and visually transparent on every route; a fixed cosmic page background independent of shell geometry.

- [ ] **Step 1: Add failing full-bleed shell tests**

Extend `routeStyles.test.ts` with explicit structural assertions:

```ts
it("keeps the shared shell full-bleed without a visible frame", () => {
  const shell = declarationBlock(source("styles/base.css"), ".app-shell");
  const workflowShell = declarationBlock(source("styles/base.css"), ".app-shell--workflow");

  expect(shell).toContain("width: 100%");
  expect(shell).toContain("min-height: 100dvh");
  expect(shell).toContain("margin: 0");
  expect(shell).toContain("overflow: visible");
  expect(shell).toContain("border: 0");
  expect(shell).toContain("border-radius: 0");
  expect(shell).toContain("background: transparent");
  expect(shell).toContain("box-shadow: none");
  expect(shell).toContain("backdrop-filter: none");
  expect(workflowShell).toContain("min-height: 100dvh");
  expect(workflowShell).toContain("margin: 0");
});
```

Update the Agent Canvas chrome assertion so it requires the canvas to consume the entire height below the topbar:

```ts
expect(baseCss).toContain("min-height: 100dvh");
expect(baseCss).toContain("margin: 0");
expect(canvasCss).toContain("height: calc(100dvh - var(--topbar-height))");
expect(canvasCss).not.toContain("var(--topbar-height) - 16px");
```

Replace the old shell-owned cosmic-artwork assertion in `themeStyles.test.ts` with:

```ts
test("keeps cosmic artwork fixed behind every application shell", () => {
  const themeStyles = source("styles/theme.css");
  const body = declarationBlock(themeStyles, ":root body");
  const shell = declarationBlock(themeStyles, ":root .app-shell");
  const cosmicShell = declarationBlock(themeStyles, ":root .app-shell--cosmic");

  expect(body).toContain('url("/assets/home-dark-black-hole.webp")');
  expect(body).toContain("50% 60% / cover fixed no-repeat");
  expect(shell).toContain("background: transparent");
  expect(cosmicShell).toContain("background: transparent");
  expect(cosmicShell).not.toContain("border-color");
  expect(cosmicShell).not.toContain("box-shadow");
});
```

- [ ] **Step 2: Run the shell tests and verify they fail**

Run:

```bash
cd apps/web
npm test -- src/quality/routeStyles.test.ts src/styles/themeStyles.test.ts
```

Expected: FAIL because `.app-shell` still uses viewport insets, a rounded border, a translucent background, shadow, blur, and shell-owned cosmic artwork.

- [ ] **Step 3: Implement the full-bleed structural shell**

Update the shared primitives in `base.css`:

```css
.app-shell {
  position: relative;
  width: 100%;
  min-height: 100vh;
  min-height: 100dvh;
  margin: 0;
  overflow: visible;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  backdrop-filter: none;
}

.app-shell--workflow {
  min-height: 100vh;
  min-height: 100dvh;
  margin: 0;
}
```

Remove the mobile `.app-shell` width, margin, and radius override. Keep the existing mobile topbar and navigation rules.

Move the cosmic layers into the existing `:root body` declaration in `theme.css`:

```css
:root body {
  background:
    linear-gradient(
      90deg,
      rgba(5, 6, 9, 0.9) 0%,
      rgba(6, 7, 10, 0.82) 38%,
      rgba(6, 7, 10, 0.46) 70%,
      rgba(6, 7, 10, 0.62) 100%
    ),
    linear-gradient(180deg, rgba(5, 6, 9, 0.26), rgba(5, 6, 9, 0.68)),
    url("/assets/home-dark-black-hole.webp") 50% 60% / cover fixed no-repeat,
    var(--page-bg);
  color: var(--text-primary);
}
```

Make both theme shell blocks explicitly transparent:

```css
:root .app-shell,
:root .app-shell--cosmic {
  border: 0;
  background: transparent;
  box-shadow: none;
  backdrop-filter: none;
}
```

Change the narrow-screen background-position override to target `:root body` instead of `.app-shell--cosmic`.

Remove the retired shell inset from the Agent Canvas height while retaining its negative margins that cancel `.main-view` content padding:

```css
height: calc(100vh - var(--topbar-height));
height: calc(100dvh - var(--topbar-height));
```

- [ ] **Step 4: Run the shell tests and verify they pass**

Run:

```bash
cd apps/web
npm test -- src/quality/routeStyles.test.ts src/styles/themeStyles.test.ts src/app/routeProviders.test.tsx src/features/agent-canvas/AgentCanvasPage.chrome.test.ts
```

Expected: PASS. Route class assignment remains unchanged, while the shell style assertions confirm a full-bleed surface.

- [ ] **Step 5: Commit the full-bleed shell**

```bash
git add apps/web/src/styles/base.css apps/web/src/styles/theme.css apps/web/src/styles/themeStyles.test.ts apps/web/src/quality/routeStyles.test.ts apps/web/src/features/agent-canvas/agent-canvas-page.css apps/web/src/features/agent-canvas/AgentCanvasPage.chrome.test.ts
git commit -m "style(web): remove rounded application frame"
```

---

### Task 2: Replace The Global Brand Token Family With Blue

**Files:**
- Modify: `apps/web/src/styles/theme.css:1-44`
- Modify: `apps/web/src/styles/base.css:31-57`
- Modify: `apps/web/src/pages/home-typography-lab.css:548-590`
- Modify: `apps/web/src/styles/themeStyles.test.ts:31-72`

**Interfaces:**
- Consumes: Existing `--brand`, `--brand-hover`, `--brand-subtle`, `--focus-ring`, `--mauve`, and `--iris` CSS custom-property consumers.
- Produces: One blue brand token family used by all generic interactions while leaving semantic tokens unchanged.

- [ ] **Step 1: Add failing palette tests**

Update the fixed-theme assertions in `themeStyles.test.ts`:

```ts
test("uses the approved blue brand palette and preserves semantic colors", () => {
  const theme = declarationBlock(source("styles/theme.css"), ":root");
  const base = declarationBlock(source("styles/base.css"), ":root");
  const typographyLab = declarationBlock(
    source("pages/home-typography-lab.css"),
    ".home-typography-lab--dark",
  );

  expect(theme).toContain("--brand: #9DAFE6");
  expect(theme).toContain("--brand-hover: #B2C0ED");
  expect(theme).toContain("--brand-subtle: #20283F");
  expect(theme).toContain("--focus-ring: #CAD4F5");
  expect(theme).toContain("--mauve: var(--brand)");
  expect(theme).toContain("--iris: var(--brand)");
  expect(base).toContain("--mauve: #9DAFE6");
  expect(base).toContain("--iris: #9DAFE6");
  expect(typographyLab).toContain("--brand: #9DAFE6");
  expect(theme).toContain("--success: #9CD38E");
  expect(theme).toContain("--warning: #E1A750");
  expect(theme).toContain("--error: #CA6F6F");
  expect(theme).toContain("--info: #7F9FE8");
});
```

Also replace the old `#9E8BEA` assertion in the token-coverage test with `#9DAFE6`.

- [ ] **Step 2: Run the palette test and verify it fails**

Run:

```bash
cd apps/web
npm test -- src/styles/themeStyles.test.ts
```

Expected: FAIL because the root tokens and typography lab still declare the old purple palette.

- [ ] **Step 3: Implement the blue token family**

Use these exact root declarations in `theme.css`:

```css
--brand: #9DAFE6;
--brand-hover: #B2C0ED;
--brand-subtle: #20283F;
--focus-ring: #CAD4F5;
--mauve: var(--brand);
--iris: var(--brand);
```

Use these compatibility defaults in `base.css`:

```css
--mauve: #9DAFE6;
--iris: #9DAFE6;
```

Mirror the same exact brand token family in `.home-typography-lab--dark`. Do not change the semantic red, green, yellow, or information-blue declarations.

- [ ] **Step 4: Run the palette tests and verify they pass**

Run:

```bash
cd apps/web
npm test -- src/styles/themeStyles.test.ts
```

Expected: PASS with exact blue tokens and unchanged semantic colors.

- [ ] **Step 5: Commit the token migration**

```bash
git add apps/web/src/styles/theme.css apps/web/src/styles/base.css apps/web/src/pages/home-typography-lab.css apps/web/src/styles/themeStyles.test.ts
git commit -m "style(theme): adopt blue brand palette"
```

---

### Task 3: Migrate Generic Purple Interactions And Isolate Discover Purple

**Files:**
- Modify: `apps/web/src/pages/home.css:185-224,465-592`
- Modify: `apps/web/src/pages/DiscoverOrbit.styles.test.ts:1-28`
- Modify: `apps/web/src/pages/HomePage.hero-title.test.tsx:145-165`
- Modify: `apps/web/src/features/agent-canvas/agent-canvas-page.css:1-180,340-780`
- Modify: `apps/web/src/features/agent-canvas/canvas/AgentCanvasConnectedNodeMenu.css:50-70`
- Create: `apps/web/src/styles/brandInteractionStyles.test.ts`

**Interfaces:**
- Consumes: The blue token family from Task 2 and existing Discover selectors.
- Produces: Blue generic interactions across Home and Workflow, explicit local purple Discover tokens, and regression coverage that preserves node-type accents.

- [ ] **Step 1: Add failing Discover isolation tests**

Extend `DiscoverOrbit.styles.test.ts`:

```ts
it("keeps the Discover interaction glow locally purple", () => {
  const orbit = declarationBlock("\\.discover-orbit");
  const selected = declarationBlock(
    "\\.discover-orbit__card:is\\(:hover, :focus-visible, \\.is-selected\\)",
  );
  const focused = declarationBlock("\\.discover-orbit__card:focus-visible");

  expect(orbit).toContain("--discover-selection-glow: rgba(171, 143, 247, 0.22)");
  expect(orbit).toContain("--discover-selection-shadow: rgba(49, 35, 92, 0.32)");
  expect(orbit).toContain("--discover-focus-ring: rgba(190, 167, 252, 0.88)");
  expect(selected).toContain("var(--discover-selection-glow)");
  expect(selected).toContain("var(--discover-selection-shadow)");
  expect(selected).not.toContain("var(--brand)");
  expect(focused).toContain("var(--discover-focus-ring)");
});
```

- [ ] **Step 2: Add failing brand-interaction and semantic-preservation tests**

Create `brandInteractionStyles.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const sourceRoot = resolve(process.cwd(), "src");
const source = (path: string) => readFileSync(resolve(sourceRoot, path), "utf8");

describe("blue brand interactions", () => {
  it("uses theme tokens for generic Home and Agent Canvas interactions", () => {
    const home = source("pages/home.css");
    const canvas = source("features/agent-canvas/agent-canvas-page.css");
    const connectedMenu = source(
      "features/agent-canvas/canvas/AgentCanvasConnectedNodeMenu.css",
    );

    expect(home).toContain("color-mix(in srgb, var(--brand) 30%, transparent)");
    expect(canvas).toContain("--agent-canvas-pointer-dot-color: var(--brand)");
    expect(canvas).toContain("background: var(--brand)");
    expect(canvas).toContain("accent-color: var(--brand)");
    expect(connectedMenu).toContain("color: var(--brand)");
  });

  it("keeps node-type and semantic color declarations unchanged", () => {
    const nodes = source("features/agent-canvas/canvas/AgentCanvasNode.css");
    const theme = source("styles/theme.css");

    expect(nodes).toContain("--agent-node-accent: #7465b5");
    expect(nodes).toContain("--agent-node-accent: #3f9c8e");
    expect(nodes).toContain("--agent-node-accent: #4d78d2");
    expect(theme).toContain("--success: #9CD38E");
    expect(theme).toContain("--warning: #E1A750");
    expect(theme).toContain("--error: #CA6F6F");
  });
});
```

Update the Home CTA assertions in `HomePage.hero-title.test.tsx` to expect blue token-derived backgrounds instead of the previous hard-coded purple rules.

- [ ] **Step 3: Run the focused interaction tests and verify they fail**

Run:

```bash
cd apps/web
npm test -- src/pages/DiscoverOrbit.styles.test.ts src/pages/HomePage.hero-title.test.tsx src/styles/brandInteractionStyles.test.ts
```

Expected: FAIL because Discover has no local tokens and generic Home/Agent Canvas interactions still contain hard-coded purple values.

- [ ] **Step 4: Isolate the Discover purple treatment**

Add the three local variables to `.discover-orbit`:

```css
--discover-selection-glow: rgba(171, 143, 247, 0.22);
--discover-selection-shadow: rgba(49, 35, 92, 0.32);
--discover-focus-ring: rgba(190, 167, 252, 0.88);
```

Use the variables in the card hover/selected shadow and card focus outline. Keep the existing selector behavior, dimensions, animation, and center-card logic unchanged.

- [ ] **Step 5: Replace generic Home and Agent Canvas purple interactions with tokens**

In `home.css`, express the Create Project interaction colors through `--brand`:

```css
background: color-mix(in srgb, var(--brand) 30%, transparent);
border-color: color-mix(in srgb, var(--brand) 52%, white 18%);
box-shadow:
  0 16px 34px color-mix(in srgb, var(--brand) 28%, transparent),
  0 0 30px color-mix(in srgb, var(--brand) 42%, transparent),
  inset 0 1px rgba(255, 255, 255, 0.58);
```

In `agent-canvas-page.css`, replace generic purple interactions with `var(--brand)`, `var(--brand-hover)`, or `var(--brand-subtle)` according to intensity:

- pointer spotlight dot and its glow;
- canvas decorative purple radial wash;
- toolbar hover/active controls and Run button;
- context-menu hover/focus state;
- inspector input-count badge;
- checkbox accent color;
- primary and Save buttons.

Do not change the per-node `--agent-node-accent` declarations in `AgentCanvasNode.css`. Change the connected-node menu's generic action color to `var(--brand)` without changing node-type icons.

- [ ] **Step 6: Run the focused interaction tests and verify they pass**

Run:

```bash
cd apps/web
npm test -- src/pages/DiscoverOrbit.styles.test.ts src/pages/HomePage.hero-title.test.tsx src/styles/brandInteractionStyles.test.ts src/styles/themeStyles.test.ts
```

Expected: PASS. Discover remains explicitly purple, generic interaction styling uses the blue token family, and node-type colors remain unchanged.

- [ ] **Step 7: Commit the interaction migration**

```bash
git add apps/web/src/pages/home.css apps/web/src/pages/DiscoverOrbit.styles.test.ts apps/web/src/pages/HomePage.hero-title.test.tsx apps/web/src/features/agent-canvas/agent-canvas-page.css apps/web/src/features/agent-canvas/canvas/AgentCanvasConnectedNodeMenu.css apps/web/src/styles/brandInteractionStyles.test.ts
git commit -m "style(web): align interactions with blue theme"
```

---

### Task 4: Verify Layout, Theme, And Main Routes

**Files:**
- Modify only if verification finds an in-scope regression in files already listed above.

**Interfaces:**
- Consumes: Full-bleed shell, blue brand tokens, page interaction migration, and Discover exception from Tasks 1-3.
- Produces: Verified frontend behavior ready for review and local-main integration.

- [ ] **Step 1: Run all affected tests**

```bash
cd apps/web
npm test -- \
  src/quality/routeStyles.test.ts \
  src/styles/themeStyles.test.ts \
  src/styles/brandInteractionStyles.test.ts \
  src/app/routeProviders.test.tsx \
  src/pages/HomePage.hero-title.test.tsx \
  src/pages/DiscoverOrbit.styles.test.ts
```

Expected: all listed files pass.

- [ ] **Step 2: Run static verification**

```bash
cd apps/web
npm run typecheck
npm run lint
npm run build
```

Expected: all commands exit with status 0. Existing warnings may be reported only if they were present before this branch and do not originate from modified files.

- [ ] **Step 3: Start the frontend for browser verification**

```bash
cd apps/web
npm run dev -- --port 5189
```

Expected: Vite serves the application at `http://127.0.0.1:5189` without selecting another port.

- [ ] **Step 4: Inspect representative routes in Chromium**

Open `/`, `/projects`, `/assets`, `/trash`, `/api-space`, and an available `/workflow/{id}` route. At desktop viewports `1440x900` and `1920x1080`, verify:

- no outer rounded frame, border, shadow, or viewport inset;
- fixed continuous background while ordinary pages scroll;
- sticky top bar and side navigation remain usable;
- page content retains existing max widths and padding;
- Workflow fills the area below the top bar with no outer or bottom gap;
- generic active, hover, focus, and loading accents are blue;
- Discover hover and selected glow remains purple;
- node-type colors remain distinct and unchanged;
- no horizontal overflow or accidental clipping.

- [ ] **Step 5: Review the branch diff**

```bash
git diff --check main...HEAD
git diff --stat main...HEAD
git status --short --branch
```

Expected: no whitespace errors, only the documented frontend styles/tests/spec/plan are changed, and the worktree is clean.

- [ ] **Step 6: Commit any verification-only correction**

If Step 4 exposed an in-scope visual regression, add only the corrected files and focused regression test, then commit:

```bash
git add apps/web/src/styles apps/web/src/pages apps/web/src/features/agent-canvas
git commit -m "fix(web): finalize full-bleed blue theme"
```

If no correction was needed, do not create an empty commit.
