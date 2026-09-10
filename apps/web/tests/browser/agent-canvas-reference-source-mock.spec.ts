import { expect, test } from "@playwright/test";

test("loads typed reference candidates and submits exact catalog identity", async ({ page }) => {
  const candidateRequests: Array<{ kind: string | null; scope: string | null; query: string | null }> = [];
  const submitRequests: Array<{ headers: Record<string, string>; body: unknown }> = [];

  await page.route("**/api/mock-reference.png", async (route) => {
    await route.fulfill({ status: 200, contentType: "image/png", body: Buffer.from("mock-image") });
  });
  await page.route("**/api/v2/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.endsWith("/reference-candidates")) {
      candidateRequests.push({
        kind: url.searchParams.get("reference_kind"),
        scope: url.searchParams.get("scope"),
        query: url.searchParams.get("query"),
      });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          workflow_id: "workflow-reference-source-mock",
          reference_kind: "character_main",
          scope: url.searchParams.get("scope"),
          items: [{
            entity_id: "character-entity-1",
            member_id: "character-member-1",
            asset_id: "asset-character-1",
            asset_version_id: "version-character-7",
            media_type: "image",
            display_name: "Catalog Character",
            preview_url: "/api/mock-reference.png",
            content_url: "/api/mock-reference.png",
            reference_kind: "character_main",
            semantic_reference_role: "character_reference",
            reference_purpose: "identity_guidance",
            selectable: true,
          }],
          next_cursor: null,
        }),
      });
      return;
    }
    if (url.pathname.endsWith("/submit") && request.method() === "POST") {
      submitRequests.push({ headers: request.headers(), body: request.postDataJSON() });
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          workflow_id: "workflow-reference-source-mock",
          interaction_id: "interaction-reference-source-mock",
          submission_id: "submission-reference-source-mock",
          receipt_id: "receipt-reference-source-mock",
          created_node_ids: ["character-main-1"],
          created_binding_ids: ["binding-character-reference-1"],
          document_revisions: {},
          continuation_id: null,
          automatic_run_command_ids: [],
          resulting_session_revision: 13,
          events_cursor: 21,
          replayed: false,
        }),
      });
      return;
    }
    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ code: "not_found" }) });
  });

  await page.goto("/tests/browser/agent-canvas-reference-source-mock.html");
  await expect(page.getByText("Choose a Character reference image.")).toBeVisible();
  await page.getByRole("tab", { name: "Asset Library" }).click();
  await page.getByRole("tab", { name: "My Assets" }).click();
  await page.getByLabel("Search reference assets").fill("catalog");
  await expect(page.getByRole("button", { name: "Select Catalog Character" })).toBeVisible();
  await page.getByRole("button", { name: "Select Catalog Character" }).click();
  await page.getByRole("button", { name: "Use reference" }).click();

  await expect.poll(() => submitRequests.length).toBe(1);
  expect(candidateRequests.at(-1)).toEqual({ kind: "character_main", scope: "mine", query: "catalog" });
  expect(submitRequests[0]).toMatchObject({
    headers: { "idempotency-key": "mock-guided-reference-source" },
    body: {
      submission_kind: "reference_source",
      expected_interaction_revision: 4,
      expected_session_revision: 12,
      action: "use_reference",
      reference_kind: "character_main",
      source_scope: "mine",
      entity_id: "character-entity-1",
      member_id: "character-member-1",
      asset_id: "asset-character-1",
      asset_version_id: "version-character-7",
    },
  });
  await expect(page.getByTestId("submitted-request")).toContainText('"asset_version_id":"version-character-7"');
  await expect(page.getByRole("button", { name: "Accept" })).toHaveCount(0);
});
