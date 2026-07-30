import { describe, expect, it } from "vitest";
import { VOLCENGINE_CREDENTIAL_CONSUMERS } from "./volcengineCredentials";
import {
  buildTianpuyueCredentialUpdateRequest,
  type TianpuyueCredentialStatusResponse,
} from "./tianpuyueCredentials";

describe("Tianpuyue credential contracts", () => {
  it("builds the exact Audio update request from a trimmed candidate", () => {
    expect(buildTianpuyueCredentialUpdateRequest("  audio-secret  ")).toEqual({
      audio_api_key: "audio-secret",
    });
  });

  it("rejects an empty candidate", () => {
    expect(buildTianpuyueCredentialUpdateRequest("   ")).toBeNull();
  });

  it("models exactly one masked Audio credential", () => {
    const response: TianpuyueCredentialStatusResponse = {
      provider: "tianpuyue",
      credentials: {
        audio: {
          configured: true,
          masked_api_key: "********1234",
          source: "project_dotenv",
          test_capability: "unsupported",
        },
      },
    };

    expect(Object.keys(response.credentials)).toEqual(["audio"]);
    expect(response.credentials.audio.masked_api_key).toBe("********1234");
  });

  it("does not widen the Volcengine consumer contract", () => {
    expect(VOLCENGINE_CREDENTIAL_CONSUMERS).toEqual(["llm", "image", "video"]);
    expect(VOLCENGINE_CREDENTIAL_CONSUMERS).not.toContain("audio");
  });
});
