import type { AgentTransportAttemptMetadataV1 } from "./generated/agent-runtime.js";

export interface AgentTransportClassification {
  readonly code: "agent_provider_transport_failed" | "agent_provider_insufficient_balance";
  readonly retryable: boolean;
  readonly retryAfterMs: number;
}

interface TransportFailureShape {
  readonly code?: unknown;
  readonly status?: unknown;
  readonly statusCode?: unknown;
  readonly message?: unknown;
  readonly retryAfterSeconds?: unknown;
  readonly response?: {
    readonly status?: unknown;
    readonly headers?: { readonly get?: (name: string) => string | null };
  };
  readonly cause?: unknown;
  readonly error?: { readonly code?: unknown; readonly type?: unknown };
}

export const PROVIDER_INSUFFICIENT_BALANCE_MESSAGE =
  "The Agent provider has insufficient balance or credits. Please top up your account or switch to another model provider.";

const BILLING_ERROR_CODES = new Set([
  "insufficient_balance",
  "insufficient_quota",
  "credit_balance_too_low",
  "billing_hard_limit_reached",
]);

export function isProviderBalanceFailure(candidate: unknown): boolean {
  let current = candidate;
  for (let depth = 0; depth < 4 && current; depth += 1) {
    const error = asFailureShape(current);
    if (numberValue(error.status ?? error.statusCode ?? error.response?.status) === 402) return true;
    if ([error.code, error.error?.code, error.error?.type].some(
      (code) => typeof code === "string" && BILLING_ERROR_CODES.has(code.toLowerCase()),
    )) return true;
    current = error.cause;
  }
  return false;
}

const RETRYABLE_CODES = new Set([
  "ECONNRESET",
  "ECONNREFUSED",
  "ETIMEDOUT",
  "EAI_AGAIN",
  "ENOTFOUND",
  "ERR_SSL_UNEXPECTED_EOF_WHILE_READING",
]);
const RETRYABLE_STATUSES = new Set([502, 503, 504]);
const RETRYABLE_MESSAGES = [
  "connection reset",
  "remote disconnect",
  "socket hang up",
  "tls eof",
  "unexpected eof",
  "dns lookup",
  "connect failed",
];

export class AgentOperationFailure extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly retryable: boolean,
    readonly attemptStage:
      | "initial"
      | "transport_retry"
      | "capability_fallback"
      | "structured_repair" =
      "initial",
    readonly attemptMetadata?: AgentTransportAttemptMetadataV1,
  ) {
    super(message);
  }
}

export function classifyAgentTransportFailure(
  candidate: unknown,
): AgentTransportClassification {
  if (isProviderBalanceFailure(candidate)) {
    return { code: "agent_provider_insufficient_balance", retryable: false, retryAfterMs: 0 };
  }
  const error = asFailureShape(candidate);
  const cause = asFailureShape(error.cause);
  const code = String(error.code ?? cause.code ?? "").toUpperCase();
  const status = numberValue(
    error.status ?? error.statusCode ?? error.response?.status,
  );
  const message = String(error.message ?? cause.message ?? candidate ?? "").toLowerCase();
  const retryAfterSeconds = numberValue(error.retryAfterSeconds) ??
    retryAfterHeader(error.response?.headers);
  const retryable =
    RETRYABLE_CODES.has(code) ||
    (status !== undefined && RETRYABLE_STATUSES.has(status)) ||
    RETRYABLE_MESSAGES.some((part) => message.includes(part)) ||
    (status === 429 && retryAfterSeconds !== undefined);
  return {
    code: "agent_provider_transport_failed",
    retryable,
    retryAfterMs: Math.max(0, (retryAfterSeconds ?? 0.25) * 1_000),
  };
}

