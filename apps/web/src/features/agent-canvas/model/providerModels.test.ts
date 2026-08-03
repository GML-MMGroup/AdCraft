import { describe, expect, it } from "vitest";

import { normalizeProviderParameters } from "./providerModels.ts";

describe("normalizeProviderParameters", () => {
  it("keeps the canonical integer duration and removes retired video keys", () => {
    expect(normalizeProviderParameters("video", {
      requested_duration_seconds: 20,
      effective_duration_seconds: 15,
    })).toEqual({
      parameters: { duration_seconds: 20 },
      migrated: true,
    });
  });

  it("does not infer provider compatibility from local binding data", () => {
    expect(normalizeProviderParameters("image", { duration_seconds: 20 })).toEqual({
      parameters: { duration_seconds: 20 },
      migrated: false,
    });
  });
});
