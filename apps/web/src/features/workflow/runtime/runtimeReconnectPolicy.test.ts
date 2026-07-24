import { describe, expect, it } from "vitest";

import { createRuntimeReconnectPolicy } from "./runtimeReconnectPolicy.ts";

function createScheduler() {
  let nextId = 0;
  const timers = new Map<number, () => void>();
  return {
    timers,
    setTimeout(callback: () => void) {
      nextId += 1;
      timers.set(nextId, callback);
      return nextId;
    },
    clearTimeout(id: number) {
      timers.delete(id);
    },
    runNext() {
      const next = timers.entries().next().value as [number, () => void] | undefined;
      if (!next) return;
      timers.delete(next[0]);
      next[1]();
    },
  };
}

describe("createRuntimeReconnectPolicy", () => {
  it("uses bounded exponential backoff with injected jitter and only one reconnect timer", () => {
    const scheduler = createScheduler();
    const states: string[] = [];
    let connects = 0;
    const policy = createRuntimeReconnectPolicy({
      random: () => 1,
      setTimeout: scheduler.setTimeout,
      clearTimeout: scheduler.clearTimeout,
      baseDelayMs: 100,
      maxDelayMs: 250,
      maxSseFailures: 3,
      onConnect: () => { connects += 1; },
      onPoll: async () => {},
      onStateChange: (state) => { states.push(state); },
    });

    policy.start();
    policy.sseFailed();
    policy.sseFailed();

    expect(connects).toBe(1);
    expect(scheduler.timers.size).toBe(1);
    expect(policy.state()).toBe("reconnecting");
    scheduler.runNext();
    expect(connects).toBe(2);
    expect(states).toContain("reconnecting");
  });

  it("falls back to one polling lane and periodically recovers SSE after polling completes", async () => {
    const scheduler = createScheduler();
    let connects = 0;
    let polls = 0;
    const policy = createRuntimeReconnectPolicy({
      random: () => 0,
      setTimeout: scheduler.setTimeout,
      clearTimeout: scheduler.clearTimeout,
      maxSseFailures: 0,
      sseRecoveryPolls: 2,
      onConnect: () => { connects += 1; },
      onPoll: async () => { polls += 1; },
      onStateChange: () => {},
    });

    policy.start();
    policy.sseFailed();
    scheduler.runNext();
    await Promise.resolve();
    scheduler.runNext();
    await Promise.resolve();

    expect(polls).toBe(2);
    expect(connects).toBe(2);
    expect(policy.state()).toBe("reconnecting");
  });

  it("pauses hidden or offline transport and resets retry pressure only after a healthy event", () => {
    const scheduler = createScheduler();
    let eligible = true;
    let connects = 0;
    const policy = createRuntimeReconnectPolicy({
      isEligible: () => eligible,
      setTimeout: scheduler.setTimeout,
      clearTimeout: scheduler.clearTimeout,
      onConnect: () => { connects += 1; },
      onPoll: async () => {},
      onStateChange: () => {},
    });

    policy.start();
    policy.sseFailed();
    eligible = false;
    policy.reconcile();
    scheduler.runNext();

    expect(connects).toBe(1);
    expect(policy.state()).toBe("idle");
    eligible = true;
    policy.reconcile();
    policy.sseHealthyEvent();
    expect(policy.failures()).toBe(0);
  });

  it("does not reconnect SSE while a paused fallback poll is still in flight", async () => {
    const scheduler = createScheduler();
    let eligible = true;
    let connects = 0;
    let completePoll: (() => void) | undefined;
    const policy = createRuntimeReconnectPolicy({
      isEligible: () => eligible,
      setTimeout: scheduler.setTimeout,
      clearTimeout: scheduler.clearTimeout,
      maxSseFailures: 0,
      onConnect: () => { connects += 1; },
      onPoll: () => new Promise<void>((resolve) => { completePoll = resolve; }),
      onStateChange: () => {},
    });

    policy.start();
    policy.sseFailed();
    scheduler.runNext();
    eligible = false;
    policy.reconcile();
    eligible = true;
    policy.reconcile();

    expect(connects).toBe(1);
    completePoll?.();
    await Promise.resolve();
  });
});