export async function runWithOneTransportRetry<T>(
  operation: (stage: "initial" | "transport_retry") => Promise<T>,
  options: {
    readonly deadlineEpochMs: number;
    readonly now?: () => number;
    readonly sleep?: (milliseconds: number) => Promise<void>;
    readonly canRetry?: () => boolean;
  },
): Promise<T> {
  const now = options.now ?? Date.now;
  const sleep = options.sleep ?? ((milliseconds) => new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  }));
  for (let attempt = 0; attempt < 2; attempt += 1) {
    if (now() >= options.deadlineEpochMs) {
      throw new AgentOperationFailure(
        "agent_deadline_exceeded",
        "Agent operation deadline exceeded.",
        false,
        attempt === 0 ? "initial" : "transport_retry",
      );
    }
    try {
      return await operation(attempt === 0 ? "initial" : "transport_retry");
    } catch (error) {
      const providerTimeout = isProviderTimeoutFailure(error) ||
        (error instanceof AgentOperationFailure &&
          error.code === "agent_provider_timeout");
      if (error instanceof AgentOperationFailure &&
        !(providerTimeout && error.retryable)) throw error;
      if (
        error instanceof Error &&
        error.message === "agent_structured_output_invalid"
      ) {
        throw new AgentOperationFailure(
          error.message,
          "Agent structured output remained invalid after repair.",
          false,
          "structured_repair",
        );
      }
      const classification = providerTimeout
        ? {
            code: "agent_provider_transport_failed" as const,
            retryable: attempt === 0 && !responseActivityObserved(error),
            retryAfterMs: 250,
          }
        : classifyAgentTransportFailure(error);
      const retryStage = attempt === 0 ? "initial" : "transport_retry";
      const remainingMs = Math.max(0, options.deadlineEpochMs - now());
      if (
        attempt >= 1 ||
        options.canRetry?.() === false ||
        !classification.retryable ||
        classification.retryAfterMs >= remainingMs
      ) {
        throw new AgentOperationFailure(
          providerTimeout ? "agent_provider_timeout" : classification.code,
          providerTimeout
            ? "Agent provider request timed out."
            : classification.code === "agent_provider_insufficient_balance"
            ? PROVIDER_INSUFFICIENT_BALANCE_MESSAGE
            : "Agent model transport failed.",
          false,
          retryStage,
        );
      }
      await sleep(classification.retryAfterMs);
    }
  }
  throw new AgentOperationFailure(
    "agent_provider_transport_failed",
    "Agent model transport failed.",
    false,
    "transport_retry",
  );
}

function responseActivityObserved(candidate: unknown): boolean {
  if (candidate instanceof AgentOperationFailure) {
    return candidate.attemptMetadata?.response_activity_observed === true;
  }
  if (!candidate || typeof candidate !== "object") return false;
  const error = candidate as {
    readonly response_started?: unknown;
    readonly response?: { readonly status?: unknown };
  };
  return error.response_started === true ||
    numberValue(error.response?.status) !== undefined;
}

export function isProviderTimeoutFailure(candidate: unknown): boolean {
  let current: unknown = candidate;
  for (let depth = 0; depth < 4; depth += 1) {
    if (!current || typeof current !== "object") return false;
    const error = current as {
      readonly name?: unknown;
      readonly cause?: unknown;
      readonly constructor?: { readonly name?: unknown };
    };
    const names = new Set([
      String(error.name ?? ""),
      String(error.constructor?.name ?? ""),
    ]);
    if (
      names.has("APIConnectionTimeoutError") ||
      names.has("APITimeoutError") ||
      names.has("TimeoutError") ||
      (names.has("AbortError") && depth > 0)
    ) {
      return true;
    }
    current = error.cause;
  }
  return false;
}

function asFailureShape(candidate: unknown): TransportFailureShape {
  return candidate && typeof candidate === "object"
    ? (candidate as TransportFailureShape)
    : { message: candidate };
}

function numberValue(candidate: unknown): number | undefined {
  const value = typeof candidate === "number" ? candidate : Number(candidate);
  return Number.isFinite(value) ? value : undefined;
}

function retryAfterHeader(
  headers: TransportFailureShape["response"] extends infer _T
    ? { readonly get?: (name: string) => string | null } | undefined
    : never,
): number | undefined {
  const value = headers?.get?.("retry-after");
  return value === null || value === undefined ? undefined : numberValue(value);
}
