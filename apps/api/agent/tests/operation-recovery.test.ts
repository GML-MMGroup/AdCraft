import { describe, expect, it, vi } from "vitest";

import {
  AgentOperationFailure,
  classifyAgentTransportFailure,
  runWithOneTransportRetry,
} from "../src/operation-recovery.js";


describe("Agent operation recovery", () => {
  it.each([
    [{ code: "ECONNRESET" }, true],
    [{ message: "remote disconnected" }, true],
    [{ code: "ERR_SSL_UNEXPECTED_EOF_WHILE_READING" }, true],
    [{ code: "ECONNREFUSED" }, true],
    [{ code: "EAI_AGAIN" }, true],
    [{ status: 429, retryAfterSeconds: 0.25 }, true],
    [{ status: 502 }, true],
    [{ status: 503 }, true],
    [{ status: 504 }, true],
    [{ status: 401 }, false],
    [{ status: 403 }, false],
    [{ status: 422 }, false],
    [{ message: "safety rejected" }, false],
    [{ code: "agent_deadline_exceeded" }, false],
  ])("classifies transport failures narrowly", (error, retryable) => {
    expect(classifyAgentTransportFailure(error).retryable).toBe(retryable);
  });

  it("retries one transient transport failure inside the original deadline", async () => {
    const operation = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce({ code: "ECONNRESET" })
      .mockResolvedValueOnce("completed");
    const sleep = vi.fn(async () => undefined);

    await expect(
      runWithOneTransportRetry(operation, {
        deadlineEpochMs: 5_000,
        now: () => 1_000,
        sleep,
      }),
    ).resolves.toBe("completed");
    expect(operation).toHaveBeenCalledTimes(2);
    expect(sleep).toHaveBeenCalledTimes(1);
  });

  it("never replays an unchanged operation after the hard deadline", async () => {
    const operation = vi.fn<() => Promise<string>>().mockRejectedValue(
      new AgentOperationFailure(
        "agent_deadline_exceeded",
        "Agent operation deadline exceeded.",
        false,
      ),
    );

    await expect(
      runWithOneTransportRetry(operation, {
        deadlineEpochMs: 2_000,
        now: () => 1_000,
        sleep: async () => undefined,
      }),
    ).rejects.toMatchObject({ code: "agent_deadline_exceeded" });
    expect(operation).toHaveBeenCalledTimes(1);
  });

  it("preserves structured contract failures without classifying them as transport", async () => {
    const operation = vi
      .fn<() => Promise<string>>()
      .mockRejectedValue(new Error("agent_structured_output_invalid"));

    await expect(
      runWithOneTransportRetry(operation, {
        deadlineEpochMs: 2_000,
        now: () => 1_000,
        sleep: async () => undefined,
      }),
    ).rejects.toMatchObject({
      code: "agent_structured_output_invalid",
      attemptStage: "structured_repair",
    });
    expect(operation).toHaveBeenCalledTimes(1);
  });

  it("does not retry when backoff would exceed the remaining budget", async () => {
    const operation = vi.fn<() => Promise<string>>().mockRejectedValue({
      status: 429,
      retryAfterSeconds: 2,
    });

    await expect(
      runWithOneTransportRetry(operation, {
        deadlineEpochMs: 2_000,
        now: () => 1_500,
        sleep: async () => undefined,
      }),
    ).rejects.toMatchObject({ code: "agent_transport_failed" });
    expect(operation).toHaveBeenCalledTimes(1);
  });
});
