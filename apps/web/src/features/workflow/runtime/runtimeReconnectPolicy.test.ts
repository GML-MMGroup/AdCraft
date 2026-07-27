import { describe, expect, it } from "vitest";

import { createRuntimeReconnectPolicy } from "./runtimeReconnectPolicy.ts";

function createScheduler() {
  let nextId = 0;
  const timers = new Map<number, { callback: () => void; delayMs: number }>();
  const scheduledDelays: number[] = [];
  return {
    timers,
    scheduledDelays,
    setTimeout(callback: () => void, delayMs: number) {
      nextId += 1;
      timers.set(nextId, { callback, delayMs });
      scheduledDelays.push(delayMs);
      return nextId;
    },
    clearTimeout(id: number) {
      timers.delete(id);
    },
    runNext() {
      const next = timers.entries().next().value as [number, { callback: () => void; delayMs: number }] | undefined;
      if (!next) return;
      timers.delete(next[0]);
      next[1].callback();
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

  it("records exact jittered exponential delays and caps every retry", () => {
    const scheduler = createScheduler();
    const randomValues = [0, 0.25, 1];
    const policy = createRuntimeReconnectPolicy({
      random: () => randomValues.shift() ?? 1,
      setTimeout: scheduler.setTimeout,
      clearTimeout: scheduler.clearTimeout,
      baseDelayMs: 100,
      maxDelayMs: 250,
      maxSseFailures: 3,
      onConnect: () => {},
      onPoll: async () => {},
      onStateChange: () => {},
    });

    policy.start();
    policy.sseFailed();
    scheduler.runNext();
    policy.sseFailed();
    scheduler.runNext();
    policy.sseFailed();

    expect(scheduler.scheduledDelays).toEqual([50, 150, 250]);
    expect(scheduler.scheduledDelays.every((delay) => delay >= 0 && delay <= 250)).toBe(true);
  });

  it("falls back to one polling lane and periodically recovers SSE after polling completes", async () => {
    const scheduler = createScheduler();
    let connects = 0;
    let polls = 0;
    let pollsInFlight = 0;
    const pollsInFlightWhenConnecting: number[] = [];
    const policy = createRuntimeReconnectPolicy({
      random: () => 0,
      setTimeout: scheduler.setTimeout,
      clearTimeout: scheduler.clearTimeout,
      maxSseFailures: 0,
      sseRecoveryPolls: 2,
      onConnect: () => {
        connects += 1;
        pollsInFlightWhenConnecting.push(pollsInFlight);
      },
      onPoll: async () => {
        polls += 1;
        pollsInFlight += 1;
        await Promise.resolve();
        pollsInFlight -= 1;
      },
      onStateChange: () => {},
    });

    policy.start();
    policy.sseFailed();
    scheduler.runNext();
    await Promise.resolve();
    await Promise.resolve();
    scheduler.runNext();
    await Promise.resolve();
    await Promise.resolve();

    expect(polls).toBe(2);
    expect(connects).toBe(2);
    expect(pollsInFlightWhenConnecting).toEqual([0, 0]);
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

  it("recovers SSE once when eligibility returns before a paused fallback poll settles", async () => {
    const scheduler = createScheduler();
    let eligible = true;
    let connects = 0;
    let polls = 0;
    let completePoll: (() => void) | undefined;
    const policy = createRuntimeReconnectPolicy({
      isEligible: () => eligible,
      setTimeout: scheduler.setTimeout,
      clearTimeout: scheduler.clearTimeout,
      maxSseFailures: 0,
      onConnect: () => { connects += 1; },
      onPoll: () => new Promise<void>((resolve) => {
        polls += 1;
        completePoll = resolve;
      }),
      onStateChange: () => {},
    });

    policy.start();
    policy.sseFailed();
    scheduler.runNext();
    eligible = false;
    policy.reconcile();
    eligible = true;
    policy.reconcile();
    policy.reconcile();

    expect(connects).toBe(1);
    expect(polls).toBe(1);
    expect(policy.state()).toBe("idle");
    completePoll?.();
    await Promise.resolve();
    await Promise.resolve();

    policy.reconcile();
    policy.reconcile();

    expect(connects).toBe(2);
    expect(polls).toBe(1);
    expect(policy.state()).toBe("reconnecting");
    expect(scheduler.timers.size).toBe(0);
  });

  it("recovers SSE once when a paused fallback poll settles before eligibility returns", async () => {
    const scheduler = createScheduler();
    let eligible = true;
    let connects = 0;
    let polls = 0;
    let completePoll: (() => void) | undefined;
    const policy = createRuntimeReconnectPolicy({
      isEligible: () => eligible,
      setTimeout: scheduler.setTimeout,
      clearTimeout: scheduler.clearTimeout,
      maxSseFailures: 0,
      onConnect: () => { connects += 1; },
      onPoll: () => new Promise<void>((resolve) => {
        polls += 1;
        completePoll = resolve;
      }),
      onStateChange: () => {},
    });

    policy.start();
    policy.sseFailed();
    scheduler.runNext();
    expect(polls).toBe(1);

    eligible = false;
    policy.reconcile();
    completePoll?.();
    await Promise.resolve();
    await Promise.resolve();

    expect(policy.state()).toBe("idle");
    expect(scheduler.timers.size).toBe(0);

    eligible = true;
    policy.reconcile();
    policy.reconcile();

    expect(connects).toBe(2);
    expect(polls).toBe(1);
    expect(scheduler.timers.size).toBe(0);
  });

  it("cancels a scheduled fallback poll when SSE opens first", async () => {
    const scheduler = createScheduler();
    let connects = 0;
    let polls = 0;
    const policy = createRuntimeReconnectPolicy({
      setTimeout: scheduler.setTimeout,
      clearTimeout: scheduler.clearTimeout,
      maxSseFailures: 0,
      onConnect: () => { connects += 1; },
      onPoll: async () => { polls += 1; },
      onStateChange: () => {},
    });

    policy.start();
    policy.sseFailed();
    scheduler.runNext();
    await Promise.resolve();
    await Promise.resolve();

    expect(scheduler.timers.size).toBe(1);
    policy.sseOpened();
    scheduler.runNext();
    await Promise.resolve();

    expect(connects).toBe(1);
    expect(polls).toBe(1);
    expect(policy.state()).toBe("connected");
    expect(scheduler.timers.size).toBe(0);
  });

  it("makes an aborted poll finalizer inert when SSE opens", async () => {
    const scheduler = createScheduler();
    let completePoll: (() => void) | undefined;
    let pollSignal: AbortSignal | undefined;
    const policy = createRuntimeReconnectPolicy({
      setTimeout: scheduler.setTimeout,
      clearTimeout: scheduler.clearTimeout,
      maxSseFailures: 0,
      onConnect: () => {},
      onPoll: (_generation, signal) => new Promise<void>((resolve) => {
        pollSignal = signal;
        completePoll = resolve;
      }),
      onStateChange: () => {},
    });

    policy.start();
    policy.sseFailed();
    scheduler.runNext();
    policy.sseOpened();

    expect(pollSignal?.aborted).toBe(true);
    expect(policy.state()).toBe("connected");
    completePoll?.();
    await Promise.resolve();
    await Promise.resolve();

    expect(policy.state()).toBe("connected");
    expect(scheduler.timers.size).toBe(0);
  });

  it("hands connected SSE ownership to one awaited poll before reconnecting", async () => {
    const scheduler = createScheduler();
    let connects = 0;
    let disconnects = 0;
    let polls = 0;
    let completePoll: (() => void) | undefined;
    const policy = createRuntimeReconnectPolicy({
      setTimeout: scheduler.setTimeout,
      clearTimeout: scheduler.clearTimeout,
      onConnect: () => { connects += 1; },
      onDisconnect: () => { disconnects += 1; },
      onPoll: () => new Promise<void>((resolve) => {
        polls += 1;
        completePoll = resolve;
      }),
      onStateChange: () => {},
    });

    policy.start();
    policy.sseOpened();
    const synchronization = policy.synchronize();

    expect(disconnects).toBe(1);
    expect(polls).toBe(1);
    expect(policy.state()).toBe("degraded_polling");
    completePoll?.();
    await synchronization;

    expect(connects).toBe(2);
    expect(policy.state()).toBe("connecting");
    expect(scheduler.timers.size).toBe(0);
  });

  it("joins direct synchronization to the active degraded poll", async () => {
    const scheduler = createScheduler();
    let polls = 0;
    let completePoll: (() => void) | undefined;
    const policy = createRuntimeReconnectPolicy({
      setTimeout: scheduler.setTimeout,
      clearTimeout: scheduler.clearTimeout,
      maxSseFailures: 0,
      onConnect: () => {},
      onPoll: () => new Promise<void>((resolve) => {
        polls += 1;
        completePoll = resolve;
      }),
      onStateChange: () => {},
    });

    policy.start();
    policy.sseFailed();
    scheduler.runNext();
    const firstSync = policy.synchronize();
    const secondSync = policy.synchronize();

    expect(polls).toBe(1);
    completePoll?.();
    await Promise.all([firstSync, secondSync]);
    expect(polls).toBe(1);
  });

  it("awaits a stale poll before workflow generation replacement starts transport", async () => {
    const scheduler = createScheduler();
    const completePolls: Array<() => void> = [];
    let eligible = true;
    let connects = 0;
    let polls = 0;
    let pollsInFlight = 0;
    const pollsInFlightWhenConnecting: number[] = [];
    const policy = createRuntimeReconnectPolicy({
      isEligible: () => eligible,
      setTimeout: scheduler.setTimeout,
      clearTimeout: scheduler.clearTimeout,
      maxSseFailures: 0,
      onConnect: () => {
        connects += 1;
        pollsInFlightWhenConnecting.push(pollsInFlight);
      },
      onPoll: () => new Promise<void>((resolve) => {
        polls += 1;
        pollsInFlight += 1;
        completePolls.push(() => {
          pollsInFlight -= 1;
          resolve();
        });
      }),
      onStateChange: () => {},
    });

    policy.start();
    policy.sseFailed();
    scheduler.runNext();
    expect(polls).toBe(1);
    eligible = false;
    policy.reconcile();
    eligible = true;
    policy.reconcile();

    policy.start();
    expect(connects).toBe(1);
    expect(polls).toBe(1);
    expect(pollsInFlight).toBe(1);

    completePolls[0]?.();
    await Promise.resolve();
    await Promise.resolve();
    expect(connects).toBe(2);
    expect(pollsInFlightWhenConnecting).toEqual([0, 0]);

    policy.sseFailed();
    scheduler.runNext();
    expect(polls).toBe(2);
    completePolls[1]?.();
    await Promise.resolve();
    policy.sseOpened();

    await Promise.resolve();

    expect(connects).toBe(2);
    expect(polls).toBe(2);
    expect(scheduler.timers.size).toBe(0);
    expect(policy.state()).toBe("connected");
  });
});
