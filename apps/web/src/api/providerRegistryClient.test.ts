import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./client.ts";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("provider registry client", () => {
  it("uses the canonical SiliconFlow credential route instead of a Volcengine route", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toMatch(/\/api\/v1\/providers\/siliconflow\/credentials$/);
      expect(init?.method).toBe("PUT");
      expect(JSON.parse(String(init?.body))).toEqual({
        api_keys: { text: "siliconflow-candidate" },
        clear_capabilities: [],
      });
      return jsonResponse({
        provider: providerStatus("siliconflow", ["text"]),
        updated_capabilities: ["text"],
        cleared_capabilities: [],
        applied_at: "2026-08-03T03:00:00Z",
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await api.updateProviderCredentials("siliconflow", {
      api_keys: { text: "siliconflow-candidate" },
      clear_capabilities: [],
    });

    expect(response.provider.provider_id).toBe("siliconflow");
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("loads providers, model inventory, and all installation defaults from canonical routes", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      expect(init?.method).toBeUndefined();
      if (url.endsWith("/providers")) {
        return jsonResponse({ items: [providerStatus("siliconflow", ["text"])] });
      }
      if (url.includes("/models?")) {
        expect(url).toContain("provider=siliconflow");
        expect(url).toContain("include_unavailable=true");
        return jsonResponse({ items: [model("siliconflow:zai-org/GLM-5.2")] });
      }
      if (url.endsWith("/model-defaults")) {
        return jsonResponse({
          defaults: { text: "siliconflow:zai-org/GLM-5.2" },
          revisions: { text: 3 },
        });
      }
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const [providers, models, defaults] = await Promise.all([
      api.listProviders(),
      api.listProviderModels({ provider: "siliconflow", include_unavailable: true }),
      api.getModelDefaults(),
    ]);

    expect(providers.items[0]?.display_name).toBe("SiliconFlow");
    expect(models.items[0]?.model_ref).toBe("siliconflow:zai-org/GLM-5.2");
    expect(defaults.defaults.text).toBe("siliconflow:zai-org/GLM-5.2");
  });

  it("syncs a provider catalog and patches selected global defaults", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/providers/siliconflow/models/sync")) {
        expect(init?.method).toBe("POST");
        return jsonResponse({
          provider_id: "siliconflow",
          sync_run_id: "sync-1",
          catalog_revision: 4,
          status: "succeeded",
        });
      }
      if (url.endsWith("/model-defaults")) {
        expect(init?.method).toBe("PATCH");
        expect(JSON.parse(String(init?.body))).toEqual({
          defaults: {
            agent: "siliconflow:zai-org/GLM-5.2",
            text: "siliconflow:zai-org/GLM-5.2",
          },
        });
        return jsonResponse({
          defaults: {
            agent: "siliconflow:zai-org/GLM-5.2",
            text: "siliconflow:zai-org/GLM-5.2",
          },
          revisions: { agent: 4, text: 4 },
        });
      }
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const sync = await api.syncProviderModels("siliconflow");
    const defaults = await api.patchModelDefaults({
      defaults: {
        agent: "siliconflow:zai-org/GLM-5.2",
        text: "siliconflow:zai-org/GLM-5.2",
      },
    });

    expect(sync.catalog_revision).toBe(4);
    expect(defaults.revisions.agent).toBe(4);
  });
});

function providerStatus(providerId: string, capabilities: string[]) {
  return {
    provider_id: providerId,
    display_name: providerId === "siliconflow" ? "SiliconFlow" : providerId,
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

function model(modelRef: string) {
  return {
    model_ref: modelRef,
    provider_id: "siliconflow",
    provider_model_id: "zai-org/GLM-5.2",
    display_name: "GLM-5.2",
    capability: "text",
    capability_metadata: {},
    availability: "available",
    unavailable_reason: null,
    catalog_revision: 4,
  };
}

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
