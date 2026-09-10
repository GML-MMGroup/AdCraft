import { describe, expect, it } from "vitest";

import type { ProviderConnectionStatusV1 } from "./providerRegistry.ts";
import {
  clearCapabilitiesForProvider,
  updateCredentialDraftForProvider,
  usesSharedOpenRouterCredential,
} from "./providerCredentialPolicy.ts";

const openRouterProvider: ProviderConnectionStatusV1 = {
  provider_id: "openrouter",
  display_name: "OpenRouter",
  capabilities: ["text", "image"],
  connection_state: "unconfigured",
  credentials: {},
  credential_revision: 1,
};

describe("provider credential policy", () => {
  it("recognizes the shared OpenRouter text and image credential", () => {
    expect(usesSharedOpenRouterCredential(openRouterProvider)).toBe(true);
    expect(usesSharedOpenRouterCredential({ ...openRouterProvider, provider_id: "openai" })).toBe(false);
  });

  it("copies one OpenRouter key into both capability fields", () => {
    expect(updateCredentialDraftForProvider(openRouterProvider, {}, "text", "secret")).toEqual({
      text: "secret",
      image: "secret",
    });
  });

  it("clears both OpenRouter capability states atomically", () => {
    expect(clearCapabilitiesForProvider(openRouterProvider, "image")).toEqual(["text", "image"]);
    expect(clearCapabilitiesForProvider({ ...openRouterProvider, provider_id: "other" }, "image")).toEqual(["image"]);
  });
});
