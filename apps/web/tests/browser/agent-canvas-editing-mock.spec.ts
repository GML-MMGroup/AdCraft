import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { CutiaSavedState } from "../../src/features/agent-canvas/editing/cutia/project";
import type { AgentCanvasWorkflowV2, ProjectAssetSummaryV2 } from "../../src/types-v2";

const mediaDir = mkdtempSync(join(tmpdir(), "adcraft-cutia-"));
test.beforeAll(() => {
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", join(mediaDir, "source.mp4")]);
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=44100", "-t", "2", join(mediaDir, "bgm.wav")]);
});

async function setup(page: Page, scenario = "short") {
  let workflow: AgentCanvasWorkflowV2;
  let output: Buffer | undefined;
  const writes: Array<{ path: string; body: Record<string, unknown> }> = [];
  await page.route("**/api/v2/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === "GET" && path.includes("/assets/") && path.endsWith("/content")) {
      const isAudio = path.includes("audio-source");
      await route.fulfill({ contentType: isAudio ? "audio/wav" : "video/mp4", body: path.includes("asset-export") && output ? output : readFileSync(join(mediaDir, isAudio ? "bgm.wav" : "source.mp4")) });
      return;
    }
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", headers: { ETag: `"workflow:workflow-1:revision:${workflow?.revision || 8}"` }, body: JSON.stringify(body) });
    if (request.method() === "GET" && path.endsWith("/assets")) return json({ workflow_id: "workflow-1", assets: workflow.assets });
    if (request.method() === "PATCH") {
      const patch = request.postDataJSON(); writes.push({ path, body: patch });
      workflow = { ...workflow, revision: workflow.revision + 1, nodes: workflow.nodes.map(node => node.node_id === "editing-1" ? { ...node, ...patch, revision: node.revision + 1 } : node) };
      return json({ workflow, node: workflow.nodes.find(node => node.node_id === "editing-1"), binding: null });
    }
    if (path.endsWith("/assets/upload")) {
      const form = await new Request("http://fixture/upload", { method: "POST", headers: { "content-type": request.headers()["content-type"] }, body: new Uint8Array(request.postDataBuffer()!).buffer }).formData();
      const file = form.get("file") as File;
      output = Buffer.from(await file.arrayBuffer());
      writes.push({ path, body: JSON.parse(String(form.get("metadata"))) });
      const asset: ProjectAssetSummaryV2 = { ...workflow.assets[0], asset_id: "asset-export", version_id: "export-v1", display_name: file.name, media_type: "video", mime_type: file.type, duration_seconds: 2, width: 320, height: 180, size_bytes: output.length, preview_url: null, media_url: "/api/v2/assets/asset-export/content" };
      workflow.assets = [...workflow.assets.filter(item => item.asset_id !== asset.asset_id), asset];
      return json({ workflow_id: "workflow-1", asset }, 201);
    }
    if (path.endsWith("/nodes") && request.method() === "POST") {
      const body = request.postDataJSON(); writes.push({ path, body });
      const node = { ...workflow.nodes[0], ...body, node_id: "video-export", output_asset_id: body.source_asset_id, status: "ready", execution_mode: "source_only", generation_prompt: null };
      delete node.source_asset_id;
      workflow = { ...workflow, revision: workflow.revision + 1, nodes: [...workflow.nodes, node] };
      return json({ workflow, node, binding: null }, 201);
    }
    if (path.endsWith("/bindings") && request.method() === "POST") {
      const body = request.postDataJSON(); writes.push({ path, body });
      const binding = { ...workflow.bindings[0], ...body, binding_id: "binding-video-downstream" };
      workflow = { ...workflow, revision: workflow.revision + 1, bindings: [...workflow.bindings, binding] };
      return json({ workflow, node: null, binding }, 201);
    }
    await route.fulfill({ status: 404, body: path });
  });
  if (process.env.CUTIA_USE_BUILD === "1") {
    await page.route("**/cutia-editor.html", route => route.fulfill({ path: join(process.cwd(), "dist/cutia-editor.html") }));
    await page.route(url => url.pathname.startsWith("/assets/"), route => route.fulfill({ path: join(process.cwd(), "dist", new URL(route.request().url()).pathname) }));
  }
  await page.goto(`/tests/browser/agent-canvas-editing-mock.html?manifest=${scenario}`);
  workflow = JSON.parse(await page.getByTestId("workflow-state").textContent() || "{}");
  const frame = page.frameLocator("iframe.cutia-editor-frame");
  return { frame, writes, getWorkflow: () => workflow, getOutput: () => output };
}

