import { expect, test, type Page } from "@playwright/test";

const timestamp = "2026-08-27T00:00:00Z";

type GuidedSubmitBody = {
  submission_kind: string;
  expected_interaction_revision: number;
  expected_session_revision: number;
  action: Record<string, unknown>;
};

function projectAsset(assetId: string, displayName: string) {
  return {
    asset_id: assetId,
    version_id: `version-${assetId}`,
    project_id: "project-product-source-mock",
    workflow_id: "workflow-product-source-mock",
    media_type: "image",
    source_type: "upload",
    semantic_type: "product",
    display_name: displayName,
    mime_type: "image/png",
    status: "ready",
    size_bytes: 1024,
    storage_key: null,
    preview_url: "/api/mock-product.png",
    media_url: "/api/mock-product.png",
    width: 1024,
    height: 1024,
    duration_seconds: null,
    checksum: `sha256-${assetId}`,
    source_semantic_role: "product_main",
    source_node_id: null,
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

async function installRoutes(page: Page) {
  const uploadRequests: Array<{ idempotencyKey: string | undefined; body: string | undefined }> = [];
  const submitRequests: Array<{ idempotencyKey: string | undefined; body: GuidedSubmitBody }> = [];
  const providerRequests: string[] = [];
  const advanceRequests: string[] = [];
  let uploadCount = 0;
  const uploadedAssets: ReturnType<typeof projectAsset>[] = [];

  await page.route("**/api/mock-product.png", async (route) => {
    await route.fulfill({ status: 200, contentType: "image/png", body: Buffer.from("mock-image") });
  });
  await page.route("**/api/v2/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (/provider|run|execution/i.test(url.pathname)) providerRequests.push(url.pathname);
    if (url.pathname.endsWith("/chat/guidance/advance")) advanceRequests.push(url.pathname);

    if (url.pathname === "/api/v2/workflows/workflow-product-source-mock/assets" && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          workflow_id: "workflow-product-source-mock",
          assets: [
            projectAsset("asset-existing-front", "Existing Product Front"),
            projectAsset("asset-existing-side", "Existing Product Side"),
            ...uploadedAssets,
          ],
        }),
      });
      return;
    }

    if (url.pathname === "/api/v2/workflows/workflow-product-source-mock/assets/upload" && request.method() === "POST") {
      const asset = projectAsset(`asset-uploaded-${uploadCount + 1}`, `Uploaded Product ${uploadCount + 1}`);
      const uploadBody = request.postData() ?? "";
      uploadedAssets.push(asset);
      uploadRequests.push({
        idempotencyKey: request.headers()["idempotency-key"],
        body: request.postData() ?? undefined,
      });
      uploadCount += 1;
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          workflow_id: "workflow-product-source-mock",
          asset,
          pending_handoff_id: uploadBody.includes('"input_kind":"main"')
            ? "pending-product-handoff-1"
            : null,
        }),
      });
      return;
    }

    if (url.pathname.includes("/chat/interactions/") && url.pathname.endsWith("/submit") && request.method() === "POST") {
      const body = request.postDataJSON() as GuidedSubmitBody;
      submitRequests.push({ idempotencyKey: request.headers()["idempotency-key"], body });
      const inputKind = body.action.input_kind === "multiview" ? "multiview" : "main";
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          workflow_id: "workflow-product-source-mock",
          interaction_id: body.action.question_id === "product_multiview_source"
            ? "interaction-product-multiview"
            : "interaction-product-main",
          submission_id: `submission-product-${inputKind}`,
          receipt_id: `receipt-product-${inputKind}`,
          created_node_ids: [`product-${inputKind}-source-node`],
          created_binding_ids: [],
          document_revisions: {},
          continuation_id: null,
          automatic_run_command_ids: [],
          resulting_session_revision: 8,
          events_cursor: 12,
          replayed: false,
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

  return { uploadRequests, submitRequests, providerRequests, advanceRequests };
}

