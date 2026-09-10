import { expect, test } from "@playwright/test";

function pickerAsset(index: number) {
  return {
    asset_id: `picker-${index}`, version_id: `version-${index}`, media_type: "image", source_type: "upload",
    display_name: `Reference ${index}`, mime_type: "image/webp", status: index === 2 ? "unavailable" : "ready",
    preview_url: "https://assets.example.test/picker.webp", media_url: "https://assets.example.test/picker.webp",
    width: 1254, height: 1254, duration_seconds: null, checksum: `image-${index}`,
  };
}

test("asset picker uses monochrome controls, stable thumbnails and a visible footer", async ({ page }) => {
  test.setTimeout(60000);
  for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }, { width: 330, height: 640 }, { width: 720, height: 430 }]) {
    await page.setViewportSize(viewport);
    await page.route("https://assets.example.test/picker.webp*", (route) => route.fulfill({ path: "public/brand/adcraft-icon.webp", contentType: "image/webp", headers: { "Access-Control-Allow-Origin": "*" } }));
    await page.route("**/api/v2/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/assets") && route.request().method() === "GET") {
        await route.fulfill({ json: { workflow_id: "workflow-manual-prompt-mock", assets: Array.from({ length: 24 }, (_, i) => pickerAsset(i + 1)) } });
      } else if (path.endsWith("/assets/mine") || path.endsWith("/assets/recommended")) {
        await route.fulfill({ json: { items: [] } });
      } else { await route.abort(); }
    });
    await page.goto("/tests/browser/agent-canvas-manual-prompt-mock.html?assetBrowser=1");
    await page.getByRole("button", { name: "Choose asset references" }).click();
    const dialog = page.getByRole("dialog", { name: "Project assets" });
    const panel = page.getByRole("region", { name: "Agent Canvas assets" });
    const first = panel.getByTestId("agent-asset-project:picker-1");
    await expect(first).toBeVisible();
    await expect.poll(() => first.locator("img").evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
    await expect(panel).toHaveCSS("background-color", "rgb(32, 32, 32)");
    await expect(dialog).toHaveCSS("backdrop-filter", "none");
    await expect(dialog).toHaveCSS("background-color", "rgba(0, 0, 0, 0.48)");
    await expect(panel.getByRole("tab", { name: "Project Assets" })).toHaveCSS("border-top-color", "rgb(163, 163, 163)");
    const add = panel.getByRole("button", { name: /Add .*reference/ });
    await expect(add).toBeDisabled();
    await first.hover();
    await expect(first).toHaveCSS("transform", "none");
    await expect(first).toHaveCSS("border-top-color", "rgb(163, 163, 163)");
    await panel.getByRole("checkbox", { name: "Select Reference 1", exact: true }).check();
    await expect(first).toHaveCSS("border-top-color", "rgb(245, 245, 245)");
    await expect(panel.getByRole("checkbox", { name: "Select Reference 2", exact: true })).toBeDisabled();
    await expect(add).toBeEnabled();
    await add.focus();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Shift+Tab");
    await expect(add).toHaveCSS("outline-color", "rgb(21, 21, 21)");
    await add.click();
    await expect(add).toBeDisabled();
    await expect(page.getByTestId("asset-browser-action")).toHaveText(JSON.stringify([{
      source: "project", assetId: "picker-1", entityId: null, versionId: "version-1", mediaType: "image", displayName: "Reference 1",
    }]));
    const body = panel.locator(".agent-asset-browser__body");
    const footer = panel.locator("footer");
    const footerBefore = (await footer.boundingBox())!;
    await body.evaluate((el) => { el.scrollTop = el.scrollHeight; });
    expect(await body.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
    expect(await footer.boundingBox()).toEqual(footerBefore);
    const bounds = (await panel.boundingBox())!;
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(viewport.width);
    expect(bounds.y + bounds.height).toBeLessThanOrEqual(viewport.height);
    expect(footerBefore.y + footerBefore.height).toBeLessThanOrEqual(bounds.y + bounds.height);
    expect(await panel.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
    const close = dialog.getByRole("button", { name: "Close assets" });
    const cb = (await close.boundingBox())!;
    expect(cb.y + cb.height).toBeLessThanOrEqual(bounds.y);
    await body.evaluate((el) => { el.scrollTop = 0; });
    await page.screenshot({ path: `/tmp/adcraft-asset-picker-${viewport.width}-${viewport.height}.png` });
    const search = panel.getByRole("searchbox");
    await search.focus();
    await expect(search).toHaveCSS("outline-color", "rgb(245, 245, 245)");
    await search.fill("no-match");
    await expect(panel.getByText("No matching assets")).toBeVisible();
    await search.fill("");
    await panel.getByRole("tab", { name: "My Assets" }).click();
    await expect(panel.getByText("No saved images")).toBeVisible();
    await expect(panel.getByLabel("Upload project media")).toHaveCount(0);
    await panel.getByRole("tab", { name: "Recommended" }).click();
    await expect(panel.getByText("No recommended images")).toBeVisible();
    await close.click();
    await expect(dialog).toHaveCount(0);
    await page.unrouteAll();
  }
});

