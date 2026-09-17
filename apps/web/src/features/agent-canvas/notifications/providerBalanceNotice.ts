import { isV2ApiError } from "../../../api/agentCanvasApi.ts";
import type {
  CanvasNodeErrorV2,
  CanvasRuntimeEventV2,
} from "../../../types-v2.ts";

/**
 * One "the provider credential cannot pay" notice.
 *
 * The backend folds provider billing failures into generic codes and only the
 * provider's own message survives to the client, so the detector reads both the
 * error code and the message text.
 */
export interface ProviderBalanceNotice {
  providerId: string | null;
  providerLabel: string;
  detail: string | null;
  /** Identity used to show at most one notice per provider in a session. */
  dedupeKey: string;
}

const PROVIDER_LABELS: Record<string, string> = {
  volcengine_ark: "火山方舟",
  openrouter: "OpenRouter",
  siliconflow: "SiliconFlow",
  minimax: "MiniMax",
  tianpuyue: "天谱乐",
  openai: "OpenAI",
};

const UNKNOWN_PROVIDER_LABEL = "模型供应商";

/** Already-emitted codes that mean "this credential has no funds left". */
const BALANCE_ERROR_CODES = new Set([
  "providerinsufficientbalance",
  "insufficientquota",
  "insufficientbalance",
  "accountoverdue",
  "accountoverdueerror",
  "accountarrears",
  "quotaexhausted",
  "bgmproviderquotaexhausted",
  "bgmquotaerror",
]);

const BALANCE_TEXT_PATTERNS: readonly RegExp[] = [
  /insufficient\s+(?:account\s+)?(?:balance|credit|credits|funds|quota)/i,
  /(?:balance|credits?|funds)\s+(?:is|are)\s+(?:not\s+enough|insufficient|exhausted)/i,
  /not\s+enough\s+(?:balance|credits?|funds)/i,
  /out\s+of\s+credits?/i,
  /arrears/i,
  /account\s+(?:is\s+)?(?:in\s+arrears|overdue)/i,
  /exceeded\s+your\s+current\s+quota/i,
  /check\s+your\s+plan\s+and\s+billing/i,
  /(?:recharge|top\s+up)\s+(?:your|the)\s+account/i,
  /余额不足/,
  /欠费/,
  /账户余额/,
  /可用额度不足/,
];

const DETAIL_LIMIT = 320;

