import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ProviderModelSummaryV1 } from "../api/providerRegistry.ts";
import { ModelDefaultsPanel } from "./api-space/ModelDefaultsPanel.tsx";
import { ProviderCredentialCard } from "./api-space/ProviderCredentialCard.tsx";
import { ApiSpacePage } from "./ApiSpacePage.tsx";

const fixture = vi.hoisted(() => ({
  api: {
    listProviders: vi.fn(),
    updateProviderCredentials: vi.fn(),
    testProviderCredential: vi.fn(),
    syncProviderModels: vi.fn(),
    listProviderModels: vi.fn(),
    getModelDefaults: vi.fn(),
    patchModelDefaults: vi.fn(),
  },
}));

vi.mock("../api/client", () => ({
  api: fixture.api,
  ApiError: class ApiError extends Error {
    status: number;
    payload: unknown;

    constructor(message: string, status: number, payload: unknown) {
      super(message);
      this.status = status;
      this.payload = payload;
    }
  },
}));

const providers = [
  provider("siliconflow", "SiliconFlow", ["text"]),
  provider("volcengine_ark", "Volcengine Ark", ["text", "image", "video"]),
  provider("tianpuyue", "Tianpuyue", ["audio"]),
];

const glm = model("siliconflow:zai-org/GLM-5.2", "SiliconFlow", "GLM-5.2", "text");
const arkText = model("volcengine_ark:doubao-seed-2-1-pro-260628", "Volcengine Ark", "Doubao Seed 2.1 Pro", "text");
const arkImage = model("volcengine_ark:doubao-seedream-4-0", "Volcengine Ark", "Doubao Seedream 4.0", "image");
const deterministicImage = model("fake:deterministic-image", "fake", "Deterministic fake", "image");
const tianpuyueAudio = model("tianpuyue:TemPolor-i3", "Tianpuyue", "TemPolor i3", "audio");
const tianpuyueLongAudio = model("tianpuyue:TemPolor-i3.5", "Tianpuyue", "TemPolor i3.5", "audio");