test("loads nullable legacy edits without writes and rejects malformed data", async ({ page }) => {
  const { frame, writes } = await setup(page, "nullable");
  await expect(frame.getByRole("region", { name: "Timeline", exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Export", exact: true })).toBeEnabled();
  expect(writes).toEqual([]);
  await page.goto("/tests/browser/agent-canvas-editing-mock.html?manifest=invalid");
  await expect(page.getByRole("alert")).toContainText("timeline_duration_seconds");
  await expect(page.getByRole("button", { name: "Export", exact: true })).toBeDisabled();
});

for (const format of ["mp4", "webm"] as const) test(`native ${format} edits persist across reopen, export real audio/video, download and return to canvas`, async ({ page }) => {
  test.setTimeout(120_000);
  const { frame, writes, getWorkflow, getOutput } = await setup(page);
  await expect(page.getByRole("button", { name: "Export", exact: true })).toBeEnabled();
  expect(writes).toEqual([]);
  await frame.getByRole("button", { name: "Source video", exact: true }).click();
  await frame.getByRole("slider", { name: "Timeline ruler", exact: true }).click({ position: { x: 50, y: 8 } });
  await frame.getByRole("button", { name: "Split element", exact: true }).click();
  await expect(frame.getByRole("button", { name: /^Source video \(.*\)$/ })).toHaveCount(2);
  await frame.getByRole("button", { name: "Transitions", exact: true }).click();
  await frame.getByRole("button", { name: "Dissolve", exact: false }).click();
  await expect.poll(() => {
    const state = getWorkflow().nodes.find(node => node.node_id === "editing-1")!.parameters.cutia_editor_v1 as CutiaSavedState | undefined;
    const track = state?.snapshot.project.scenes[0].tracks.find(track => track.type === "video");
    return track?.type === "video" ? track.transitions?.[0]?.type : null;
  }).toBe("dissolve");
  await frame.getByRole("slider", { name: "Timeline ruler", exact: true }).click({ position: { x: 0, y: 8 } });
  await frame.getByRole("button", { name: "Text", exact: true }).click();
  await frame.getByText("Default text", { exact: true }).hover();
  await frame.getByRole("button", { name: "Add to timeline", exact: true }).click();
  await expect.poll(() => writes.filter(write => write.path.endsWith("/editing-1")).length).toBeGreaterThan(0);
  await frame.getByRole("button", { name: "Undo", exact: true }).click();
  await frame.getByRole("button", { name: "Redo", exact: true }).click();
  await page.getByRole("button", { name: "Close editor" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const saved = getWorkflow().nodes.find(node => node.node_id === "editing-1")!.parameters.cutia_editor_v1 as CutiaSavedState;
  const videoTrack = saved.snapshot.project.scenes[0].tracks.find(track => track.type === "video")!;
  expect(videoTrack.type === "video" && videoTrack.transitions?.[0].type).toBe("dissolve");
  expect(videoTrack.elements).toHaveLength(2);
  expect(saved.snapshot.project.scenes[0].tracks.some((track) => track.type === "text" && track.elements.length)).toBe(true);
  await page.getByRole("button", { name: "Reopen editor" }).click();
  await expect(page.getByRole("button", { name: "Export", exact: true })).toBeEnabled();
  await expect(frame.getByText("Default text", { exact: true }).first()).toBeVisible();
  await page.getByRole("combobox", { name: "Format" }).selectOption(format);
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await expect(page.getByRole("button", { name: "Download exported video" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("button", { name: "Add to Canvas", exact: true })).toBeEnabled({ timeout: 60_000 });
  await page.screenshot({ path: `/tmp/adcraft-cutia-${format}.png` });
  const bytes = getOutput()!;
  expect(bytes.length).toBeGreaterThan(1000);
  const outputPath = join(mediaDir, `result.${format}`); writeFileSync(outputPath, bytes);
  const probe = JSON.parse(execFileSync("ffprobe", ["-v", "error", "-show_streams", "-show_format", "-of", "json", outputPath], { encoding: "utf8" }));
  expect(probe.streams.some((stream: { codec_type: string; width: number; height: number }) => stream.codec_type === "video" && stream.width === 320 && stream.height === 180)).toBe(true);
  expect(probe.streams.some((stream: { codec_type: string; width: number; height: number }) => stream.codec_type === "audio")).toBe(true);
  expect(Number(probe.format.duration)).toBeCloseTo(5, 0);
  const pcm = execFileSync("ffmpeg", ["-v", "error", "-i", outputPath, "-t", "1", "-f", "f32le", "-ac", "1", "-ar", "44100", "pipe:1"]);
  const amplitude = (frequency: number) => {
    let sin = 0; let cos = 0; const count = pcm.length / 4;
    for (let index = 0; index < count; index++) {
      const sample = pcm.readFloatLE(index * 4); const phase = 2 * Math.PI * frequency * index / 44100;
      sin += sample * Math.sin(phase); cos += sample * Math.cos(phase);
    }
    return 2 * Math.hypot(sin, cos) / count;
  };
  expect(amplitude(440)).toBeGreaterThan(0.02);
  expect(amplitude(880)).toBeGreaterThan(0.005);
  const textFrame = execFileSync("ffmpeg", ["-v", "error", "-ss", "3", "-i", outputPath, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]);
  expect([...textFrame].filter(value => value > 100).length).toBeGreaterThan(50);
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download exported video" }).click();
  const download = await downloadPromise;
  await download.saveAs(join(mediaDir, `download.${format}`));
  expect(readFileSync(join(mediaDir, `download.${format}`))).toEqual(bytes);
  await page.getByRole("button", { name: "Add to Canvas", exact: true }).click();
  await expect(page.getByTestId("agent-canvas-node-video-export")).toBeVisible();
  await page.getByRole("button", { name: "Connect imported video downstream" }).click();
  await expect(page.getByTestId("downstream-binding")).toHaveText("binding-video-downstream");
  expect(writes.find(write => write.path.endsWith("/nodes"))?.body.source_asset_id).toBe("asset-export");
  expect(writes.some(write => /provider|execution|import-export|\/export$/.test(write.path))).toBe(false);
  expect(writes.filter(write => write.path.endsWith("/editing-1")).every(write => !write.body.structured_content)).toBe(true);
});

test("mobile layout keeps preview and tools reachable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { frame } = await setup(page);
  await expect(page.getByRole("button", { name: "Export", exact: true })).toBeEnabled();
  await expect(frame.getByRole("button", { name: "Stickers", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Cutia", exact: true })).toHaveCount(0);
  await expect(frame.locator(".cutia-preview-pane")).toBeVisible();
  await expect(frame.locator(".cutia-media-pane")).toBeHidden();
  await frame.getByRole("button", { name: "Text", exact: true }).click();
  await expect(frame.getByText("Default text", { exact: true })).toBeVisible();
  expect(await page.locator(".cutia-editor-panel").evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.screenshot({ path: "/tmp/adcraft-cutia-mobile.png" });
});


test("imports existing project assets and local files, then restores their media references", async ({ page }) => {
  const { frame, getWorkflow, writes } = await setup(page);
  await expect(page.getByRole("button", { name: "Export", exact: true })).toBeEnabled();
  await page.getByRole("combobox", { name: "Add project media" }).selectOption("asset-extra-shot");
  await expect(frame.getByText("Extra shot", { exact: true })).toBeVisible();
  await frame.locator('input[type="file"]').setInputFiles(join(mediaDir, "source.mp4"));
  await expect.poll(() => writes.filter(write => write.path.endsWith("/assets/upload")).length).toBe(1);
  await expect(frame.getByText("source.mp4", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Close editor" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const saved = getWorkflow().nodes.find(node => node.node_id === "editing-1")!.parameters.cutia_editor_v1 as CutiaSavedState;
  expect(saved.snapshot.media.map(media => media.assetId)).toEqual(expect.arrayContaining(["asset-extra-shot", "asset-export"]));
  await page.getByRole("button", { name: "Reopen editor" }).click();
  await expect(frame.getByText("source.mp4", { exact: true })).toBeVisible();
});

test("uses the workspace Chinese locale inside the embedded editor", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("adcraft.locale", "zh-CN"));
  const { frame } = await setup(page);
  await expect(page.getByRole("button", { name: "导出视频", exact: true })).toBeEnabled();
  await expect(frame.getByRole("button", { name: "贴纸", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Cutia", exact: true })).toHaveCount(0);
  await expect(frame.getByRole("button", { name: "素材", exact: true })).toBeVisible();
  await frame.getByRole("button", { name: "文字", exact: true }).click();
  await expect(frame.locator(".cutia-media-pane")).toContainText("默认文本");
  await page.screenshot({ path: "/tmp/adcraft-cutia-chinese.png" });
});
