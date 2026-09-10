import { expect, test, type Page } from "@playwright/test";

const arkImageModel = {
  model_ref: "volcengine_ark:doubao-seedream-4-0",
  provider_id: "volcengine_ark",
  provider_model_id: "doubao-seedream-4-0",
  display_name: "Doubao Seedream 4.0",
  capability: "image",
  capability_metadata: {},
  availability: "available",
  unavailable_reason: null,
  catalog_revision: 4,
  adapter_id: "ark-image-v1",
  transport_kind: "ark_image_native",
  release_tier: "default",
  conformance_status: "certified",
  accepted_input_modes: ["text_only", "native_reference_slots"],
  parameter_schema_id: "ark-image-v1",
  parameter_descriptors: [
    {
      name: "resolution",
      value_type: "enum",
      required: false,
      allowed_values: ["1024x1024", "1536x1024"],
      minimum: null,
      maximum: null,
      default: null,
    },
  ],
  reference_policy: {
    modes: [
      {
        mode: "native_reference_slots",
        max_references: 2,
        allowed_roles: ["product", "scene"],
      },
    ],
    max_images: 2,
  },
};

const openAiImageModel = {
  ...arkImageModel,
  model_ref: "openai:gpt-image-2",
  provider_id: "openai",
  provider_model_id: "gpt-image-2",
  display_name: "GPT Image 2",
  adapter_id: "openai-image-v1",
  transport_kind: "openai_images_native",
  release_tier: "optional",
  conformance_status: "unverified",
};

const retiredArkTextModel = {
  ...arkImageModel,
  model_ref: "volcengine_ark:doubao-seed-2-0-mini-260428",
  provider_model_id: "doubao-seed-2-0-mini-260428",
  display_name: "Doubao Seed 2.0 Mini",
  capability: "text",
  adapter_id: "ark-text-v1",
  transport_kind: "litellm_chat",
  conformance_status: "compatible",
};

function provider(providerId: string, displayName: string) {
  return {
    provider_id: providerId,
    display_name: displayName,
    capabilities: ["image"],
    connection_state: "unconfigured",
    credentials: {
      image: {
        configured: false,
        fingerprint: null,
        source: "unconfigured",
        test_capability: "unsupported",
      },
    },
    credential_revision: 1,
    updated_at: null,
  };
}

async function installRoutes(page: Page) {
  const providerMutations: string[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (route.request().method() !== "GET") providerMutations.push(`${route.request().method()} ${url.pathname}`);

    if (url.pathname === "/api/v1/health") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "ok", service: "AdCraft", version: "test", mode: "mock" }),
      });
      return;
    }

    if (url.pathname === "/api/v1/providers") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [
            provider("volcengine_ark", "Volcengine Ark"),
            provider("openai", "OpenAI"),
            provider("litellm", "LiteLLM"),
          ],
        }),
      });
      return;
    }

    if (url.pathname === "/api/v1/model-defaults") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          defaults: { image: arkImageModel.model_ref, text: retiredArkTextModel.model_ref },
          modes: {},
          revisions: { image: 1, text: 1 },
        }),
      });
      return;
    }

    if (url.pathname === "/api/v1/models") {
      const providerId = url.searchParams.get("provider");
      const purpose = url.searchParams.get("purpose");
      let items = [arkImageModel, openAiImageModel, retiredArkTextModel];
      if (providerId) items = items.filter((model) => model.provider_id === providerId);
      if (purpose) items = items.filter((model) => model.capability === purpose);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items }),
      });
      return;
    }

    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ code: "mock_route_not_found", message: url.pathname }),
    });
  });
  return { providerMutations };
}

test("uses backend model eligibility on API Space without exposing transport providers", async ({ page }) => {
  const requests = await installRoutes(page);
  await page.goto("/api-space");

  await expect(page.getByRole("heading", { name: "API Space" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Volcengine Ark provider settings" })).toBeVisible();
  await expect(page.getByRole("region", { name: "OpenAI provider settings" })).toBeVisible();
  await expect(page.getByRole("region", { name: "LiteLLM provider settings" })).toHaveCount(0);

  const openAi = page.getByRole("region", { name: "OpenAI provider settings" });
  await expect(openAi.getByText("0 available / 1 discovered models")).toBeVisible();

  const imageDefault = page.getByLabel("Image default model");
  await expect(imageDefault).toHaveValue(arkImageModel.model_ref);
  await expect(imageDefault.locator("option", { hasText: "Doubao Seedream 4.0" })).toHaveCount(1);
  await expect(imageDefault.locator("option", { hasText: "GPT Image 2" })).toHaveCount(0);

  const textDefault = page.getByLabel("Text default model");
  await expect(textDefault).toHaveValue("");
  await expect(textDefault.locator("option", { hasText: "Doubao Seed 2.0 Mini" })).toHaveCount(0);
  expect(requests.providerMutations).toEqual([]);
});

test("renders Agent Canvas controls from backend descriptors and reference policy", async ({ page }) => {
  const requests = await installRoutes(page);
  await page.goto("/tests/browser/agent-canvas-manual-prompt-mock.html?provider=1");

  await expect(page.getByLabel("Resolution")).toBeVisible();
  await expect(page.getByText("Native reference slots", { exact: true })).toBeVisible();
  await expect(page.getByText("Product · Scene", { exact: true })).toBeVisible();
  await expect(page.getByText("2 images maximum", { exact: true })).toBeVisible();
  expect(requests.providerMutations).toEqual([]);
});
