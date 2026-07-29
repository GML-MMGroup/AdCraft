import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Tianpuyue credential client", () => {
  it("loads masked Audio credential status from the provider endpoint", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toMatch(/\/api\/v1\/settings\/providers\/tianpuyue$/);
      expect(init?.method).toBeUndefined();
      return jsonResponse({
        provider: "tianpuyue",
        credentials: {
          audio: {
            configured: true,
            masked_api_key: "********1234",
            source: "project_dotenv",
            test_capability: "unsupported",
          },
        },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await api.getTianpuyueCredentialStatus();

    expect(response.credentials.audio.masked_api_key).toBe("********1234");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("sends only the Audio candidate when saving or replacing a key", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toMatch(/\/api\/v1\/settings\/providers\/tianpuyue$/);
      expect(init?.method).toBe("PUT");
      expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
      expect(JSON.parse(String(init?.body))).toEqual({ audio_api_key: "audio-secret" });
      return jsonResponse({
        provider: "tianpuyue",
        credentials: {
          audio: {
            configured: true,
            masked_api_key: "********5678",
            source: "project_dotenv",
            test_capability: "unsupported",
          },
        },
        updated_consumers: ["audio"],
        applied: true,
        applied_at: "2026-07-29T00:00:00Z",
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await api.updateTianpuyueCredentials({ audio_api_key: "audio-secret" });

    expect(response.updated_consumers).toEqual(["audio"]);
    expect(response.credentials.audio.masked_api_key).toBe("********5678");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not expose a Tianpuyue connection-test operation", () => {
    expect("testTianpuyueCredential" in api).toBe(false);
  });
});

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
