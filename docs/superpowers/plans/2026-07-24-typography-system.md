# Typography System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a locally hosted Manrope, Instrument Serif, Noto-compatible, and JetBrains Mono type system that makes AdCraft clearer and more cohesive across product and workbench screens.

**Architecture:** Local WOFF2 assets are served from `public/fonts`, while CSS font-face declarations and root tokens own all typography choices. A contract test reads the production HTML, CSS, and font assets to prevent external font regressions, unsupported weights, or accidental hierarchy drift.

**Tech Stack:** Vite, React, CSS custom properties, Vitest, locally served WOFF2 font files.

## Global Constraints

- Use Manrope for the interface, Instrument Serif only for the Home hero, and JetBrains Mono for technical values.
- Keep Noto Sans SC, PingFang SC, and Microsoft YaHei in the CJK fallback stack without bundling a full CJK font payload.
- Remove runtime Google Fonts dependencies.
- Support only numeric weights 400, 500, 600, 700, and 800.
- Do not change page structure, colors, data flow, or interaction behavior.
- Preserve readable generic fallback fonts when local WOFF2 assets cannot load.

---

### Task 1: Typography Contract Test

**Files:**
- Modify: `apps/web/package.json`
- Create: `apps/web/src/typographySystem.test.ts`

**Interfaces:**
- Consumes: `apps/web/index.html`, `apps/web/src/styles.css`, and the local font files.
- Produces: `npm run test:typography-system`.

- [ ] **Step 1: Write the failing contract test**

Create `apps/web/src/typographySystem.test.ts` using `node:fs`, `node:path`, and Vitest. It must assert:

```ts
expect(indexHtml).not.toContain("fonts.googleapis.com");
expect(styles).toContain('url("/fonts/manrope-latin-variable.woff2")');
expect(styles).toContain('--font-ui: "Manrope"');
expect(styles).toContain('--font-brand: "Instrument Serif"');
expect(styles).toContain('--font-mono: "JetBrains Mono"');
expect(styles).toMatch(/\.page-title\s*\{[^}]*font-size:\s*clamp\(40px, 3\.4vw, 48px\)/s);
expect(styles).toMatch(/\.section-title h2\s*\{[^}]*font-size:\s*clamp\(32px, 3vw, 40px\)/s);
expect(invalidWeights).toEqual([]);
```

Assert the four WOFF2 files exist and are non-empty.

- [ ] **Step 2: Add and run the test command to verify RED**

Add:

```json
"test:typography-system": "vitest run src/typographySystem.test.ts"
```

Run:

```bash
cd apps/web
npm run test:typography-system
```

Expected: FAIL because Google Fonts are still linked, local files and tokens do not exist, headings retain oversized scales, and arbitrary font weights remain.

---

### Task 2: Local Font Assets and Token System

**Files:**
- Create: `apps/web/public/fonts/manrope-latin-variable.woff2`
- Create: `apps/web/public/fonts/instrument-serif-latin.woff2`
- Create: `apps/web/public/fonts/instrument-serif-latin-italic.woff2`
- Create: `apps/web/public/fonts/jetbrains-mono-latin-variable.woff2`
- Create: `apps/web/public/fonts/README.md`
- Modify: `apps/web/index.html`
- Modify: `apps/web/src/styles.css`

**Interfaces:**
- Consumes: Google Fonts OFL font binaries downloaded at implementation time.
- Produces: `--font-ui`, `--font-brand`, and `--font-mono` root variables, plus four local `@font-face` declarations.

- [ ] **Step 1: Add local WOFF2 assets and attribution**

Download the Latin variable files from the Google Fonts CSS responses and save them under `apps/web/public/fonts/`. Document each family, source URL, and SIL Open Font License status in `README.md`.

- [ ] **Step 2: Remove external font loading**

Delete the Google Fonts preconnect and stylesheet elements from `apps/web/index.html`.

- [ ] **Step 3: Declare local faces and font tokens**

At the beginning of `apps/web/src/styles.css`, add:

```css
@font-face {
  font-family: "Manrope";
  font-style: normal;
  font-weight: 400 800;
  font-display: swap;
  src: url("/fonts/manrope-latin-variable.woff2") format("woff2");
}
```

Add equivalent normal and italic Instrument Serif faces and a 400-700 JetBrains
Mono face. Set the root tokens to Manrope/CJK, Instrument Serif/CJK serif, and
JetBrains Mono/system mono stacks. Set `font-synthesis: none` on the document
root to prevent browser-created heavy weights.

- [ ] **Step 4: Normalize typography hierarchy**

Set `.page-title` to `clamp(40px, 3.4vw, 48px)`, `.section-title h2` to
`clamp(32px, 3vw, 40px)`, and the Home hero title to a 68px desktop maximum.
Map all arbitrary numeric weights to the approved scale:

```text
650, 720, 740, 750, 760, 780 -> 600
800, 820, 850 -> 700
900, 950 -> 800
```

Replace hard-coded system mono stacks with `var(--font-mono)`.

- [ ] **Step 5: Run the typography test to verify GREEN**

Run:

```bash
cd apps/web
npm run test:typography-system
```

Expected: PASS.

- [ ] **Step 6: Commit the tested typography system**

```bash
git add apps/web/package.json apps/web/src/typographySystem.test.ts apps/web/index.html \
  apps/web/src/styles.css apps/web/public/fonts
git commit -m "style(web): establish local typography system"
```

---

### Task 3: Product Verification

**Files:**
- Verify: `apps/web/src/styles.css`
- Verify: `apps/web/index.html`
- Verify: `apps/web/public/fonts/`

**Interfaces:**
- Consumes: the completed typography system.
- Produces: automated and browser evidence for the final visual result.

- [ ] **Step 1: Run automated frontend checks**

```bash
cd apps/web
npm run test:typography-system
npm run test:assets-page
npm run test:v2-asset-library-normalizer
npm run test:v2-recommended-catalog
npm run lint:react
npm run build
```

Expected: every command exits 0.

- [ ] **Step 2: Check local serving and visual hierarchy**

Run the frontend and inspect Home, Assets, API Space, and Workflow at desktop
and mobile widths. Confirm no request is made to Google Fonts; the four local
font files return 200; operational titles are smaller than the Home hero;
controls and card labels stay within their bounds; and API/technical values use
the mono token.

- [ ] **Step 3: Review scope before integration**

```bash
git diff --check HEAD^
git status --short
```

Expected: only typography assets, CSS, HTML, package test command, and the
focused typography test are changed.
