import { expect, test } from "@playwright/test";

const timestamp = "2026-08-27T00:00:00Z";

function importedNode() {
  return {
    node_id: "video-export",
    workflow_id: "workflow-1",
    node_type: "video",
    creative_role: "general_video",
    role_contract_version: "ad-media-role-v2",
    title: "Exported video",
    status: "ready",
    execution_mode: "source_only",
    summary_prompt: null,
    generation_prompt: null,
    structured_content: {},
    model_id: null,
    model_selection_mode: "default",
    model_ref: null,
    model_summary: null,
    parameters: {},
    metadata: {},
    parameter_provenance: {},
    prompt_context_snapshot_id: null,
    output_asset_id: "asset-export",
    position: { x: 900, y: 160 },
    revision: 1,
    error: null,
    prompt_preparation: null,
    variation_draft: null,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function editingNode(nodeId: string, title: string, position: { x: number; y: number }) {
  return {
    ...importedNode(),
    node_id: nodeId,
    node_type: "editing",
    creative_role: "editing",
    title,
    status: "draft",
    execution_mode: "generative",
    output_asset_id: null,
    position,
  };
}

function exportedAsset() {
  return {
    asset_id: "asset-export",
    version_id: "version-asset-export",
    project_id: "project-1",
    workflow_id: "workflow-1",
    media_type: "video",
    source_type: "editing_export",
    semantic_type: null,
    display_name: "AdCraft Final 30s",
    mime_type: "video/mp4",
    status: "ready",
    size_bytes: 1024,
    storage_key: null,
    preview_url: "/api/v2/assets/asset-export/preview.webp",
    media_url: "/api/v2/assets/asset-export/content",
    width: 1920,
    height: 1080,
    duration_seconds: 30,
    checksum: "sha256-asset-export",
    source_semantic_role: null,
    source_node_id: "editing-1",
    source_execution_id: null,
    provider: null,
    model_id: null,
    prompt_provenance: {},
    actual_media_facts: {},
    generation_provenance: {},
    quality_metadata: {},
    created_at: timestamp,
  };
}

function binding(bindingId: string, sourceNodeId: string, targetNodeId: string) {
  return {
    binding_id: bindingId,
    workflow_id: "workflow-1",
    source: { kind: "node_output", source_node_id: sourceNodeId },
    target_node_id: targetNodeId,
    input_role: "video_reference",
    required: true,
    enabled: true,
    order: 0,
    label: null,
    metadata: {},
    created_at: timestamp,
    updated_at: timestamp,
  };
}

test("exports, downloads, and imports a 30 second Editing result without creating Provider work", async ({ page }) => {
  const providerRequests: string[] = [];
  const downloadRequests: string[] = [];
  const previewRequests: string[] = [];
  const exportRequests: Array<{ headers: Record<string, string>; body: unknown }> = [];
  const importRequests: Array<{ headers: Record<string, string>; body: unknown }> = [];
  const bindingRequests: Array<{ headers: Record<string, string>; body: unknown }> = [];

  await page.route("**/api/v2/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/v2/assets/asset-export/preview.webp") {
      previewRequests.push(request.url());
    }
    if (/provider|run|execution/i.test(url.pathname)) providerRequests.push(url.pathname);

    if (url.pathname === "/api/v2/assets/asset-export/preview.webp") {
      await route.fulfill({
        status: 200,
        contentType: "image/webp",
        body: "mock-preview-bytes",
      });
      return;
    }

    if (url.pathname === "/api/v2/assets/asset-export/content" && url.searchParams.get("download") === "true") {
      downloadRequests.push("asset-export");
      await route.fulfill({
        status: 200,
        contentType: "video/mp4",
        headers: { "Content-Disposition": "attachment; filename=AdCraft-Final-30s.mp4" },
        body: "mock-mp4-bytes",
      });
      return;
    }

    if (url.pathname === "/api/v2/assets/asset-export/content") {
      await route.fulfill({
        status: 200,
        contentType: "video/mp4",
        body: "mock-mp4-bytes",
      });
      return;
    }

    if (url.pathname === "/api/v2/workflows/workflow-1/nodes/editing-1/export") {
      exportRequests.push({
        headers: request.headers(),
        body: request.postDataJSON(),
      });
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          workflow_id: "workflow-1",
          node_id: "editing-1",
          export_id: "export-30s",
          status: "queued",
          manifest_revision: 5,
          ready_video_node_ids: ["video-source"],
          skipped_inputs: [],
          bgm_node_id: "audio-source",
          events_cursor: 40,
        }),
      });
      return;
    }

    if (url.pathname === "/api/v2/workflows/workflow-1/nodes/editing-1/import-export") {
      importRequests.push({
        headers: request.headers(),
        body: request.postDataJSON(),
      });
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        headers: { ETag: '"workflow:workflow-1:revision:10"' },
        body: JSON.stringify({
          workflow_id: "workflow-1",
          revision: 10,
          layout_revision: 4,
          node: importedNode(),
          binding: binding("binding-editing-export", "editing-1", "video-export"),
          asset: exportedAsset(),
          events_cursor: 41,
          replayed: false,
        }),
      });
      return;
    }

    if (url.pathname === "/api/v2/workflows/workflow-1/bindings") {
      bindingRequests.push({
        headers: request.headers(),
        body: request.postDataJSON(),
      });
      const importBinding = binding("binding-editing-export", "editing-1", "video-export");
      const downstreamBinding = binding("binding-video-downstream", "video-export", "editing-downstream");
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        headers: { ETag: '"workflow:workflow-1:revision:11"' },
        body: JSON.stringify({
          workflow: {
            workflow_id: "workflow-1",
            project_id: "project-1",
            workflow_schema_version: 2,
            canvas_model: "agent_canvas_v1",
            revision: 11,
            layout_revision: 4,
            nodes: [
              editingNode("editing-1", "Final composition", { x: 620, y: 160 }),
              importedNode(),
              editingNode("editing-downstream", "Downstream composition", { x: 1100, y: 160 }),
            ],
            bindings: [importBinding, downstreamBinding],
            assets: [exportedAsset()],
            active_style_skill: null,
          },
          node: null,
          binding: downstreamBinding,
        }),
      });
      return;
    }

    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ code: "mock_route_not_found", message: url.pathname }),
    });
  });

  await page.goto("/tests/browser/agent-canvas-editing-mock.html");

  await expect(page.getByText("Video Track")).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "Source audio" })).toBeChecked();
  await expect(page.getByText("1 clips · 0:30")).toBeVisible();

  await page.getByRole("button", { name: "Export" }).click();
  await expect.poll(() => exportRequests.length).toBe(1);
  expect(exportRequests[0]?.body).toEqual({
    expected_manifest_revision: 5,
    availability_policy: "use_ready_inputs",
  });
  expect(exportRequests[0]?.headers["idempotency-key"]).toBeTruthy();
  await page.evaluate(() => window.dispatchEvent(new Event("mock-editing-export-completed")));
  await expect(page.getByRole("button", { name: "Download exported video" })).toBeVisible();

  await page.getByRole("button", { name: "Download exported video" }).click();
  await expect.poll(() => downloadRequests.length).toBe(1);
  expect(downloadRequests).toEqual(["asset-export"]);

  await page.getByRole("button", { name: "Add exported video to canvas" }).click();
  await expect(page.getByTestId("agent-canvas-node-video-export")).toBeVisible();
  const importedNodeCard = page.getByTestId("agent-canvas-node-video-export");
  await expect(importedNodeCard.locator("video")).toHaveCount(0);
  await expect.poll(() => previewRequests.length).toBe(1);
  expect(new URL(previewRequests[0]).searchParams.get("v")).toBe("version-asset-export");
  await expect(page.getByTestId("import-binding")).toContainText("node_output:video-export");
  const importedWorkbench = page.getByTestId("imported-workbench");
  await expect(importedWorkbench.locator("button, input, select, textarea")).toHaveCount(0);

  await page.getByRole("button", { name: "Play video output" }).click();
  await expect(page.getByLabel("Imported source-only video preview")).toBeVisible();

  await page.getByRole("button", { name: "Connect imported video downstream" }).click();
  await expect(page.getByTestId("downstream-binding")).toHaveText("binding-video-downstream");

  expect(importRequests).toHaveLength(1);
  expect(importRequests[0]?.headers["if-match"]).toBe('"workflow:workflow-1:revision:9"');
  expect(importRequests[0]?.headers["idempotency-key"]).toBe("mock-editing-export-import");
  expect(bindingRequests).toHaveLength(1);
  expect(bindingRequests[0]?.headers["if-match"]).toBe('"workflow:workflow-1:revision:10"');
  expect(bindingRequests[0]?.body).toEqual({
    source: { kind: "node_output", source_node_id: "video-export" },
    target_node_id: "editing-downstream",
    input_role: "video_reference",
    required: true,
    enabled: true,
    order: 0,
  });
  expect(providerRequests).toEqual([]);
});
