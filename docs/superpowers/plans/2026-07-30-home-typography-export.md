# 首页字体配置导出 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow the typography lab to download the complete current settings as a JSON file.

**Architecture:** Keep download mechanics in a small `home-typography` utility. The page owns UI state and invokes the utility with its existing `settings` record, displaying a local error message only when the browser download APIs fail. No API calls, persistence, or import parsing are added.

**Tech Stack:** React, TypeScript, Vitest, Testing Library, browser `Blob` and object URL APIs.

## Global Constraints

- Export only; do not create an import flow.
- Serialize the complete current `settings` object without JSON metadata fields.
- Do not introduce backend, database, browser persistence, or dependencies.
- The control must remain scoped to `/design-lab/home-typography`.

---

### Task 1: Add a JSON download utility

**Files:**
- Create: `apps/web/src/features/home-typography/exportTypographyConfig.ts`
- Test: `apps/web/src/features/home-typography/exportTypographyConfig.test.ts`

**Interfaces:**
- Consumes: `Record<TypographyRegionId, TypographyRegionSettings>` from `fontCatalog.ts`.
- Produces: `serializeTypographyConfig(settings): string` and `downloadTypographyConfig(settings, date?): void`.

- [ ] **Step 1: Write the failing tests**

```ts
expect(JSON.parse(serializeTypographyConfig(settings))).toEqual(settings);
downloadTypographyConfig(settings, new Date("2026-07-30T12:34:56.000Z"));
expect(downloadedFileName).toBe("adcraft-home-typography-2026-07-30.json");
expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:typography-config");
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `npm test -- --run src/features/home-typography/exportTypographyConfig.test.ts`
Expected: failure because the export utility does not exist.

- [ ] **Step 3: Implement the utility**

```ts
export function serializeTypographyConfig(settings: TypographySettings) {
  return `${JSON.stringify(settings, null, 2)}\n`;
}

export function downloadTypographyConfig(settings: TypographySettings, date = new Date()) {
  const blob = new Blob([serializeTypographyConfig(settings)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `adcraft-home-typography-${date.toISOString().slice(0, 10)}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `npm test -- --run src/features/home-typography/exportTypographyConfig.test.ts`
Expected: all serialization, file-name and object-URL cleanup assertions pass.

- [ ] **Step 5: Commit the utility**

```bash
git add apps/web/src/features/home-typography/exportTypographyConfig.ts apps/web/src/features/home-typography/exportTypographyConfig.test.ts
git commit -m "feat(web): add typography config export utility"
```

### Task 2: Add the export control and failure feedback

**Files:**
- Modify: `apps/web/src/icons.tsx`
- Modify: `apps/web/src/pages/HomeTypographyLabPage.tsx`
- Modify: `apps/web/src/pages/home-typography-lab.css`
- Modify: `apps/web/src/pages/HomeTypographyLabPage.test.tsx`

**Interfaces:**
- Consumes: `downloadTypographyConfig(settings)` from `exportTypographyConfig.ts`.
- Produces: an accessible `Export configuration` icon button that downloads current settings and a lightweight error status on failure.

- [ ] **Step 1: Write the failing page tests**

```tsx
fireEvent.click(screen.getByRole("button", { name: "Export configuration" }));
expect(downloadTypographyConfig).toHaveBeenCalledWith(expect.objectContaining({
  heroMain: expect.objectContaining({ fontId: "instrument-serif" }),
}));

downloadTypographyConfig.mockImplementation(() => { throw new Error("download unavailable"); });
fireEvent.click(screen.getByRole("button", { name: "Export configuration" }));
expect(screen.getByText("Configuration could not be exported.")).toBeTruthy();
```

- [ ] **Step 2: Run the focused page test and verify it fails**

Run: `npm test -- --run src/pages/HomeTypographyLabPage.test.tsx`
Expected: failure because no export button or error feedback exists.

- [ ] **Step 3: Implement the control**

```tsx
function exportCurrentSettings() {
  try {
    downloadTypographyConfig(settings);
    setExportStatus("");
  } catch {
    setExportStatus("Configuration could not be exported.");
  }
}

<button aria-label="Export configuration" title="Export configuration" onClick={exportCurrentSettings}>
  <DownloadIcon />
</button>
```

Use the existing icon module, title-area layout, and dark panel tokens. Render the error in an `aria-live="polite"` status element; do not change the existing font-load status semantics.

- [ ] **Step 4: Run the focused page test and verify it passes**

Run: `npm test -- --run src/pages/HomeTypographyLabPage.test.tsx`
Expected: export invocation and error message assertions pass alongside existing typography tests.

- [ ] **Step 5: Commit the page control**

```bash
git add apps/web/src/icons.tsx apps/web/src/pages/HomeTypographyLabPage.tsx apps/web/src/pages/home-typography-lab.css apps/web/src/pages/HomeTypographyLabPage.test.tsx
git commit -m "feat(web): export typography lab settings"
```

### Task 3: Verify the final feature

**Files:**
- Verify: `apps/web/src/features/home-typography/exportTypographyConfig.test.ts`
- Verify: `apps/web/src/pages/HomeTypographyLabPage.test.tsx`

- [ ] **Step 1: Run focused export tests**

Run: `npm test -- --run src/features/home-typography/exportTypographyConfig.test.ts src/pages/HomeTypographyLabPage.test.tsx`
Expected: all export and existing typography-lab tests pass.

- [ ] **Step 2: Run the complete frontend check**

Run: `npm run check`
Expected: typecheck, lint, all tests, production build and bundle budget pass.

- [ ] **Step 3: Check final diff and commit design records**

```bash
git diff --check
git add docs/superpowers/specs/2026-07-30-home-typography-export-design.md docs/superpowers/plans/2026-07-30-home-typography-export.md
git commit -m "docs: record typography export design"
```