function normalizeCode(value: string | null | undefined): string {
  return (value ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function readString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function boundedDetail(value: string | null): string | null {
  if (!value) return null;
  const collapsed = value.replace(/\s+/g, " ").trim();
  if (!collapsed) return null;
  return collapsed.length > DETAIL_LIMIT ? `${collapsed.slice(0, DETAIL_LIMIT - 1)}…` : collapsed;
}

export function providerIdFromModelRef(modelRef: string | null | undefined): string | null {
  const normalized = readString(modelRef);
  if (!normalized) return null;
  const separator = normalized.indexOf(":");
  return separator > 0 ? normalized.slice(0, separator) : null;
}

export function providerLabelFor(providerId: string | null): string {
  if (!providerId) return UNKNOWN_PROVIDER_LABEL;
  return PROVIDER_LABELS[providerId] ?? providerId;
}

function noticeFor(providerId: string | null, detail: string | null): ProviderBalanceNotice {
  return {
    providerId,
    providerLabel: providerLabelFor(providerId),
    detail: boundedDetail(detail),
    dedupeKey: `provider-balance:${providerId ?? "unknown"}`,
  };
}

export function providerBalanceNoticeFromSignal({
  code,
  text,
  providerId = null,
}: {
  code?: string | null;
  text?: string | null;
  providerId?: string | null;
}): ProviderBalanceNotice | null {
  const normalizedCode = normalizeCode(code);
  if (normalizedCode && BALANCE_ERROR_CODES.has(normalizedCode)) {
    return noticeFor(providerId, text ?? null);
  }
  const message = readString(text);
  if (message && BALANCE_TEXT_PATTERNS.some((pattern) => pattern.test(message))) {
    return noticeFor(providerId, message);
  }
  return null;
}

export function providerBalanceNoticeFromText(
  text: string | null | undefined,
  providerId: string | null = null,
): ProviderBalanceNotice | null {
  return providerBalanceNoticeFromSignal({ text, providerId });
}

export function providerBalanceNoticeFromCode(
  code: string | null | undefined,
  providerId: string | null = null,
  detail: string | null = null,
): ProviderBalanceNotice | null {
  return providerBalanceNoticeFromSignal({ code, text: detail, providerId });
}

export function providerBalanceNoticeFromError(error: unknown): ProviderBalanceNotice | null {
  if (isV2ApiError(error)) {
    if (error.status === 402) {
      return noticeFor(null, readString(error.message));
    }
    return providerBalanceNoticeFromSignal({ code: error.code, text: error.message });
  }
  if (error instanceof Error) {
    return providerBalanceNoticeFromSignal({ text: error.message });
  }
  return null;
}

type ProviderBalanceNodeSource = {
  error?: CanvasNodeErrorV2 | null;
  latest_attempt?: { error?: CanvasNodeErrorV2 | null } | null;
  prompt_preparation?: { error?: CanvasNodeErrorV2 | null } | null;
  model_ref?: string | null;
  model_summary?: { provider_id?: string | null } | null;
};

function noticeFromNodeError(
  error: CanvasNodeErrorV2 | null | undefined,
  providerId: string | null,
): ProviderBalanceNotice | null {
  if (!error) return null;
  return providerBalanceNoticeFromSignal({
    code: error.code,
    text: error.message,
    providerId,
  });
}

export function providerBalanceNoticeFromNode(
  node: ProviderBalanceNodeSource,
): ProviderBalanceNotice | null {
  const providerId = providerIdFromNode(node);
  return noticeFromNodeError(node.error, providerId)
    ?? noticeFromNodeError(node.latest_attempt?.error, providerId)
    ?? noticeFromNodeError(node.prompt_preparation?.error, providerId);
}

export function providerIdFromNode(node: ProviderBalanceNodeSource): string | null {
  return readString(node.model_summary?.provider_id) ?? providerIdFromModelRef(node.model_ref);
}

/** Detector for the live runtime projection of one node. */
export function providerBalanceNoticeFromNodeRuntime(
  node: ProviderBalanceNodeSource,
  runtimeError: CanvasNodeErrorV2 | null | undefined,
): ProviderBalanceNotice | null {
  return noticeFromNodeError(runtimeError, providerIdFromNode(node));
}

const FAILURE_EVENT_TYPES = new Set([
  "agent_command_failed",
  "agent_operation_failed",
  "agent_turn_failed",
  "continuation_failed",
  "expert_activity_failed",
  "guided_product_source_failed",
  "journey_stage_failed",
  "node_prompt_preparation_failed",
  "provider_result_download_failed",
  "provider_task_failed",
]);

function eventCarriesFailure(event: CanvasRuntimeEventV2): boolean {
  if (FAILURE_EVENT_TYPES.has(event.event_type)) return true;
  if (event.event_type === "node_status_changed") {
    return readString(event.payload?.status) === "failed";
  }
  return /(?:^|_)(?:failed|error|exhausted)$/.test(event.event_type);
}

export function providerBalanceNoticeFromRuntimeEvent(
  event: CanvasRuntimeEventV2,
): ProviderBalanceNotice | null {
  const payload = event.payload ?? {};
  const code = readString(payload.error_code) ?? readString(payload.code);
  const text = readString(payload.error_message)
    ?? readString(payload.error)
    ?? readString(payload.message)
    ?? readString(payload.detail);
  const knownCode = Boolean(code && BALANCE_ERROR_CODES.has(normalizeCode(code)));
  if (!knownCode && !eventCarriesFailure(event)) return null;
  const providerId = readString(payload.provider)
    ?? readString(payload.provider_id)
    ?? providerIdFromModelRef(readString(payload.model_ref));
  return providerBalanceNoticeFromSignal({ code, text, providerId });
}
