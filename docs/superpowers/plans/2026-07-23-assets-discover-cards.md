# Assets Discover Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver full-width Discover-style asset cards that cannot escape their grid, remove Recommended saving, and show the detail column only for a selected asset.

**Architecture:** Keep Home and Assets interactions separate while applying the existing Discover visual contract to the Assets-specific card. `selectedEntityId` controls the two-column layout, the existing detail fetch supplies panel content, and the Recommended save request path is removed only from the Assets page.

**Tech Stack:** React 19, TypeScript, Vite, Vitest, Testing Library, jsdom, CSS Grid.

## Global Constraints

- Repository-root `assets/` images are GitHub presentation resources and must not enter Recommended Assets.
- Asset cards show only `display_name`; internal type labels and entity IDs are hidden.
- Asset cards have no play control.
- No `Save to My Assets` UI or frontend request path remains.
- No empty detail placeholder is rendered before selection.
- Existing My Assets edit, favorite, trash, restore, upload, search, catalog, and pagination behavior remains.
- Card media and overlays stay clipped to their own positioned card.

---

### Task 1: Add Assets Page Regression Coverage

**Files:**
- Modify: `apps/web/package.json`
- Modify: `apps/web/package-lock.json`
- Create: `apps/web/vitest.config.ts`
- Create: `apps/web/src/pages/AssetsPage.test.tsx`

**Interfaces:**
- Consumes: `AssetsPage`, `useV2AssetLibrary`, and `useRecommendedCatalog`.
- Produces: `npm run test:assets-page`, a jsdom regression suite for card, detail, and CSS behavior.

- [ ] **Step 1: Install the test runner and DOM test utilities**

Run:

```bash
cd apps/web
npm install --save-dev vitest jsdom @testing-library/react
```

Expected: `package.json` and `package-lock.json` gain compatible development dependencies.

- [ ] **Step 2: Add the test command and Vitest configuration**

Add to `package.json`:

```json
"test:assets-page": "vitest run src/pages/AssetsPage.test.tsx"
```

Create `vitest.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    restoreMocks: true,
  },
});
```

- [ ] **Step 3: Write failing behavior tests**

Create `src/pages/AssetsPage.test.tsx` with a realistic asset summary/detail fixture and mocked asset hooks. Test these independent behaviors:

```tsx
it("renders a Discover-style card using only the display name", () => {
  const { container } = render(<AssetsPage />);
  const card = screen.getByRole("button", { name: "Open asset Portrait Spark" });

  expect(card.textContent).toBe("Portrait Spark");
  expect(card.querySelector(".play-dot")).toBeNull();
  expect(card.textContent).not.toContain("recommended-v1-character-001");
  expect(container.querySelector(".v2-asset-entity-card-title")).toBeTruthy();
});

it("does not reserve a detail panel until a card is selected", async () => {
  const { container } = render(<AssetsPage />);
  const layout = container.querySelector(".v2-asset-library-layout");

  expect(screen.queryByText("Select an asset to view its members.")).toBeNull();
  expect(layout?.classList.contains("is-detail-open")).toBe(false);

  fireEvent.click(container.querySelector(".v2-asset-entity-card") as HTMLElement);
  expect(await screen.findByRole("heading", { name: "Portrait Spark" })).toBeTruthy();
  expect(layout?.classList.contains("is-detail-open")).toBe(true);
});

it("does not offer saving for a recommended detail", async () => {
  const { container } = render(<AssetsPage />);
  fireEvent.click(container.querySelector(".v2-asset-entity-card") as HTMLElement);

  await screen.findByRole("heading", { name: "Portrait Spark" });
  expect(screen.queryByRole("button", { name: "Save to My Assets" })).toBeNull();
});

it("contains full-bleed media inside the asset card", () => {
  const card = document.createElement("button");
  card.className = "v2-asset-entity-card v2-asset-discover-card";
  document.body.append(card);

  const computed = window.getComputedStyle(card);
  expect(computed.position).toBe("relative");
  expect(computed.overflow).toBe("hidden");
});
```

- [ ] **Step 4: Run the regression test and verify RED**

Run:

```bash
cd apps/web
npm run test:assets-page
```

Expected: FAIL because the current card exposes the entity ID, its accessible name uses the ID, the empty detail placeholder and save button still render, and the card is statically positioned.

---

### Task 2: Implement Card and Detail Behavior