test("uploads Product Main as one exact AssetVersion and exposes a Ready source-only node", async ({ page }) => {
  const requests = await installRoutes(page);
  await page.goto("/tests/browser/agent-canvas-product-source-mock.html");

  await expect(page.getByText("Choose exactly one Product main image.")).toBeVisible();
  await page.getByLabel("Upload Product source").setInputFiles({
    name: "product-main.png",
    mimeType: "image/png",
    buffer: Buffer.from("product-main"),
  });
  await page.getByRole("button", { name: "Use selected Product" }).click();

  await expect.poll(() => requests.submitRequests.length).toBe(1);
  expect(requests.uploadRequests).toHaveLength(1);
  expect(requests.uploadRequests[0]?.idempotencyKey).toMatch(/^guided-product-upload-/);
  expect(requests.submitRequests[0]?.body).toEqual({
    submission_kind: "product_source",
    expected_interaction_revision: 3,
    expected_session_revision: 7,
    action: {
      input_kind: "main",
      choice: "upload",
      handoff_mode: "apply",
      asset_versions: [{ asset_id: "asset-uploaded-1", version_id: "version-asset-uploaded-1" }],
      pending_handoff_id: "pending-product-handoff-1",
      expected_guidance_revision: 11,
      question_id: "product_main_source",
    },
  });
  expect(requests.submitRequests[0]?.idempotencyKey).toBe("mock-guided-product-main");
  const sourceOnly = page.getByTestId("source-only-product-node");
  await expect(sourceOnly).toBeVisible();
  await expect(sourceOnly.getByText("Ready", { exact: true })).toBeVisible();
  await expect(sourceOnly.getByText("execution_mode: source_only", { exact: true })).toBeVisible();
  await expect(sourceOnly.locator("button, input, select, textarea")).toHaveCount(0);
  expect(requests.providerRequests).toEqual([]);
  expect(requests.advanceRequests).toEqual([]);
});

test("preserves ordered Multiview uploads and submits once without Provider work", async ({ page }) => {
  const requests = await installRoutes(page);
  await page.goto("/tests/browser/agent-canvas-product-source-mock.html");
  await page.getByRole("button", { name: "Product Multiview" }).click();
  await page.getByLabel("Upload Product sources").setInputFiles([
    { name: "front.png", mimeType: "image/png", buffer: Buffer.from("front") },
    { name: "side.png", mimeType: "image/png", buffer: Buffer.from("side") },
  ]);
  await page.getByRole("button", { name: "Move side.png up" }).click();
  await page.getByRole("button", { name: "Use selected Product" }).click();

  await expect.poll(() => requests.submitRequests.length).toBe(1);
  expect(requests.uploadRequests).toHaveLength(2);
  expect(requests.submitRequests[0]?.body.action).toEqual({
    input_kind: "multiview",
    choice: "upload",
    handoff_mode: "apply",
    asset_versions: [
      { asset_id: "asset-uploaded-1", version_id: "version-asset-uploaded-1" },
      { asset_id: "asset-uploaded-2", version_id: "version-asset-uploaded-2" },
    ],
    pending_handoff_id: null,
    expected_guidance_revision: 11,
    question_id: "product_multiview_source",
  });
  expect(requests.submitRequests[0]?.idempotencyKey).toBe("mock-guided-product-multiview");
  expect(requests.providerRequests).toEqual([]);
  expect(requests.advanceRequests).toEqual([]);
});

test("submits Generate with empty source authority", async ({ page }) => {
  const requests = await installRoutes(page);
  await page.goto("/tests/browser/agent-canvas-product-source-mock.html");
  await page.getByRole("radio", { name: "Generate Product source" }).check();
  await page.getByRole("button", { name: "Generate Product" }).click();

  await expect.poll(() => requests.submitRequests.length).toBe(1);
  expect(requests.uploadRequests).toEqual([]);
  expect(requests.submitRequests[0]?.body.action).toEqual({
    input_kind: "main",
    choice: "generate",
    handoff_mode: "apply",
    asset_versions: [],
    pending_handoff_id: null,
    expected_guidance_revision: 11,
    question_id: "product_main_source",
  });
  expect(requests.providerRequests).toEqual([]);
  expect(requests.advanceRequests).toEqual([]);
});
