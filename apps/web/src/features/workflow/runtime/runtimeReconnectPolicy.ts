export type RuntimeReconnectState = "idle" | "connecting" | "connected" | "reconnecting" | "degraded_polling";

type Timer = number;

export type RuntimeReconnectPolicyOptions = {
  onConnect: (generation: number) => void;
  onPoll: (generation: number) => Promise<void> | void;
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
  let pollGeneration: number | null = null;
  let resumeAfterPollGeneration: number | null = null;
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
    clearScheduledWork();
    transition(failureCount ? "reconnecting" : "connecting");
    try {
      options.onConnect(generation);
    } catch {
      sseFailed(generation);
    }
  };
  const schedulePoll = (delayMs: number, generation = lifecycleGeneration) => {
    if (!canRun(generation) || pollGeneration === generation) return;
    schedule((scheduledGeneration) => void poll(scheduledGeneration), delayMs, generation);
  };
  const poll = async (generation = lifecycleGeneration) => {
    if (!canRun(generation) || pollGeneration === generation) return;
    pollGeneration = generation;
    transition("degraded_polling");
    try {
      await options.onPoll(generation);
    } finally {
      if (pollGeneration === generation) {
        pollGeneration = null;
        const resumeAfterPoll = resumeAfterPollGeneration === generation;
        if (resumeAfterPoll) resumeAfterPollGeneration = null;
        if (canRun(generation)) {
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
        }
      }
    }
  };
  const pause = () => {
    if (active && pollGeneration === lifecycleGeneration) {
      resumeAfterPollGeneration = lifecycleGeneration;
    }
    clearScheduledWork();
    transition("idle");
  };
  const sseFailed = (generation = lifecycleGeneration) => {
    if (!canRun(generation)) {
      if (generation === lifecycleGeneration) pause();
      return;
    }
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
      active = true;
      pollGeneration = null;
      resumeAfterPollGeneration = null;
      pollCount = 0;
      clearScheduledWork();
      connect(lifecycleGeneration);
    },
    stop() {
      lifecycleGeneration += 1;
      active = false;
      pollGeneration = null;
      resumeAfterPollGeneration = null;
      failureCount = 0;
      pollCount = 0;
      pause();
    },
    reconcile() {
      if (!active || !isEligible()) return pause();
      if (pollGeneration === lifecycleGeneration) return;
      if (currentState === "idle") connect();
    },
    sseOpened(generation = lifecycleGeneration) {
      if (!canRun(generation)) {
        if (generation === lifecycleGeneration) pause();
        return;
      }
      clearScheduledWork();
      if (pollGeneration === generation) pollGeneration = null;
      if (resumeAfterPollGeneration === generation) resumeAfterPollGeneration = null;
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