test("asset picker loading, errors and upload remain usable with a pinned footer", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 640 });
  await page.route("https://assets.example.test/picker.webp*", (route) => route.fulfill({ path: "public/brand/adcraft-icon.webp", contentType: "image/webp", headers: { "Access-Control-Allow-Origin": "*" } }));
  let listCount = 0;
  let uploads = 0;
  await page.route("**/api/v2/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/assets/upload")) {
      uploads++;
      await route.fulfill({ json: { workflow_id: "workflow-manual-prompt-mock", asset: pickerAsset(25), pending_handoff_id: null } });
    } else if (path.endsWith("/assets")) {
      listCount++;
      await new Promise((resolve) => setTimeout(resolve, 300));
      if (listCount === 1) await route.fulfill({ status: 503, json: { detail: "Assets temporarily unavailable" } });
      else await route.fulfill({ json: { workflow_id: "workflow-manual-prompt-mock", assets: uploads ? [pickerAsset(1), pickerAsset(25)] : [pickerAsset(1)] } });
    } else await route.abort();
  });
  await page.goto("/tests/browser/agent-canvas-manual-prompt-mock.html?assetBrowser=error");
  await page.getByRole("button", { name: "Choose asset references" }).click();
  const panel = page.getByRole("region", { name: "Agent Canvas assets" });
  await expect(panel.getByRole("status")).toContainText("Loading assets");
  await expect(panel.getByRole("button", { name: "Retry loading assets" })).toBeVisible();
  await panel.getByRole("button", { name: "Retry loading assets" }).click();
  await panel.getByRole("checkbox", { name: "Select Reference 1" }).check();
  await panel.getByRole("button", { name: "Add 1 reference", exact: true }).click();
  await expect(panel.getByRole("alert")).toContainText("Unable to attach this reference");
  await expect(panel.getByRole("checkbox", { name: "Select Reference 1" })).toBeChecked();
  await expect(panel.getByRole("button", { name: "Add 1 reference", exact: true })).toBeInViewport();
  await panel.getByLabel("Upload project media").setInputFiles({ name: "reference.png", mimeType: "image/png", buffer: Buffer.from("mock image") });
  await expect.poll(() => uploads).toBe(1);
  await expect(panel.getByText("Reference 25", { exact: true })).toBeVisible();
  await page.screenshot({ path: "/tmp/adcraft-asset-picker-error.png" });
});

