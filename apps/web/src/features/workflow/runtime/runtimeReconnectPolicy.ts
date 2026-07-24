export type RuntimeReconnectState = "idle" | "connecting" | "connected" | "reconnecting" | "degraded_polling";

type Timer = number;

export type RuntimeReconnectPolicyOptions = {
  onConnect: () => void;
  onPoll: () => Promise<void> | void;
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
  let timer: Timer | null = null;
  let active = false;
  let pollInFlight = false;
  let failureCount = 0;
  let pollCount = 0;
  let currentState: RuntimeReconnectState = "idle";

  const transition = (state: RuntimeReconnectState) => {
    currentState = state;
    options.onStateChange(state);
  };
  const clearScheduledWork = () => {
    if (timer === null) return;
    clearTimer(timer);
    timer = null;
  };
  const schedule = (callback: () => void, delayMs: number) => {
    clearScheduledWork();
    timer = setTimer(() => {
      timer = null;
      callback();
    }, delayMs);
  };
  const canRun = () => active && isEligible();
  const connect = () => {
    if (!canRun()) return pause();
    transition(failureCount ? "reconnecting" : "connecting");
    try {
      options.onConnect();
    } catch {
      sseFailed();
    }
  };
  const schedulePoll = (delayMs: number) => {
    if (!canRun() || pollInFlight) return;
    schedule(() => void poll(), delayMs);
  };
  const poll = async () => {
    if (!canRun() || pollInFlight) return;
    pollInFlight = true;
    transition("degraded_polling");
    try {
      await options.onPoll();
    } finally {
      pollInFlight = false;
      if (!canRun()) return;
      pollCount += 1;
      if (pollCount >= sseRecoveryPolls) {
        pollCount = 0;
        connect();
        return;
      }
      schedulePoll(pollIntervalMs);
    }
  };
  const pause = () => {
    clearScheduledWork();
    transition("idle");
  };
  const sseFailed = () => {
    if (!canRun()) return pause();
    failureCount += 1;
    if (failureCount > maxSseFailures) {
      transition("degraded_polling");
      schedulePoll(0);
      return;
    }
    transition("reconnecting");
    const exponentialDelay = Math.min(maxDelayMs, baseDelayMs * 2 ** (failureCount - 1));
    const jitteredDelay = Math.min(maxDelayMs, Math.round(exponentialDelay * (0.5 + random())));
    schedule(connect, jitteredDelay);
  };

  return {
    start() {
      active = true;
      pollInFlight = false;
      pollCount = 0;
      clearScheduledWork();
      connect();
    },
    stop() {
      active = false;
      pollInFlight = false;
      failureCount = 0;
      pollCount = 0;
      pause();
    },
    reconcile() {
      if (!active || !isEligible()) return pause();
      if (pollInFlight) return;
      if (currentState === "idle") connect();
    },
    sseOpened() {
      if (!canRun()) return pause();
      clearScheduledWork();
      pollCount = 0;
      transition("connected");
    },
    sseHealthyEvent() {
      if (!canRun()) return;
      failureCount = 0;
    },
    sseFailed,
    state: () => currentState,
    failures: () => failureCount,
  };
}