**Files:**
- Modify: `apps/web/src/pages/AssetsPage.tsx`
- Modify: `apps/web/src/styles.css`
- Test: `apps/web/src/pages/AssetsPage.test.tsx`

**Interfaces:**
- Consumes: `V2AssetLibraryEntitySummary.display_name`, `selectedEntityId`, and the existing detail fetch.
- Produces: `.v2-asset-entity-card-title` and `.v2-asset-library-layout.is-detail-open`.

- [ ] **Step 1: Remove the Recommended save request path**

Delete `saveRecommended`, the `onSaveRecommended` prop and call site, and the `Save to My Assets` button. Keep provenance output for Recommended details.

- [ ] **Step 2: Render the requested card contract**

Replace the ID overlay with:

```tsx
<span className="v2-asset-entity-card-title">{entity.display_name}</span>
```

Set the card accessible label to:

```tsx
aria-label={`Open asset ${entity.display_name}`}
```

Delete `assetEntityIdentityLabel`.

- [ ] **Step 3: Make detail layout selection-driven**

Render:

```tsx
<div className={`v2-asset-library-layout ${selectedEntityId ? "is-detail-open" : ""}`}>
```

Clear stale detail and enter loading state in `selectEntity`. Return `null` from
`AssetDetailPanel` when neither loading nor detail is present. On close, clear the
ID, detail, loading state, and detail feedback. On fetch failure, clear selection
so the full-width grid is restored.

- [ ] **Step 4: Contain and polish card styling**

Set the default layout to one column and add the detail column only for
`.is-detail-open`. Update the card rules to:

```css
.v2-asset-entity-card.v2-asset-discover-card {
  position: relative;
  display: block;
  min-height: 220px;
  aspect-ratio: 1 / 1;
  isolation: isolate;
  overflow: hidden;
  border: 0;
  background: rgba(32, 34, 53, 0.12);
  color: white;
}

.v2-asset-library-layout.is-detail-open {
  grid-template-columns: minmax(0, 1fr) minmax(310px, 380px);
}
```

Use a bottom gradient and `.v2-asset-entity-card-title` matching Home Discover
typography. Remove hover scaling so a selected card cannot grow over neighboring
hit targets. Keep a visible focus ring and stable image cover behavior.

- [ ] **Step 5: Run the focused test and verify GREEN**

Run:

```bash
cd apps/web
npm run test:assets-page
```

Expected: all Assets page regression tests pass.

- [ ] **Step 6: Commit the tested implementation**

```bash
git add apps/web/package.json apps/web/package-lock.json apps/web/vitest.config.ts \
  apps/web/src/pages/AssetsPage.test.tsx apps/web/src/pages/AssetsPage.tsx \
  apps/web/src/styles.css
git commit -m "fix(web): contain and simplify asset cards"
```

---

### Task 3: Full Verification

**Files:**
- Verify: `apps/web/src/pages/AssetsPage.tsx`
- Verify: `apps/web/src/styles.css`
- Verify: `apps/web/src/pages/AssetsPage.test.tsx`

**Interfaces:**
- Consumes: the completed Assets page.
- Produces: fresh automated and browser evidence for the requested behavior.

- [ ] **Step 1: Run all focused asset checks**

Run:

```bash
cd apps/web
npm run test:assets-page
npm run test:v2-asset-library-normalizer
npm run test:v2-recommended-catalog
```

Expected: every command exits `0`.

- [ ] **Step 2: Run static verification**

Run:

```bash
cd apps/web
npm run lint:react
npm run build
```

Expected: lint reports no errors and the production build exits `0`.

- [ ] **Step 3: Verify browser interaction at desktop and mobile widths**

Using the running frontend:

- Open `/assets`.
- Confirm no empty detail panel exists before selection.
- Confirm the grid spans the content area before selection.
- Click scope/category controls and verify no card descendant intercepts them.
- Select a card and verify the detail column appears.
- Close details and verify the full-width grid returns.
- Confirm the card title is `display_name`, no internal ID is visible, and no play
  or Recommended save button exists.
- Repeat at a mobile viewport and check for horizontal overflow or overlap.

- [ ] **Step 4: Review the final diff and worktree scope**

Run:

```bash
git diff --check HEAD^
git status --short
```

Expected: only the planned frontend/test files plus the user's pre-existing
untracked root assets are present.
