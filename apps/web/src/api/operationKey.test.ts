import { describe, expect, it, vi } from "vitest";

import { createOperationKey } from "./operationKey.ts";

describe("createOperationKey", () => {
  it("uses a namespaced UUID when Web Crypto is available", () => {
    const randomUUID = vi.fn(() => "uuid-1");
    vi.stubGlobal("crypto", { randomUUID });

    expect(createOperationKey("chat")).toBe("chat-uuid-1");
    expect(randomUUID).toHaveBeenCalledTimes(1);

    vi.unstubAllGlobals();
  });

  it("falls back when randomUUID is unavailable", () => {
    vi.stubGlobal("crypto", {});

    expect(createOperationKey("run")).toMatch(/^run-\d+-[a-z0-9]+$/);

    vi.unstubAllGlobals();
  });
});
