export type RuntimeReconnectState = "idle" | "connecting" | "connected" | "reconnecting" | "degraded_polling";

type Timer = number;

export type RuntimeReconnectPolicyOptions = {
  onConnect: (generation: number) => void;
  onDisconnect?: () => void;
  onPoll: (generation: number, signal: AbortSignal) => Promise<void> | void;
  onStateChange: (state: RuntimeReconnectState) => void;
  isEligible?: () => boolean;
  setTimeout?: (callback: () => void, delayMs: number) => Timer;
  clearTimeout?: (timer: Timer) => void;
  random?: () => number;
  baseDelayMs?: number;
  maxDelayMs?: number;
  maxSseFailures?: number;
  pollIntervalMs?: number;
  sseRecoveryPolls?: number;
};

export function createRuntimeReconnectPolicy(options: RuntimeReconnectPolicyOptions) {
  const isEligible = options.isEligible ?? (() => true);
  const setTimer = options.setTimeout ?? ((callback, delayMs) => window.setTimeout(callback, delayMs));
  const clearTimer = options.clearTimeout ?? ((timer) => window.clearTimeout(timer));
  const random = options.random ?? Math.random;
  const baseDelayMs = options.baseDelayMs ?? 1_000;
  const maxDelayMs = options.maxDelayMs ?? 30_000;
  const maxSseFailures = options.maxSseFailures ?? 3;
  const pollIntervalMs = options.pollIntervalMs ?? 5_000;
  const sseRecoveryPolls = options.sseRecoveryPolls ?? 6;
  let timer: { id: Timer; generation: number } | null = null;
  let active = false;
  let lifecycleGeneration = 0;
  let activePoll: {
    generation: number;
    controller: AbortController;
    promise: Promise<void>;
    ownsResult: boolean;
  } | null = null;
  let resumeAfterPollGeneration: number | null = null;
  let connectionGeneration: number | null = null;
  let failureCount = 0;
  let pollCount = 0;
  let currentState: RuntimeReconnectState = "idle";

  const transition = (state: RuntimeReconnectState) => {
    currentState = state;
    options.onStateChange(state);
  };
  const clearScheduledWork = () => {
    if (timer === null) return;
    clearTimer(timer.id);
    timer = null;
  };
  const canRun = (generation = lifecycleGeneration) => active && generation === lifecycleGeneration && isEligible();
  const schedule = (callback: (generation: number) => void, delayMs: number, generation = lifecycleGeneration) => {
    clearScheduledWork();
    const timerId = setTimer(() => {
      if (timer?.id === timerId) timer = null;
      if (!canRun(generation)) return;
      callback(generation);
    }, delayMs);
    timer = { id: timerId, generation };
  };
  const connect = (generation = lifecycleGeneration) => {
    if (!canRun(generation)) {
      if (generation === lifecycleGeneration) pause();
      return;
    }
    if (activePoll || connectionGeneration === generation) return;
    clearScheduledWork();
    connectionGeneration = generation;
    transition(failureCount ? "reconnecting" : "connecting");
    try {
      options.onConnect(generation);
    } catch {
      sseFailed(generation);
    }
  };
  const schedulePoll = (delayMs: number, generation = lifecycleGeneration) => {
    if (!canRun(generation) || activePoll) return;
    schedule((scheduledGeneration) => void poll(scheduledGeneration), delayMs, generation);
  };
  const poll = (generation = lifecycleGeneration): Promise<void> => {
    if (!canRun(generation)) return Promise.resolve();
    if (activePoll) {
      if (activePoll.generation === generation && activePoll.ownsResult) return activePoll.promise;
      return activePoll.promise.then(() => poll(generation));
    }
    const entry = {
      generation,
      controller: new AbortController(),
      promise: Promise.resolve(),
      ownsResult: true,
    };
    activePoll = entry;
    transition("degraded_polling");
    entry.promise = (async () => {
      try {
        await options.onPoll(generation, entry.controller.signal);
      } catch {
        // Poll failures retain degraded transport state and follow the same retry lane.
      } finally {
        if (activePoll === entry) {
          activePoll = null;
          const resumeAfterPoll = resumeAfterPollGeneration === generation;
          if (resumeAfterPoll) resumeAfterPollGeneration = null;
          if (entry.ownsResult && canRun(generation)) {
            if (resumeAfterPoll) {
              pollCount = 0;
              connect(generation);
            } else {
              pollCount += 1;
              if (pollCount >= sseRecoveryPolls) {
                pollCount = 0;
                connect(generation);
              } else {
                schedulePoll(pollIntervalMs, generation);
              }
            }
          } else if (resumeAfterPoll && canRun(generation)) {
            connect(generation);
          }
        }
      }
    })();
    return entry.promise;
  };
  const pause = () => {
    if (active && activePoll?.generation === lifecycleGeneration) {
      resumeAfterPollGeneration = lifecycleGeneration;
    }
    clearScheduledWork();
    connectionGeneration = null;
    transition("idle");
  };
  const sseFailed = (generation = lifecycleGeneration) => {
    if (!canRun(generation)) {
      if (generation === lifecycleGeneration) pause();
      return;
    }
    if (connectionGeneration === generation) connectionGeneration = null;
    failureCount += 1;
    if (failureCount > maxSseFailures) {
      transition("degraded_polling");
      schedulePoll(0, generation);
      return;
    }
    transition("reconnecting");
    const exponentialDelay = Math.min(maxDelayMs, baseDelayMs * 2 ** (failureCount - 1));
    const jitteredDelay = Math.min(maxDelayMs, Math.round(exponentialDelay * (0.5 + random())));
    schedule(connect, jitteredDelay, generation);
  };

  return {
    start() {
      lifecycleGeneration += 1;
      const generation = lifecycleGeneration;
      active = true;
      resumeAfterPollGeneration = null;
      connectionGeneration = null;
      pollCount = 0;
      clearScheduledWork();
      const previousPoll = activePoll;
      if (!previousPoll) {
        connect(generation);
        return;
      }
      previousPoll.controller.abort();
      void previousPoll.promise.then(
        () => {
          if (canRun(generation)) connect(generation);
        },
        () => {
          if (canRun(generation)) connect(generation);
        },
      );
    },
    stop() {
      lifecycleGeneration += 1;
      active = false;
      resumeAfterPollGeneration = null;
      connectionGeneration = null;
      failureCount = 0;
      pollCount = 0;
      activePoll?.controller.abort();
      pause();
    },
    reconcile() {
      if (!active || !isEligible()) return pause();
      if (activePoll) return;
      if (currentState === "idle") connect();
    },
    synchronize() {
      const generation = lifecycleGeneration;
      if (!canRun(generation)) return Promise.resolve();
      if (activePoll?.generation === generation) return activePoll.promise;
      clearScheduledWork();
      if (currentState !== "degraded_polling") {
        options.onDisconnect?.();
        connectionGeneration = null;
        resumeAfterPollGeneration = generation;
      }
      return poll(generation);
    },
    sseOpened(generation = lifecycleGeneration) {
      if (!canRun(generation)) {
        if (generation === lifecycleGeneration) pause();
        return;
      }
      clearScheduledWork();
      if (activePoll?.generation === generation) {
        const pollToAbort = activePoll;
        pollToAbort.ownsResult = false;
        pollToAbort.controller.abort();
      }
      if (resumeAfterPollGeneration === generation) resumeAfterPollGeneration = null;
      connectionGeneration = generation;
      pollCount = 0;
      transition("connected");
    },
    sseHealthyEvent(generation = lifecycleGeneration) {
      if (!canRun(generation)) return;
      failureCount = 0;
    },
    sseFailed,
    state: () => currentState,
    failures: () => failureCount,
  };
}