describe("ApiSpacePage provider registry", () => {
  beforeEach(() => {
    fixture.api.listProviders.mockResolvedValue({ items: providers });
    fixture.api.getModelDefaults.mockResolvedValue({
      defaults: { agent: glm.model_ref, text: glm.model_ref, audio: tianpuyueAudio.model_ref },
      modes: { agent: "explicit", text: "explicit", audio: "automatic" },
      revisions: { agent: 2, text: 2, audio: 2 },
    });
    fixture.api.listProviderModels.mockImplementation((query: { provider?: string; purpose?: string }) => {
      if (query.provider === "siliconflow") return Promise.resolve({ items: [glm] });
      if (query.provider === "volcengine_ark") return Promise.resolve({ items: [arkText, arkImage] });
      if (query.purpose === "agent" || query.purpose === "text") return Promise.resolve({ items: [glm, arkText] });
      if (query.purpose === "image") return Promise.resolve({ items: [arkImage, deterministicImage] });
      if (query.purpose === "audio" || query.provider === "tianpuyue") return Promise.resolve({ items: [tianpuyueAudio, tianpuyueLongAudio] });
      return Promise.resolve({ items: [] });
    });
    fixture.api.updateProviderCredentials.mockResolvedValue({
      provider: {
        ...providers[0],
        connection_state: "configured",
        credentials: {
          text: { configured: true, fingerprint: "fingerprint", source: "project_dotenv", test_capability: "minimal_request" },
        },
      },
      updated_capabilities: ["text"],
      cleared_capabilities: [],
      applied_at: "2026-08-03T04:00:00Z",
    });
    fixture.api.testProviderCredential.mockResolvedValue({
      provider_id: "siliconflow",
      capability: "text",
      accepted: true,
      model_ref: glm.model_ref,
      tested_at: "2026-08-03T04:00:00Z",
    });
    fixture.api.syncProviderModels.mockResolvedValue({
      provider_id: "siliconflow",
      sync_run_id: "sync-1",
      catalog_revision: 4,
      status: "succeeded",
    });
    fixture.api.patchModelDefaults.mockResolvedValue({
      defaults: { agent: glm.model_ref, text: glm.model_ref, audio: tianpuyueAudio.model_ref },
      modes: { agent: "explicit", text: "explicit", audio: "automatic" },
      revisions: { agent: 3, text: 3, audio: 3 },
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders backend providers as separate configuration cards", async () => {
    render(<ApiSpacePage />);

    expect(await screen.findByRole("region", { name: "SiliconFlow provider settings" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Volcengine Ark provider settings" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Tianpuyue provider settings" })).toBeTruthy();
    expect(fixture.api.listProviders).toHaveBeenCalledOnce();
    expect(screen.getByLabelText("SiliconFlow Text API Key")).toBeTruthy();
    expect(screen.getByLabelText("Volcengine Ark Image API Key")).toBeTruthy();
    expect(screen.getByLabelText("Tianpuyue Audio API Key")).toBeTruthy();
  });

  it("does not expose transport-only or test-only providers as user-configurable", async () => {
    fixture.api.listProviders.mockResolvedValueOnce({
      items: [
        ...providers,
        provider("litellm", "LiteLLM", ["text"]),
        provider("fake", "Fake", []),
      ],
    });

    render(<ApiSpacePage />);

    expect(await screen.findByRole("region", { name: "SiliconFlow provider settings" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "LiteLLM provider settings" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Fake provider settings" })).toBeNull();
  });

  it("shows OpenRouter instead of the retired official OpenAI provider", async () => {
    fixture.api.listProviders.mockResolvedValueOnce({
      items: [
        ...providers,
        openRouterProvider(),
        provider("openai", "OpenAI", ["image"]),
      ],
    });

    render(<ApiSpacePage />);

    expect(await screen.findByRole("region", { name: "OpenRouter provider settings" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "OpenAI provider settings" })).toBeNull();
  });

  it("uses one shared OpenRouter key for Text and Image while showing separate endpoints", async () => {
    const onProviderUpdated = vi.fn();
    render(
      <ProviderCredentialCard
        provider={openRouterProvider()}
        models={[]}
        onProviderUpdated={onProviderUpdated}
        onModelsUpdated={vi.fn()}
      />,
    );

    expect(screen.getByText("Text endpoint · https://openrouter.ai/api/v1")).toBeTruthy();
    expect(screen.getByText("Image endpoint · https://openrouter.ai/api/v1")).toBeTruthy();
    expect(screen.getAllByLabelText("OpenRouter API Key")).toHaveLength(1);

    fireEvent.change(screen.getByLabelText("OpenRouter API Key"), { target: { value: "  shared-key  " } });
    fireEvent.click(screen.getByRole("button", { name: "Save OpenRouter credentials" }));

    await waitFor(() => expect(fixture.api.updateProviderCredentials).toHaveBeenCalledWith("openrouter", {
      api_keys: { text: "shared-key", image: "shared-key" },
      clear_capabilities: [],
    }));
  });

  it("clears the shared OpenRouter key for Text and Image in one mutation", async () => {
    const configured = openRouterProvider(true);
    fixture.api.updateProviderCredentials.mockResolvedValueOnce({
      provider: openRouterProvider(false),
      updated_capabilities: [],
      cleared_capabilities: ["text", "image"],
      applied_at: "2026-09-04T00:00:00Z",
    });
    render(
      <ProviderCredentialCard
        provider={configured}
        models={[]}
        onProviderUpdated={vi.fn()}
        onModelsUpdated={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Clear OpenRouter key" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm clear" }));

    await waitFor(() => expect(fixture.api.updateProviderCredentials).toHaveBeenCalledWith("openrouter", {
      api_keys: {},
      clear_capabilities: ["text", "image"],
    }));
  });

  it("does not promote OpenRouter models after a successful credential probe", async () => {
    const onModelsUpdated = vi.fn();
    render(
      <ProviderCredentialCard
        provider={openRouterProvider()}
        models={[openRouterImageModel({ availability: "unavailable", conformance_status: "unverified" })]}
        onProviderUpdated={vi.fn()}
        onModelsUpdated={onModelsUpdated}
      />,
    );

    fireEvent.change(screen.getByLabelText("OpenRouter API Key"), { target: { value: "candidate" } });
    fireEvent.click(screen.getByRole("button", { name: "Test Image key" }));

    await waitFor(() => expect(fixture.api.testProviderCredential).toHaveBeenCalledWith("openrouter", {
      capability: "image",
      api_key: "candidate",
    }));
    expect(screen.getByText("Image credential accepted.")).toBeTruthy();
    expect(screen.getByText("0 available / 1 discovered models")).toBeTruthy();
    expect(onModelsUpdated).not.toHaveBeenCalled();
  });

  it("does not count an unverified expanded model as available", () => {
    render(
      <ProviderCredentialCard
        provider={provider("openai", "OpenAI", ["image"])}
        models={[{
          ...arkImage,
          model_ref: "openai:gpt-image-2",
          provider_id: "openai",
          provider_model_id: "gpt-image-2",
          display_name: "GPT Image 2",
          adapter_id: "openai-image-v1",
          transport_kind: "openai_images_native",
          conformance_status: "unverified",
        }]}
        onProviderUpdated={vi.fn()}
        onModelsUpdated={vi.fn()}
      />,
    );

    expect(screen.getByText("0 available / 1 discovered models")).toBeTruthy();
  });

  it("shows only the provider-scoped fingerprint after a successful save", async () => {
    render(<ApiSpacePage />);
    const input = await screen.findByLabelText("SiliconFlow Text API Key");

    fireEvent.change(input, { target: { value: "candidate-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Save SiliconFlow credentials" }));

    expect(await screen.findByText("Configured · fingerprint")).toBeTruthy();
    expect(screen.queryByDisplayValue("candidate-key")).toBeNull();
  });

  it("saves a SiliconFlow Text candidate through the SiliconFlow route and clears plaintext", async () => {
    render(<ApiSpacePage />);
    const input = await screen.findByLabelText("SiliconFlow Text API Key");

    fireEvent.change(input, { target: { value: "  siliconflow-candidate  " } });
    fireEvent.click(screen.getByRole("button", { name: "Save SiliconFlow credentials" }));

    await waitFor(() => expect(fixture.api.updateProviderCredentials).toHaveBeenCalledWith("siliconflow", {
      api_keys: { text: "siliconflow-candidate" },
      clear_capabilities: [],
    }));
    expect((input as HTMLInputElement).value).toBe("");
    expect(screen.getByText("SiliconFlow credentials saved.")).toBeTruthy();
  });

  it("tests a SiliconFlow candidate with the matching provider ID", async () => {
    render(<ApiSpacePage />);
    const input = await screen.findByLabelText("SiliconFlow Text API Key");
    fireEvent.change(input, { target: { value: "siliconflow-candidate" } });
    fireEvent.click(within(screen.getByRole("region", { name: "SiliconFlow provider settings" })).getByRole("button", { name: "Test Text key" }));

    await waitFor(() => expect(fixture.api.testProviderCredential).toHaveBeenCalledWith("siliconflow", {
      capability: "text",
      api_key: "siliconflow-candidate",
    }));
    expect(screen.getByText("Text credential accepted.")).toBeTruthy();
  });

  it("synchronizes a provider catalog without removing its displayed models", async () => {
    render(<ApiSpacePage />);
    const section = await screen.findByRole("region", { name: "SiliconFlow provider settings" });
    fireEvent.click(within(section).getByRole("button", { name: "Sync models" }));

    await waitFor(() => expect(fixture.api.syncProviderModels).toHaveBeenCalledWith("siliconflow"));
    await waitFor(() => expect(fixture.api.listProviderModels).toHaveBeenCalledWith({
      provider: "siliconflow",
      include_unavailable: true,
    }));
    expect(within(section).getByText("Models synchronized.")).toBeTruthy();
  });

  it("saves only changed global defaults from server-provided model options", async () => {
    render(<ApiSpacePage />);
    const textSelect = await screen.findByLabelText("Text default model");
    await waitFor(() => expect((textSelect as HTMLSelectElement).value).toBe(glm.model_ref));
    fireEvent.change(textSelect, { target: { value: arkText.model_ref } });
    const saveButton = screen.getByRole("button", { name: "Save default models" });
    await waitFor(() => expect((saveButton as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(saveButton);

    await waitFor(() => expect(fixture.api.patchModelDefaults).toHaveBeenCalledWith({
      defaults: { text: arkText.model_ref },
    }));
  });

  it("excludes fake provider models from production default selectors", async () => {
    render(<ApiSpacePage />);

    const imageSelect = await screen.findByLabelText("Image default model");
    await waitFor(() => expect(within(imageSelect).getByText("Doubao Seedream 4.0 · volcengine_ark")).toBeTruthy());
    expect(within(imageSelect).queryByText("Deterministic fake · fake")).toBeNull();
  });

  it("excludes unverified expanded and retired models from production defaults", () => {
    const unverified = {
      ...arkImage,
      model_ref: "openai:gpt-image-2",
      provider_id: "openai",
      display_name: "GPT Image 2",
      adapter_id: "openai-image-v1",
      transport_kind: "openai_images_native" as const,
      conformance_status: "unverified" as const,
    };
    render(
      <ModelDefaultsPanel
        defaults={{ defaults: {}, modes: {}, revisions: {} }}
        modelsByPurpose={{
          agent: [],
          text: [],
          image: [arkImage, unverified, deterministicImage],
          video: [],
          audio: [],
        }}
        loading={false}
        pending={false}
        notice={null}
        onSave={vi.fn()}
      />,
    );

    const imageSelect = screen.getByLabelText("Image default model");
    expect(within(imageSelect).getByText("Doubao Seedream 4.0 · volcengine_ark")).toBeTruthy();
    expect(within(imageSelect).queryByText("GPT Image 2 · openai")).toBeNull();
    expect(within(imageSelect).queryByText("Deterministic fake · fake")).toBeNull();
  });

  it("does not expose a persisted fake default as an unavailable option", async () => {
    render(
      <ModelDefaultsPanel
        defaults={{
          defaults: { image: deterministicImage.model_ref },
          modes: {},
          revisions: { image: 1 },
        }}
        modelsByPurpose={{
          agent: [],
          text: [],
          image: [arkImage, deterministicImage],
          video: [],
          audio: [],
        }}
        loading={false}
        pending={false}
        notice={null}
        onSave={vi.fn()}
      />,
    );

    const imageSelect = screen.getByLabelText("Image default model");
    expect((imageSelect as HTMLSelectElement).value).toBe("");
    expect(within(imageSelect).queryByText(`${deterministicImage.model_ref} (unavailable)`)).toBeNull();
  });

  it("does not expose a persisted retired Ark Mini default as an unavailable option", () => {
    const retiredRef = "volcengine_ark:doubao-seed-2-0-mini-260428";
    render(
      <ModelDefaultsPanel
        defaults={{
          defaults: { text: retiredRef },
          modes: {},
          revisions: { text: 1 },
        }}
        modelsByPurpose={{ agent: [], text: [], image: [], video: [], audio: [] }}
        loading={false}
        pending={false}
        notice={null}
        onSave={vi.fn()}
      />,
    );

    const textSelect = screen.getByLabelText("Text default model");
    expect((textSelect as HTMLSelectElement).value).toBe("");
    expect(within(textSelect).queryByText(`${retiredRef} (unavailable)`)).toBeNull();
  });

  it("shows the backend-provided Audio routing mode beside its preferred model", async () => {
    render(<ApiSpacePage />);

    const automatic = await screen.findByRole("radio", { name: "Automatic" });
    await waitFor(() => expect(automatic.getAttribute("aria-checked")).toBe("true"));
    expect(screen.getByRole("radio", { name: "Explicit" }).getAttribute("aria-checked")).toBe("false");
    expect((screen.getByLabelText("Audio default model") as HTMLSelectElement).value).toBe(tianpuyueAudio.model_ref);
  });

  it("saves the Audio model and routing mode together in one patch", async () => {
    render(<ApiSpacePage />);
    const audioModel = await screen.findByLabelText("Audio default model");
    await waitFor(() => expect(screen.getByRole("radio", { name: "Automatic" }).getAttribute("aria-checked")).toBe("true"));

    fireEvent.click(screen.getByRole("radio", { name: "Explicit" }));
    fireEvent.change(audioModel, { target: { value: tianpuyueLongAudio.model_ref } });
    fireEvent.click(screen.getByRole("button", { name: "Save default models" }));

    await waitFor(() => expect(fixture.api.patchModelDefaults).toHaveBeenCalledWith({
      defaults: { audio: tianpuyueLongAudio.model_ref },
      modes: { audio: "explicit" },
    }));
  });

  it("does not write a candidate key to browser storage", async () => {
    const localStorageSpy = vi.spyOn(Storage.prototype, "setItem");
    render(<ApiSpacePage />);
    const input = await screen.findByLabelText("SiliconFlow Text API Key");
    fireEvent.change(input, { target: { value: "memory-only-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Save SiliconFlow credentials" }));

    await waitFor(() => expect(fixture.api.updateProviderCredentials).toHaveBeenCalledTimes(1));
    expect(localStorageSpy).not.toHaveBeenCalled();
  });
});

function provider(provider_id: string, display_name: string, capabilities: string[]) {
  return {
    provider_id,
    display_name,
    capabilities,
    connection_state: "unconfigured",
    credentials: Object.fromEntries(capabilities.map((capability) => [capability, {
      configured: false,
      fingerprint: null,
      source: "unconfigured",
      test_capability: capability === "text" ? "minimal_request" : "unsupported",
    }])),
    credential_revision: 1,
    updated_at: null,
  };
}

function model(
  model_ref: string,
  provider: string,
  display_name: string,
  capability: ProviderModelSummaryV1["capability"],
): ProviderModelSummaryV1 {
  return {
    model_ref,
    provider_id: provider.toLocaleLowerCase().replaceAll(" ", "_"),
    provider_model_id: model_ref.split(":")[1],
    display_name,
    capability,
    capability_metadata: {},
    availability: "available",
    unavailable_reason: null,
    catalog_revision: 1,
  };
}

function openRouterProvider(configured = false) {
  return {
    provider_id: "openrouter",
    display_name: "OpenRouter",
    capabilities: ["text", "image"] as const,
    connection_state: configured ? "configured" as const : "unconfigured" as const,
    credentials: {
      text: {
        configured,
        fingerprint: configured ? "shared-key" : null,
        source: configured ? "project_dotenv" as const : "unconfigured" as const,
        test_capability: "minimal_request" as const,
        endpoint: {
          scheme: "https" as const,
          host: "openrouter.ai",
          path: "/api/v1",
          fingerprint: "openrouter-text",
        },
      },
      image: {
        configured,
        fingerprint: configured ? "shared-key" : null,
        source: configured ? "project_dotenv" as const : "unconfigured" as const,
        test_capability: "minimal_request" as const,
        endpoint: {
          scheme: "https" as const,
          host: "openrouter.ai",
          path: "/api/v1",
          fingerprint: "openrouter-image",
        },
      },
    },
    credential_revision: 1,
    updated_at: null,
  };
}

function openRouterImageModel(overrides: Partial<ProviderModelSummaryV1> = {}): ProviderModelSummaryV1 {
  return {
    model_ref: "openrouter:openai/gpt-image-2",
    provider_id: "openrouter",
    provider_model_id: "openai/gpt-image-2",
    display_name: "GPT Image 2",
    capability: "image",
    capability_metadata: {},
    availability: "unavailable",
    unavailable_reason: "Provider credentials are missing.",
    catalog_revision: 1,
    adapter_id: "openrouter-image-native-v1",
    transport_kind: "openrouter_images_native",
    release_tier: "optional",
    conformance_status: "unverified",
    ...overrides,
  };
}
