import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
const arkText = model("volcengine_ark:doubao-seed-2-0-mini-260428", "Volcengine Ark", "Doubao Seed 2.0 Mini", "text");
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
      if (query.provider === "volcengine_ark") return Promise.resolve({ items: [arkText] });
      if (query.purpose === "agent" || query.purpose === "text") return Promise.resolve({ items: [glm, arkText] });
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
    expect(screen.getByText("Text credential verified.")).toBeTruthy();
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

function model(model_ref: string, provider: string, display_name: string, capability: string) {
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
