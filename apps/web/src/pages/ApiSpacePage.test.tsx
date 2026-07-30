import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiSpacePage } from "./ApiSpacePage";

const fixture = vi.hoisted(() => ({
  api: {
    getVolcengineCredentialStatus: vi.fn(),
    updateVolcengineCredentials: vi.fn(),
    testVolcengineCredential: vi.fn(),
    getTianpuyueCredentialStatus: vi.fn(),
    updateTianpuyueCredentials: vi.fn(),
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

const volcengineStatus = {
  provider: "volcengine_ark",
  credentials: {
    llm: {
      configured: true,
      masked_api_key: "********text",
      source: "project_dotenv",
      test_capability: "minimal_llm_request",
    },
    image: {
      configured: false,
      masked_api_key: null,
      source: "unconfigured",
      test_capability: "unsupported",
    },
    video: {
      configured: false,
      masked_api_key: null,
      source: "unconfigured",
      test_capability: "unsupported",
    },
  },
};

const tianpuyueStatus = {
  provider: "tianpuyue",
  credentials: {
    audio: {
      configured: true,
      masked_api_key: "********audio",
      source: "project_dotenv",
      test_capability: "unsupported",
    },
  },
};

function credentialInput(label: string) {
  const input = screen.getAllByLabelText(label).find((element) => element instanceof HTMLInputElement);
  if (!input) throw new Error(`Credential input not found: ${label}`);
  return input as HTMLInputElement;
}

describe("ApiSpacePage Tianpuyue credentials", () => {
  beforeEach(() => {
    fixture.api.getVolcengineCredentialStatus.mockResolvedValue(volcengineStatus);
    fixture.api.updateVolcengineCredentials.mockResolvedValue(volcengineStatus);
    fixture.api.testVolcengineCredential.mockResolvedValue({
      provider: "volcengine_ark",
      accepted: true,
      tested_consumer: "llm",
      tested_at: "2026-07-29T00:00:00Z",
    });
    fixture.api.getTianpuyueCredentialStatus.mockResolvedValue(tianpuyueStatus);
    fixture.api.updateTianpuyueCredentials.mockResolvedValue({
      ...tianpuyueStatus,
      credentials: {
        audio: {
          ...tianpuyueStatus.credentials.audio,
          masked_api_key: "********next",
        },
      },
      updated_consumers: ["audio"],
      applied: true,
      applied_at: "2026-07-29T00:00:00Z",
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("loads and renders separate Volcengine and Tianpuyue provider sections", async () => {
    render(<ApiSpacePage />);

    expect(screen.getByText("Volcengine Ark")).toBeTruthy();
    expect(screen.getByText("Tianpuyue Music")).toBeTruthy();
    expect(await screen.findByText("********audio")).toBeTruthy();
    expect(fixture.api.getVolcengineCredentialStatus).toHaveBeenCalledTimes(1);
    expect(fixture.api.getTianpuyueCredentialStatus).toHaveBeenCalledTimes(1);
  });

  it("never writes a configured mask into the Audio password input", async () => {
    render(<ApiSpacePage />);

    await screen.findByText("********audio");
    const input = credentialInput("Audio API Key");
    const section = screen.getByRole("region", { name: "Tianpuyue Music credentials" });

    expect(input.type).toBe("password");
    expect(input.autocomplete).toBe("new-password");
    expect(input.value).toBe("");
    expect(within(section).getByText("Test unavailable")).toBeTruthy();
    expect(within(section).queryByRole("button", { name: /test/i })).toBeNull();
  });

  it("shows an empty password field when Audio is not configured", async () => {
    fixture.api.getTianpuyueCredentialStatus.mockResolvedValueOnce({
      ...tianpuyueStatus,
      credentials: {
        audio: {
          configured: false,
          masked_api_key: null,
          source: "unconfigured",
          test_capability: "unsupported",
        },
      },
    });
    render(<ApiSpacePage />);

    const section = await screen.findByRole("region", { name: "Tianpuyue Music credentials" });
    expect(within(section).getByText("Not configured")).toBeTruthy();
    expect(credentialInput("Audio API Key").value).toBe("");
  });

  it("saves only the Audio candidate, updates the mask, and clears plaintext", async () => {
    render(<ApiSpacePage />);
    await screen.findByText("********audio");

    const input = credentialInput("Audio API Key");
    fireEvent.change(input, { target: { value: "  replacement-audio-key  " } });
    fireEvent.click(screen.getByRole("button", { name: "Save Audio key" }));

    await waitFor(() => {
      expect(fixture.api.updateTianpuyueCredentials).toHaveBeenCalledWith({
        audio_api_key: "replacement-audio-key",
      });
    });
    await screen.findByText("********next");
    expect(input.value).toBe("");
    expect(screen.getByText("Audio credential saved. New BGM requests use the updated configuration.")).toBeTruthy();
  });

  it("keeps the Audio candidate separate from Use Text key for all", async () => {
    render(<ApiSpacePage />);
    await screen.findByText("********audio");

    const textInput = credentialInput("Text API Key");
    const imageInput = credentialInput("Image API Key");
    const videoInput = credentialInput("Video API Key");
    const audioInput = credentialInput("Audio API Key");
    fireEvent.change(textInput, { target: { value: "text-candidate" } });
    fireEvent.change(audioInput, { target: { value: "audio-candidate" } });
    fireEvent.click(screen.getByRole("button", { name: "Use Text key for all" }));

    expect(imageInput.value).toBe("text-candidate");
    expect(videoInput.value).toBe("text-candidate");
    expect(audioInput.value).toBe("audio-candidate");
  });

  it("keeps Volcengine usable when Tianpuyue status loading fails", async () => {
    fixture.api.getTianpuyueCredentialStatus.mockRejectedValueOnce(new Error("not installed"));
    render(<ApiSpacePage />);

    expect(await screen.findByText("********text")).toBeTruthy();
    expect(screen.getByText("Unable to load Tianpuyue credential status. Check that the local backend supports this provider.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reload Tianpuyue status" })).toBeTruthy();
    expect(credentialInput("Text API Key").disabled).toBe(false);
  });

  it("keeps a candidate available for retry when saving fails", async () => {
    fixture.api.updateTianpuyueCredentials.mockRejectedValueOnce(new Error("save failed"));
    render(<ApiSpacePage />);
    await screen.findByText("********audio");

    const input = credentialInput("Audio API Key");
    fireEvent.change(input, { target: { value: "retry-audio-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Audio key" }));

    expect(await screen.findByText("Unable to save the Audio credential. No changes were confirmed.")).toBeTruthy();
    expect(input.value).toBe("retry-audio-key");
  });

  it("disables Audio editing while a save is pending", async () => {
    let resolveSave: ((value: unknown) => void) | undefined;
    fixture.api.updateTianpuyueCredentials.mockReturnValueOnce(new Promise((resolve) => {
      resolveSave = resolve;
    }));
    render(<ApiSpacePage />);
    await screen.findByText("********audio");

    const input = credentialInput("Audio API Key");
    fireEvent.change(input, { target: { value: "pending-audio-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Audio key" }));

    await waitFor(() => {
      expect(input.disabled).toBe(true);
      expect(screen.getByRole("button", { name: "Saving Audio key..." }).hasAttribute("disabled")).toBe(true);
    });

    resolveSave?.({
      ...tianpuyueStatus,
      updated_consumers: ["audio"],
      applied: true,
      applied_at: "2026-07-29T00:00:00Z",
    });
    await screen.findByText("Audio credential saved. New BGM requests use the updated configuration.");
  });

  it("does not persist the Audio candidate in browser storage", async () => {
    const localStorageSpy = vi.spyOn(Storage.prototype, "setItem");
    render(<ApiSpacePage />);
    await screen.findByText("********audio");

    fireEvent.change(credentialInput("Audio API Key"), { target: { value: "memory-only-audio-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Audio key" }));

    await waitFor(() => expect(fixture.api.updateTianpuyueCredentials).toHaveBeenCalledTimes(1));
    expect(localStorageSpy).not.toHaveBeenCalled();
  });

  it("does not call a provider test while rendering unsupported capability", async () => {
    render(<ApiSpacePage />);

    await screen.findByText("********audio");
    expect(fixture.api.testVolcengineCredential).not.toHaveBeenCalled();
    expect("testTianpuyueCredential" in fixture.api).toBe(false);
  });
});
