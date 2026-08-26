const ALLOWED_DELTA_FIELDS = new Set([
  "role",
  "content",
  "tool_calls",
  "function_call",
  "reasoning_content",
]);

const CHAT_COMPLETION_CHUNK_ERROR_CODES = new Set([
  "stream_chunk_invalid",
  "stream_provider_error",
  "stream_choice_count_invalid",
  "stream_choice_invalid",
  "stream_choice_index_invalid",
  "stream_delta_invalid",
  "stream_tool_call_forbidden",
  "stream_function_call_forbidden",
  "stream_role_invalid",
  "stream_delta_extension_unsupported",
  "stream_content_invalid",
  "stream_reasoning_content_invalid",
  "stream_finish_reason_invalid",
  "stream_response_bytes_exceeded",
  "stream_chunk_after_terminal",
  "stream_terminal_missing",
  "stream_content_missing",
]);

export function isChatCompletionChunkErrorCode(value: string): boolean {
  return CHAT_COMPLETION_CHUNK_ERROR_CODES.has(value);
}

export interface NormalizedChatCompletionChunk {
  readonly providerTraceId: unknown;
  readonly content: string | null;
  readonly finishReason: "stop" | null;
  readonly responseBytes: number;
}

export function normalizeChatCompletionChunk(
  value: unknown,
): NormalizedChatCompletionChunk {
  if (!isRecord(value)) {
    throw chunkFailure("agent_provider_transport_failed", "stream_chunk_invalid");
  }
  if (value.error !== undefined && value.error !== null) {
    throw chunkFailure("agent_provider_transport_failed", "stream_provider_error");
  }
  if (!Array.isArray(value.choices) || value.choices.length !== 1) {
    throw chunkFailure(
      "agent_provider_transport_failed",
      "stream_choice_count_invalid",
    );
  }
  const choice = value.choices[0];
  if (!isRecord(choice)) {
    throw chunkFailure("agent_provider_transport_failed", "stream_choice_invalid");
  }
  if (choice.index !== undefined && choice.index !== 0) {
    throw chunkFailure(
      "agent_provider_transport_failed",
      "stream_choice_index_invalid",
    );
  }
  if (!isRecord(choice.delta)) {
    throw chunkFailure("agent_provider_transport_failed", "stream_delta_invalid");
  }
  const delta = choice.delta;
  if (delta.tool_calls !== undefined && delta.tool_calls !== null) {
    throw chunkFailure("agent_model_capability_mismatch", "stream_tool_call_forbidden");
  }
  if (delta.function_call !== undefined && delta.function_call !== null) {
    throw chunkFailure(
      "agent_model_capability_mismatch",
      "stream_function_call_forbidden",
    );
  }
  if (delta.role !== undefined && delta.role !== "assistant") {
    throw chunkFailure("agent_provider_transport_failed", "stream_role_invalid");
  }
  if (
    Object.entries(delta).some(
      ([key, child]) =>
        !ALLOWED_DELTA_FIELDS.has(key) && child !== undefined && child !== null,
    )
  ) {
    throw chunkFailure(
      "agent_provider_transport_failed",
      "stream_delta_extension_unsupported",
    );
  }
  if (
    delta.content !== undefined &&
    delta.content !== null &&
    typeof delta.content !== "string"
  ) {
    throw chunkFailure("agent_provider_transport_failed", "stream_content_invalid");
  }
  if (
    delta.reasoning_content !== undefined &&
    delta.reasoning_content !== null &&
    typeof delta.reasoning_content !== "string"
  ) {
    throw chunkFailure(
      "agent_provider_transport_failed",
      "stream_reasoning_content_invalid",
    );
  }
  if (
    choice.finish_reason !== undefined &&
    choice.finish_reason !== null &&
    choice.finish_reason !== "stop"
  ) {
    throw chunkFailure(
      "agent_provider_transport_failed",
      "stream_finish_reason_invalid",
    );
  }
  const content = typeof delta.content === "string" ? delta.content : null;
  const reasoning =
    typeof delta.reasoning_content === "string" ? delta.reasoning_content : null;
  return {
    providerTraceId: value.id,
    content,
    finishReason: choice.finish_reason === "stop" ? "stop" : null,
    responseBytes:
      Buffer.byteLength(content ?? "", "utf8") +
      Buffer.byteLength(reasoning ?? "", "utf8"),
  };
}

export function chatCompletionChunkFailure(
  code: string,
  internalErrorCode: string,
): Error {
  return chunkFailure(code, internalErrorCode);
}

function chunkFailure(code: string, internalErrorCode: string): Error {
  return Object.assign(new Error(code), {
    code,
    internal_error_code: internalErrorCode,
    attempt_stage: "stream_chunk_normalization",
  });
}

function isRecord(value: unknown): value is Readonly<Record<string, unknown>> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
