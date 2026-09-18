import { expect, test, type Page } from "@playwright/test";

function model(nodeType: string, alternate = false) {
  return {
    model_ref: `mock:${nodeType}${alternate ? "-alternate" : ""}`,
    provider_id: "mock",
    provider_model_id: nodeType,
    display_name: `${alternate ? "Alternate" : "Cached"} ${nodeType} model`,
    capability: nodeType,
    capability_metadata: {},
    availability: "available",
    unavailable_reason: null,
    catalog_revision: 1,
    conformance_status: "certified",
    parameter_schema_id: "mock-parameters",
    parameter_descriptors: [{
      name: "resolution", value_type: "enum", allowed_values: ["720p", "1080p"],
      minimum: null, maximum: null, default: null,
    }],
  };
}

async function mockModels(page: Page, gate: Promise<void> = Promise.resolve()) {
  const reads: string[] = [];
  const writes: string[] = [];
  let videoDefault = "mock:video";
  await page.route("**/api/v2/**", route => route.abort());
  await page.route("**/api/v1/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/v1/models") {
      const nodeType = url.searchParams.get("node_type")!;
      reads.push(`models:${nodeType}`);
      expect(url.searchParams.get("include_unavailable")).toBe("true");
      await gate;
      await route.fulfill({ json: { items: [model(nodeType), model(nodeType, true)] } });
      return;
    }
    if (url.pathname === "/api/v1/model-defaults") {
      if (request.method() === "PATCH") {
        writes.push("defaults");
        videoDefault = request.postDataJSON().defaults.video;
      } else {
        reads.push("defaults");
      }
      await gate;
      await route.fulfill({ json: {
        defaults: { video: videoDefault, image: "mock:image" }, modes: {}, revisions: {},
      } });
      return;
    }
    await route.abort();
  });
  return { reads, writes };
}

test("reuses cached models on reopen and type switch, and refreshes after a real client defaults mutation", async ({ page }) => {
  const { reads, writes } = await mockModels(page);
  await page.goto("/tests/browser/agent-canvas-manual-prompt-mock.html?modelCache=1");
  const picker = page.getByLabel("Choose model", { exact: true });
  await expect(picker).toContainText("Cached video model");
  await expect(page.getByLabel("Resolution", { exact: true })).toBeVisible();
  expect(reads.toSorted()).toEqual(["defaults", "models:video"]);

  await page.evaluate(() => {
    document.body.dataset.sawModelLoading = "false";
    new MutationObserver(() => {
      if (document.querySelector('[aria-label="Choose model"]')?.textContent?.includes("Loading compatible models")) {
        document.body.dataset.sawModelLoading = "true";
      }
    }).observe(document.body, { subtree: true, childList: true, characterData: true });
  });

  for (let index = 0; index < 3; index++) {
    await page.getByRole("button", { name: "Close panel", exact: true }).click();
    await expect(picker).toHaveCount(0);
    await page.getByRole("button", { name: "Open video A", exact: true }).click();
    await expect(picker).toContainText("Cached video model");
    await expect(picker).toHaveAttribute("aria-disabled", "false");
  }
  await page.getByRole("button", { name: "Open video B", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Generation prompt" })).toHaveValue("video-b prompt");
  expect(reads.toSorted()).toEqual(["defaults", "models:video"]);
  await expect(page.locator("body")).toHaveAttribute("data-saw-model-loading", "false");
  await page.getByRole("button", { name: "Open image", exact: true }).click();
  await expect(picker).toContainText("Cached image model");
  await page.getByRole("button", { name: "Open video A", exact: true }).click();
  await expect(picker).toContainText("Cached video model");
  expect(reads.toSorted()).toEqual(["defaults", "models:image", "models:video"]);
  expect(writes).toEqual([]);

  await page.getByRole("button", { name: "Change default", exact: true }).click();
  await expect(picker).toContainText("Alternate video model");
  expect(reads.toSorted()).toEqual(["defaults", "defaults", "models:image", "models:video"]);
  expect(writes).toEqual(["defaults"]);
});

test("rapid reopen while initial requests are pending does not duplicate them", async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const { reads } = await mockModels(page, gate);
  try {
    await page.goto("/tests/browser/agent-canvas-manual-prompt-mock.html?modelCache=1");
    await expect.poll(() => reads.length).toBe(2);
    await expect(page.getByLabel("Choose model", { exact: true })).toContainText("Loading compatible models");
    await page.getByRole("button", { name: "Close panel", exact: true }).click();
    await page.getByRole("button", { name: "Open video A", exact: true }).click();
    expect(reads.toSorted()).toEqual(["defaults", "models:video"]);
    release();
    await expect(page.getByLabel("Choose model", { exact: true })).toContainText("Cached video model");
    expect(reads.toSorted()).toEqual(["defaults", "models:video"]);
  } finally {
    release();
  }
});