test("unifies Text and World Setting panel bounds, references and monochrome model menus", async ({ page }) => {
  test.setTimeout(60000);
  for (const width of [1280, 390, 330]) {
    await page.setViewportSize({ width, height: 900 });
    for (const kind of ["draft", "failed", "ready", "world"]) {
      const count = kind === "draft" ? 0 : kind === "ready" ? 1 : 12;
      await page.goto(`/tests/browser/agent-canvas-manual-prompt-mock.html?textPanel=${kind}&references=${count}&preparation=failed`);
      const panel = page.getByRole("region", { name: "text node workbench" });
      const editor = panel.getByRole("textbox");
      const footer = panel.locator("footer");
      const action = footer.locator(".agent-node-workbench__run");
      await expect(action.locator("svg path").first()).toHaveAttribute("d", /^M5 4\.5/);
      await expect(action).toHaveCSS("background-color", "rgb(245, 245, 245)");
      const checkBounds = async () => {
        const p = (await panel.boundingBox())!;
        const f = (await footer.boundingBox())!;
        const b = (await action.boundingBox())!;
        const e = (await editor.boundingBox())!;
        expect(p.height).toBe(217);
        expect(p.y + p.height - f.y - f.height).toBe(13);
        expect(p.x + p.width - b.x - b.width).toBe(13);
        expect(e.height).toBeGreaterThan(40);
        expect(e.y + e.height).toBeLessThanOrEqual(f.y);
        expect(await panel.evaluate((el) => el.scrollHeight <= el.clientHeight + 1 && el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      };
      await checkBounds();
      await expect(panel.locator(".agent-node-workbench__prompt-preparation, .agent-node-workbench__prompt-saved, .agent-node-workbench__model-resolution")).toHaveCount(0);
      if (kind === "world") {
        await expect(panel.getByLabel("Choose model")).toHaveCount(0);
      } else {
        const trigger = panel.getByLabel("Choose model");
        await expect(trigger).toHaveText("Default model · Text generation model");
        await expect(trigger).toHaveCSS("border-top-color", "rgba(0, 0, 0, 0)");
        await trigger.click();
        const menu = page.getByRole("listbox");
        await expect(menu).toHaveClass(/model-menu--monochrome/);
        await expect(menu.locator("small")).toHaveCount(0);
        await expect(menu.getByRole("option", { name: "Unverified text model", exact: true })).toBeDisabled();
        const m = (await menu.boundingBox())!;
        expect(m.x).toBeGreaterThanOrEqual(0);
        expect(m.x + m.width).toBeLessThanOrEqual(width);
        await page.screenshot({ path: `/tmp/adcraft-text-menu-${width}-${kind}.png` });
        await trigger.click();
      }
      if (count) {
        const list = panel.locator(".agent-node-workbench__reference-list");
        await expect(panel.getByRole("img")).toHaveCount(count);
        await list.evaluate((el) => { el.scrollLeft = el.scrollWidth; });
        await panel.getByRole("button", { name: `Remove Reference ${count} reference` }).click();
        await expect(panel.getByRole("img")).toHaveCount(count - 1);
        await checkBounds();
      }
      await editor.fill(Array.from({ length: 40 }, (_, i) => `Text content line ${i + 1}`).join("\n"));
      await editor.evaluate((el) => { el.scrollTop = 0; });
      await editor.hover();
      await page.mouse.wheel(0, 120);
      await expect.poll(() => editor.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
      await checkBounds();
      expect(await page.evaluate(() => window.scrollY)).toBe(0);
      await page.screenshot({ path: `/tmp/adcraft-fixed-text-panel-${width}-${kind}.png` });
    }
  }
});

test("Text save icons preserve generation flush and structured-content save authority", async ({ page }) => {
  for (const kind of ["draft", "failed", "ready", "world"]) {
    await page.goto(`/tests/browser/agent-canvas-manual-prompt-mock.html?textPanel=${kind}`);
    const panel = page.getByRole("region", { name: "text node workbench" });
    await panel.getByRole("textbox").fill("Updated text");
    await panel.locator(".agent-node-workbench__run").click();
    const events = page.getByTestId("manual-prompt-events");
    await expect(events).toContainText("patch-complete");
    if (kind === "draft" || kind === "failed") {
      await expect(events).toHaveText("patch-start:Updated text|patch-complete|run:Updated text");
    } else {
      await expect(events).toHaveText("patch-start:undefined|patch-complete");
      await expect(page.getByTestId("text-panel-content")).toHaveText(JSON.stringify({ content: "Updated text", retained_field: "keep" }));
    }
    await expect(panel.locator(".agent-node-workbench__prompt-saved")).toHaveCount(0);
  }
});

test("keeps every image prompt panel fixed with a bottom footer and no parameter or status rows", async ({ page }) => {
  for (const width of [1280, 390, 330]) {
    await page.setViewportSize({ width, height: 900 });
    for (const count of [0, 1, 12]) {
      await page.goto(`/tests/browser/agent-canvas-manual-prompt-mock.html?provider=1&references=${count}${count ? "&preparation=failed" : ""}`);
      const panel = page.getByRole("region", { name: "image node workbench" });
      const editor = page.getByLabel("Generation prompt");
      const footer = panel.locator("footer");
      const checkBounds = async () => {
        const p = (await panel.boundingBox())!;
        const f = (await footer.boundingBox())!;
        const e = (await editor.boundingBox())!;
        expect(p.height).toBe(217);
        expect(p.y + p.height - f.y - f.height).toBe(13);
        expect(e.height).toBeGreaterThan(40);
        expect(e.y + e.height).toBeLessThanOrEqual(f.y);
        expect(await panel.evaluate((el) => el.scrollHeight <= el.clientHeight + 1 && el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      };
      await checkBounds();
      await expect(panel.locator(".agent-node-workbench__model-parameters")).toHaveCount(0);
      await expect(panel.locator(".agent-node-workbench__prompt-preparation, .agent-node-workbench__prompt-saved, .agent-node-workbench__model-resolution")).toHaveCount(0);
      await expect(panel.getByLabel("Resolution", { exact: true })).toHaveCount(0);
      if (count) {
        const refs = panel.getByRole("region", { name: "Node references" });
        await expect(refs.getByRole("img")).toHaveCount(count);
        await expect.poll(() => refs.getByRole("img").first().evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
        const list = refs.locator(".agent-node-workbench__reference-list");
        await list.evaluate((el) => { el.scrollLeft = el.scrollWidth; });
        const remove = refs.getByRole("button", { name: `Remove Reference ${count} reference` });
        const rb = (await remove.boundingBox())!;
        const lb = (await list.boundingBox())!;
        expect(rb.y).toBeGreaterThanOrEqual(lb.y);
        expect(rb.x + rb.width).toBeLessThanOrEqual(lb.x + lb.width);
        await remove.click();
        await expect(refs.getByRole("img")).toHaveCount(count - 1);
        await checkBounds();
      }
      await editor.fill(Array.from({ length: 40 }, (_, i) => `Image prompt line ${i + 1}`).join("\n"));
      await editor.evaluate((el) => { el.scrollTop = 0; });
      await editor.hover();
      await page.mouse.wheel(0, 120);
      await expect.poll(() => editor.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
      await checkBounds();
      await page.screenshot({ path: `/tmp/adcraft-fixed-image-panel-${width}-${count}.png` });
    }
  }
});

test("keeps the video audio icon beside Run with typed support and exact submitted state", async ({ page }) => {
  for (const width of [1280, 390, 330]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/tests/browser/agent-canvas-manual-prompt-mock.html?audioToggle=off");
    const toggle = page.getByRole("button", { name: "Generate audio", exact: true });
    const run = page.getByRole("button", { name: "Run video node" });
    const ratio = page.locator("footer").getByLabel("Aspect ratio");
    await expect(page.getByRole("checkbox", { name: "Generate audio" })).toHaveCount(0);
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("video-toolbar-parameters")).toHaveText("null");
    const initial = (await toggle.boundingBox())!;
    const r = (await run.boundingBox())!;
    const p = (await ratio.boundingBox())!;
    expect(initial.width).toBe(32);
    expect(initial.height).toBe(32);
    expect(initial.x + initial.width + 8).toBeCloseTo(r.x, 0);
    expect(initial.y + initial.height / 2).toBeCloseTo(r.y + r.height / 2, 0);
    if (width > 600) {
      expect(initial.x).toBeGreaterThanOrEqual(p.x + p.width);
      expect(Math.abs(initial.y + initial.height / 2 - p.y - p.height / 2)).toBeLessThan(2);
    } else {
      expect(initial.y).toBeGreaterThanOrEqual(p.y + p.height);
    }
    const icon = toggle.locator(".agent-node-workbench__audio-icon");
    const renderedIcon = await icon.evaluate(async (element) => {
      const iconUrl = getComputedStyle(element).maskImage.slice(5, -2);
      const image = new Image();
      image.src = iconUrl;
      await image.decode();
      const svg = new DOMParser().parseFromString(await (await fetch(iconUrl)).text(), "image/svg+xml");
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 48;
      const context = canvas.getContext("2d")!;
      context.drawImage(image, 0, 0, 48, 48);
      const pixels = context.getImageData(0, 0, 48, 48).data;
      return { viewBox: svg.documentElement.getAttribute("viewBox"), nonblank: pixels.some((value, index) => index % 4 === 3 && value > 0) };
    });
    expect(renderedIcon).toEqual({ viewBox: "0 0 48 48", nonblank: true });
    await toggle.hover();
    await expect(page.getByRole("tooltip")).toHaveText("开启视频音频生成");
    await toggle.focus();
    await page.keyboard.press("Space");
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(await toggle.boundingBox()).toEqual(initial);
    await expect(toggle).toHaveCSS("color", "rgb(245, 245, 245)");
    await expect(toggle).toHaveCSS("border-top-color", "rgb(163, 163, 163)");
    await page.getByLabel("Choose model").click();
    await page.getByRole("option", { name: "Silent model", exact: true }).click();
    await expect(toggle).toBeDisabled();
    await expect(toggle).toHaveCSS("color", "rgb(112, 112, 112)");
    await toggle.locator("..").hover();
    await expect(page.getByRole("tooltip")).toHaveText("当前模型不支持生成音频");
    await toggle.evaluate((element) => (element as HTMLButtonElement).click());
    await expect(page.getByTestId("video-toolbar-parameters")).toHaveText("null");
    await page.getByLabel("Choose model").click();
    await page.getByRole("option", { name: "Video toolbar model", exact: true }).click();
    await expect(toggle).toBeEnabled();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await page.mouse.move(0, 0);
    await page.screenshot({ path: `/tmp/adcraft-video-audio-toggle-${width}.png` });
    await run.click();
    await expect(toggle).toBeDisabled();
    await expect(page.getByTestId("video-toolbar-parameters")).toHaveText(
      JSON.stringify({ duration_seconds: 8, resolution: "1080p", aspect_ratio: "16:9", generate_audio: true }),
    );
    const panel = page.getByRole("region", { name: "video node workbench" });
    expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  }
  await page.goto("/tests/browser/agent-canvas-manual-prompt-mock.html?audioToggle=on");
  await expect(page.getByRole("button", { name: "Generate audio" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("video-toolbar-parameters")).toHaveText("null");
});

test("keeps a manually created Video workbench at 217px with its controls pinned to the bottom", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/tests/browser/agent-canvas-manual-prompt-mock.html?manualVideo=1");

  const panel = page.getByRole("region", { name: "video node workbench" });
  const editor = panel.getByRole("textbox", { name: "Generation prompt" });
  const footer = panel.locator("footer");
  const asset = panel.getByRole("button", { name: "Choose asset references" });
  const model = panel.getByLabel("Choose model");
  const panelBounds = (await panel.boundingBox())!;
  const editorBounds = (await editor.boundingBox())!;
  const footerBounds = (await footer.boundingBox())!;
  const assetBounds = (await asset.boundingBox())!;
  const modelBounds = (await model.boundingBox())!;

  expect(panelBounds.height).toBeCloseTo(217, 0);
  expect(panelBounds.y + panelBounds.height - footerBounds.y - footerBounds.height).toBeCloseTo(13, 0);
  expect(editorBounds.height).toBeGreaterThan(88);
  expect(Math.abs(assetBounds.y + assetBounds.height / 2 - modelBounds.y - modelBounds.height / 2)).toBeLessThan(2);
  expect(await panel.evaluate((element) => element.scrollHeight <= element.clientHeight + 1)).toBe(true);
  await expect(panel.locator(".agent-node-workbench__prompt-preparation")).toHaveCount(0);
});

test("reuses image menu styling for video controls without clipping", async ({ page }) => {
  for (const width of [1280, 390, 330]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/tests/browser/agent-canvas-manual-prompt-mock.html?videoToolbar=1");
    const toolbar = page.locator(".agent-node-workbench__video-toolbar");
    const duration = page.getByLabel("Duration seconds");
    const resolution = toolbar.getByLabel("Resolution", { exact: true });
    const ratio = toolbar.getByLabel("Aspect ratio");
    const asset = page.getByRole("button", { name: "Choose asset references" });
    const run = page.getByRole("button", { name: "Run video node" });
    const assetBox = (await asset.boundingBox())!;
    const model = page.getByLabel("Choose model");
    await expect(model).toContainText("Default model · Video toolbar model");
    const modelBox = (await model.boundingBox())!;
    expect(modelBox.x - assetBox.x - assetBox.width).toBeCloseTo(8, 0);
    expect(Math.abs(modelBox.y + modelBox.height / 2 - assetBox.y - assetBox.height / 2)).toBeLessThan(2);
    const durationBox = (await duration.boundingBox())!;
    if (width > 600) {
      expect(Math.abs(durationBox.y + durationBox.height / 2 - assetBox.y - assetBox.height / 2)).toBeLessThan(2);
    } else {
      expect(durationBox.y).toBeGreaterThanOrEqual(modelBox.y + modelBox.height);
    }
    let previousRight = width > 600 ? modelBox.x + modelBox.width : durationBox.x - 1;
    for (const control of [duration, resolution, ratio]) {
      await expect(control).toHaveCount(1);
      const box = (await control.boundingBox())!;
      expect(Math.abs(box.y + box.height / 2 - durationBox.y - durationBox.height / 2)).toBeLessThan(2);
      expect(box.x).toBeGreaterThan(previousRight);
      expect(box.x + box.width).toBeLessThanOrEqual(width);
      previousRight = box.x + box.width;
    }
    await expect(toolbar.getByLabel("Audio mode")).toHaveCount(0);
    await duration.fill("8");
    await expect(duration).toHaveCSS("border-top-color", "rgb(163, 163, 163)");
    await expect(duration).toHaveCSS("box-shadow", "none");
    await expect(duration).toHaveCSS("outline-style", "none");
    for (const [trigger, label, value] of [[resolution, "Resolution", "1080p"], [ratio, "Aspect ratio", "9:16"]] as const) {
      expect(await trigger.locator(":scope > span").first().evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
      await expect(trigger).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
      await trigger.click();
      await expect(trigger).toHaveCSS("border-top-color", "rgb(163, 163, 163)");
      const menu = page.getByRole("listbox", { name: label, exact: true });
      await expect(menu).toHaveCSS("background-color", "rgb(32, 32, 32)");
      await expect(menu.locator("small, em")).toHaveCount(0);
      const bounds = (await menu.boundingBox())!;
      expect(bounds.x).toBeGreaterThanOrEqual(12);
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(width - 12);
      await page.screenshot({ path: `/tmp/adcraft-video-${label.replaceAll(" ", "-")}-menu-${width}.png` });
      await menu.getByRole("option", { name: value, exact: true }).click();
      await expect(trigger).toContainText(value);
      await expect(menu).toHaveCount(0);
    }
    await model.click();
    const modelMenu = page.getByRole("listbox", { name: "Compatible models" });
    await expect(modelMenu).toHaveCSS("background-color", "rgb(32, 32, 32)");
    await expect(modelMenu.locator("small, em")).toHaveCount(0);
    await expect(model).toHaveCSS("border-top-color", "rgb(163, 163, 163)");
    await page.keyboard.press("Escape");
    await expect(model).toBeFocused();
    await resolution.focus();
    await page.keyboard.press("Enter");
    await page.keyboard.press("End");
    await expect(page.getByRole("option", { name: "1080p", exact: true })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(resolution).toBeFocused();
    await page.screenshot({ path: `/tmp/adcraft-video-parameter-toolbar-${width}.png` });
    await duration.fill("16");
    await expect(page.getByText("Enter 15 or less.")).toBeVisible();
    await expect(run).toBeDisabled();
    await duration.fill("8");
    await expect(run).toBeEnabled();
    await run.click();
    await expect(page.getByTestId("video-toolbar-parameters")).toHaveText(
      JSON.stringify({ audio_mode: "native", duration_seconds: 8, resolution: "1080p", aspect_ratio: "9:16" }),
    );
    await expect(page.getByTestId("manual-prompt-events")).toContainText("run:");
    const panel = page.getByRole("region", { name: "video node workbench" });
    expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  }
});

test("places the image model beside assets with a monochrome menu across viewport sizes", async ({ page }) => {
  for (const width of [1280, 390, 330]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/tests/browser/agent-canvas-manual-prompt-mock.html?provider=1&modelMenu=1");
    const asset = page.getByRole("button", { name: "Choose asset references" });
    const trigger = page.getByLabel("Choose model");
    const run = page.getByRole("button", { name: "Run image node" });
    const checkLayout = async () => {
      const a = (await asset.boundingBox())!;
      const m = (await trigger.boundingBox())!;
      const r = (await run.boundingBox())!;
      expect(m.x - (a.x + a.width)).toBeCloseTo(8, 0);
      expect(Math.abs(m.y + m.height / 2 - a.y - a.height / 2)).toBeLessThan(2);
      expect(m.x + m.width).toBeLessThanOrEqual(r.x);
      expect(r.x + r.width).toBeLessThanOrEqual(width);
      const chevron = (await trigger.locator(".agent-node-workbench__model-chevron").boundingBox())!;
      expect(chevron.width).toBe(14);
      expect(chevron.height).toBe(16);
      expect(m.x + m.width - chevron.x - chevron.width).toBeCloseTo(10, 0);
      const label = (await trigger.locator(":scope > span").first().boundingBox())!;
      expect(label.x + label.width).toBeLessThanOrEqual(chevron.x);
    };
    await checkLayout();
    await page.mouse.move(0, 0);
    const restingBox = await trigger.boundingBox();
    const arrow = trigger.locator(".agent-node-workbench__model-chevron svg");
    await expect(arrow).toHaveCount(1);
    await expect(arrow.locator("path")).toHaveAttribute("d", "m7 14.5 5-5 5 5");
    await expect(trigger).toHaveCSS("color", "rgb(245, 245, 245)");
    await expect(trigger).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
    await expect(trigger).toHaveCSS("border-top-color", "rgba(0, 0, 0, 0)");
    await expect(trigger).toHaveCSS("border-top-width", "1px");
    await page.screenshot({ path: `/tmp/adcraft-image-model-trigger-rest-${width}.png` });
    await trigger.hover();
    await expect(trigger).toHaveCSS("border-top-color", "rgb(163, 163, 163)");
    await expect(trigger).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
    expect(await trigger.boundingBox()).toEqual(restingBox);
    await page.mouse.down();
    await expect(trigger).toHaveCSS("border-top-color", "rgb(163, 163, 163)");
    await page.mouse.up();
    await page.mouse.move(0, 0);
    const menu = page.getByRole("listbox", { name: "Compatible models" });
    await expect(menu).toBeVisible();
    await expect(arrow).toHaveCount(1);
    await expect(arrow.locator("path")).toHaveAttribute("d", "m7 9.5 5 5 5-5");
    await expect(trigger).toHaveCSS("border-top-color", "rgb(163, 163, 163)");
    await expect(trigger).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
    expect(await trigger.boundingBox()).toEqual(restingBox);
    await expect(menu.locator("small, em")).toHaveCount(0);
    await expect(menu.getByRole("option")).toHaveText([
      "Default model · Studio Image Model With A Long Descriptive Display Name",
      "Studio Image Model With A Long Descriptive Display Name",
      "Unverified image model",
    ]);
    await expect(menu).toHaveCSS("background-color", "rgb(32, 32, 32)");
    await expect(menu).toHaveCSS("color-scheme", "dark");
    await expect(menu.getByRole("option", { name: /Unverified image model/ })).toBeDisabled();
    const defaultOption = menu.getByRole("option", { name: /^Default model/ });
    await expect(defaultOption).toHaveAttribute("aria-selected", "true");
    await expect(defaultOption).toHaveCSS("background-color", "rgb(41, 41, 41)");
    const menuBox = (await menu.boundingBox())!;
    expect(menuBox.x).toBeGreaterThanOrEqual(12);
    expect(menuBox.x + menuBox.width).toBeLessThanOrEqual(width - 12);
    expect(await menu.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    await page.screenshot({ path: `/tmp/adcraft-image-model-menu-${width}.png` });
    await menu.getByRole("option", { name: /^Studio Image Model/ }).click();
    await expect(menu).toHaveCount(0);
    await expect(trigger).toContainText("Studio Image Model");
    await checkLayout();
    await trigger.focus();
    await page.keyboard.press("Enter");
    await expect(menu).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);
    await expect(trigger).toBeFocused();
    await expect(arrow).toHaveCount(1);
    await expect(arrow.locator("path")).toHaveAttribute("d", "m7 14.5 5-5 5 5");
    await expect(trigger).toHaveCSS("outline-color", "rgb(245, 245, 245)");
    await expect(trigger).toHaveCSS("outline-style", "solid");
    await page.getByLabel("Generation prompt").click();
    await expect(trigger).toHaveCSS("border-top-color", "rgba(0, 0, 0, 0)");
  }
});

test("scrolls long prompt text without scrolling or clipping the outer workbench", async ({ page }) => {
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/tests/browser/agent-canvas-manual-prompt-mock.html?preparation=queued");
    const panel = page.getByRole("region", { name: "image node workbench" });
    const editor = page.getByLabel("Generation prompt");
    await editor.fill(Array.from({ length: 40 }, (_, i) => `Prompt line ${i + 1}`).join("\n"));
    await editor.evaluate((element) => { element.scrollTop = 0; });
    await editor.hover();
    await page.mouse.wheel(0, 120);
    await expect.poll(() => editor.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
    expect(await panel.evaluate((element) => ({
      overflow: getComputedStyle(element).overflowY,
      scrollTop: element.scrollTop,
      contentFits: element.scrollHeight <= element.clientHeight + 1,
    }))).toEqual({ overflow: "visible", scrollTop: 0, contentFits: true });

    const panelBox = await panel.boundingBox();
    const runBox = await page.getByRole("button", { name: "Run image node" }).boundingBox();
    expect(panelBox).not.toBeNull();
    expect(runBox).not.toBeNull();
    expect(runBox!.y + runBox!.height).toBeLessThanOrEqual(panelBox!.y + panelBox!.height);
    await page.screenshot({ path: `/tmp/adcraft-prompt-scroll-${width}.png` });
  }
});

test("keeps a manually created blank prompt quiet and runs only after its autosave completes", async ({ page }) => {
  await page.goto("/tests/browser/agent-canvas-manual-prompt-mock.html");

  const editor = page.getByLabel("Generation prompt");
  await expect(editor).toBeVisible();
  await expect(page.getByText("Prompt input needed")).toHaveCount(0);
  await expect(page.getByText("Enter a prompt to continue.")).toHaveCount(0);
  await expect(page.getByRole("alert")).toHaveCount(0);

  await editor.fill("A clean studio product shot");
  await page.getByRole("button", { name: "Run image node" }).click();

  await expect.poll(async () => page.getByTestId("manual-prompt-events").textContent()).toContain("patch-start:A clean studio product shot");
  await expect(page.getByTestId("manual-prompt-events")).not.toContainText("run:");
  await expect(page.getByTestId("manual-prompt-events")).toContainText("patch-complete|run:A clean studio product shot");
  await expect(page.getByText(/Prompt ready/)).toHaveCount(0);
});

test("keeps a non-empty prompt editable while preparation is not ready", async ({ page }) => {
  for (const preparation of ["queued", "failed", "superseded"] as const) {
    await page.goto(`/tests/browser/agent-canvas-manual-prompt-mock.html?preparation=${preparation}`);

    const editor = page.getByLabel("Generation prompt");
    await expect(editor).toBeVisible();
    await expect(editor).toHaveValue("Existing generation prompt");
    await expect(editor).toBeEnabled();
    await expect(page.getByTestId("manual-node-status")).toHaveText("draft");
    await expect(page.getByLabel("Prompt preparation status")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Run image node" })).toBeVisible();
  }
});
