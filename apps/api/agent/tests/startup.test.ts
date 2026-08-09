import { describe, expect, it, vi } from "vitest";

import {
  startVerifiedServer,
  validateOperationRegistry,
} from "../src/startup.js";

describe("agent runtime startup", () => {
  it("does not listen when complete Skill verification fails", async () => {
    const listen = vi.fn();
    const failure = new Error("agent_skill_digest_mismatch");

    await expect(
      startVerifiedServer(
        { listen },
        8765,
        "127.0.0.1",
        async () => Promise.reject(failure),
      ),
    ).rejects.toBe(failure);

    expect(listen).not.toHaveBeenCalled();
  });

  it("listens only after complete Skill verification succeeds", async () => {
    const calls: string[] = [];
    const listen = vi.fn(() => {
      calls.push("listen");
    });

    await startVerifiedServer(
      { listen },
      8765,
      "127.0.0.1",
      async () => {
        calls.push("verify");
      },
    );

    expect(calls).toEqual(["verify", "listen"]);
    expect(listen).toHaveBeenCalledWith(8765, "127.0.0.1");
  });

  it("rejects descriptor omissions, handoffs, and multiple Skills", () => {
    const valid = {
      agent_name: "video_agent",
      operation: "free_image",
      required_skill: "video_agent_quick_media",
      allowed_tools: ["submit_structured_result"],
      max_handoffs: 0,
    };

    expect(() =>
      validateOperationRegistry([valid], ["free_image", "free_video"], [
        "video_agent_quick_media",
      ]),
    ).toThrow("agent_operation_registry_invalid");
    expect(() =>
      validateOperationRegistry(
        [{ ...valid, max_handoffs: 1 }],
        ["free_image"],
        ["video_agent_quick_media"],
      ),
    ).toThrow("agent_operation_registry_invalid");
    expect(() =>
      validateOperationRegistry(
        [{ ...valid, required_skills: ["one", "two"] }],
        ["free_image"],
        ["one", "two"],
      ),
    ).toThrow("agent_operation_registry_invalid");
  });
});
