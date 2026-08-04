import { describe, expect, it, vi } from "vitest";

import { startVerifiedServer } from "../src/startup.js";

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
});
