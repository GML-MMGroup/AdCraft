import { createHash } from "node:crypto";
import { mkdir, rename, writeFile } from "node:fs/promises";
import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { join } from "node:path";

import { Ajv2020 } from "ajv/dist/2020.js";

import {
  buildPrimaryStructuredCompletionRequest,
  canonicalRequestSha256,
  executeOpenAICompletion,
  PiStructuredTransportRouter,
  type StructuredCompletionExecutor,
  type StructuredCompletionRequest,
  type StructuredCompletionResponse,
} from "./pi-structured-transport.js";
import type { AgentCredentialSnapshot } from "./python-internal-client.js";
import type { PreparedStructuredModelInput } from "./structured-model-input.js";

export type ConformanceCaseId =
  | "minimal_json"
  | "production_prompt_only"
  | "production_schema_only"
  | "production_exact_raw"
  | "production_exact_streaming"
  | "production_exact_sdk"
  | "production_exact_pi"
  | "reduced_prompt"
  | "reduced_schema"
  | "reduced_combined";

export type ConformanceVerdict =
  | "verified"
  | "blocked_external"
  | "prompt_overload"
  | "schema_incompatible"
  | "prompt_schema_interaction"
  | "sdk_incompatible"
  | "pi_transport_incompatible";

export type ConformanceTransport =
  | "raw_non_streaming"
  | "raw_streaming"
  | "openai_sdk"
  | "pi_structured_transport";

export interface ConformanceCaseResultV1 {
  readonly case_id: ConformanceCaseId;
  readonly transport: ConformanceTransport;
  readonly status: "succeeded" | "failed" | "timed_out" | "aborted";
  readonly request_sha256: string;
  readonly request_bytes: number;
  readonly schema_bytes: number;
  readonly transport_completed: boolean;
  readonly json_parsed: boolean;
  readonly contract_valid: boolean;
  readonly response_activity_observed: boolean | null;
  readonly dns_at: string | null;
  readonly tcp_at: string | null;
  readonly tls_at: string | null;
  readonly dispatched_at: string;
  readonly response_headers_at: string | null;
  readonly first_content_at: string | null;
  readonly completed_at: string;
  readonly duration_ms: number;
  readonly http_status: number | null;
  readonly provider_request_id: string | null;
  readonly safe_error: Readonly<Record<string, string | number | boolean | null>> | null;
  readonly changed_fields: ReadonlyArray<string>;
}

export type ConformanceBlockedStage =
  | "credential"
  | "request_preparation"
  | "request_parity";

export interface ConformanceReportV2 {
  readonly schema_version: 2;
  readonly run_id: string;
  readonly status: "completed" | "blocked";
  readonly blocked_stage: ConformanceBlockedStage | null;
  readonly operation: string;
  readonly provider: string;
  readonly model_ref: string;
  readonly started_at: string;
  readonly completed_at: string;
  readonly production_request_sha256: string;
  readonly production_request_bytes: number;
  readonly production_schema_bytes: number;
  readonly frozen_agent_request_digest?: string;
  readonly prompt_digest?: string;
  readonly contract_schema_digest?: string;
  readonly model_policy_digest?: string;
  readonly semantic_request_digest?: string;
  readonly contract_name?: string;
  readonly contract_version?: string;
  readonly prompt_bytes?: number;
  readonly contract_schema_bytes?: number;
  readonly semantic_request_bytes?: number;
  readonly maximum_submissions: 6;
  readonly submission_count: number;
  readonly cases: ReadonlyArray<ConformanceCaseResultV1>;
  readonly verdict: ConformanceVerdict | null;
  readonly operator_error_code?: string;
}

export interface ConformanceRunOptions {
  readonly run_id: string;
  readonly operation: "decide_turn_intent";
  readonly model_ref: string;
  readonly output_directory: string;
  readonly per_case_timeout_ms?: number;
  readonly total_timeout_ms?: number;
  readonly maximum_submissions?: number;
}

export interface ProductionRequestDigestsV1 {
  readonly frozen_agent_request_digest: string;
  readonly prompt_digest: string;
  readonly contract_schema_digest: string;
  readonly model_policy_digest: string;
  readonly semantic_request_digest: string;
  readonly contract_name: string;
  readonly contract_version: string;
  readonly prompt_bytes: number;
  readonly contract_schema_bytes: number;
  readonly semantic_request_bytes: number;
}

export function productionRequestDigests(
  prepared: PreparedStructuredModelInput,
): ProductionRequestDigestsV1 {
  if (!prepared.request.contract_name) throw new Error("conformance_parity_failed");
  const providerRequest = buildPrimaryStructuredCompletionRequest(prepared);
  const prompt = {
    system_prompt: prepared.systemPrompt,
    user_prompt: prepared.userPrompt,
  };
  return {
    frozen_agent_request_digest: `sha256:${requestSha256(prepared.request)}`,
    prompt_digest: requestSha256(prompt),
    contract_schema_digest: requestSha256(prepared.schema),
    model_policy_digest: requestSha256(prepared.credential.execution_policy),
    semantic_request_digest: canonicalRequestSha256(providerRequest),
    contract_name: prepared.request.contract_name,
    contract_version: prepared.request.protocol_version ?? "1",
    prompt_bytes: byteCount(prompt),
    contract_schema_bytes: byteCount(prepared.schema),
    semantic_request_bytes: byteCount(providerRequest),
  };
}

export interface ReducedCaseSelection {
  readonly case_id: "reduced_prompt" | "reduced_schema" | "reduced_combined";
  readonly changed_fields: ReadonlyArray<"system_prompt" | "user_prompt" | "schema">;
}

export interface ConformanceExecutionInput {
  readonly caseId: ConformanceCaseId;
  readonly request: StructuredCompletionRequest | Readonly<Record<string, unknown>>;
  readonly signal: AbortSignal;
  readonly timeoutMs: number;
}

export interface ConformanceExecutionObservation {
  readonly transport_completed: boolean;
  readonly content?: string | null;
  readonly response_activity_observed: boolean | null;
  readonly dns_at: string | null;
  readonly tcp_at: string | null;
  readonly tls_at: string | null;
  readonly response_headers_at: string | null;
  readonly first_content_at: string | null;
  readonly completed_at: string;
  readonly http_status: number | null;
  readonly provider_request_id: string | null;
  readonly safe_error: Readonly<Record<string, string | number | boolean | null>> | null;
}

export type ConformanceExecutor = (
  input: ConformanceExecutionInput,
) => Promise<ConformanceExecutionObservation>;

export interface RawHttpResponseObservation {
  readonly status: number;
  readonly headers: Readonly<Record<string, string | undefined>>;
  readonly content: string | null;
  readonly dns_at: string | null;
  readonly tcp_at: string | null;
  readonly tls_at: string | null;
  readonly response_headers_at: string | null;
  readonly first_content_at: string | null;
  readonly completed_at: string;
}

export type RawHttpSender = (input: {
  readonly url: string;
  readonly apiKey: string;
  readonly payload: Readonly<Record<string, unknown>>;
  readonly signal: AbortSignal;
  readonly maximumResponseBytes: number;
}) => Promise<RawHttpResponseObservation>;

export interface ConformanceDependencies {
  readonly prepared: PreparedStructuredModelInput;
  readonly rawNonStreaming: ConformanceExecutor;
  readonly rawStreaming: ConformanceExecutor;
  readonly sdk: ConformanceExecutor;
  readonly pi: ConformanceExecutor;
  readonly now?: () => Date;
}

interface CaseDefinition {
  readonly caseId: ConformanceCaseId;
  readonly transport: ConformanceTransport;
  readonly executor: ConformanceExecutor;
  readonly request: StructuredCompletionRequest | Readonly<Record<string, unknown>>;
  readonly schema: Readonly<Record<string, unknown>>;
  readonly changedFields: ReadonlyArray<string>;
}

const MINIMAL_SCHEMA = Object.freeze({
  type: "object",
  additionalProperties: false,
  properties: { ok: { type: "boolean" } },
  required: ["ok"],
});
const ANY_OBJECT_SCHEMA = Object.freeze({ type: "object" });

export function createRawConformanceExecutor(
  credential: AgentCredentialSnapshot,
  options: { readonly send?: RawHttpSender } = {},
): ConformanceExecutor {
  const send = options.send ?? sendRawHttpRequest;
  return async (input) => {
    const response = await send({
      url: completionUrl(credential.base_url),
      apiKey: credential.api_key,
      payload: input.request as Readonly<Record<string, unknown>>,
      signal: input.signal,
      maximumResponseBytes: 1_048_576,
    });
    return {
      transport_completed: true,
      content: response.content,
      response_activity_observed: true,
      dns_at: response.dns_at,
      tcp_at: response.tcp_at,
      tls_at: response.tls_at,
      response_headers_at: response.response_headers_at,
      first_content_at: response.first_content_at,
      completed_at: response.completed_at,
      http_status: response.status,
      provider_request_id: boundedHeader(
        response.headers["x-request-id"] ?? response.headers["request-id"],
      ),
      safe_error:
        response.status >= 200 && response.status < 300
          ? null
          : {
              code: "conformance_provider_http_error",
              http_status: response.status,
            },
    };
  };
}

export function createSdkConformanceExecutor(
  credential: AgentCredentialSnapshot,
  execute: StructuredCompletionExecutor = executeOpenAICompletion,
): ConformanceExecutor {
  return async (input) =>
    terminalObservation(
      await execute(input.request as unknown as StructuredCompletionRequest, {
        apiKey: credential.api_key,
        baseUrl: credential.base_url,
        signal: input.signal,
        timeoutMs: input.timeoutMs,
      }),
    );
}

export function createPiConformanceExecutor(
  prepared: PreparedStructuredModelInput,
  execute: StructuredCompletionExecutor = executeOpenAICompletion,
): ConformanceExecutor {
  return async (input) => {
    const primarySeconds = Math.max(1, Math.ceil(input.timeoutMs / 1_000));
    const policy = {
      ...prepared.credential.execution_policy,
      deadline_seconds: primarySeconds + 2,
      primary_timeout_seconds: primarySeconds,
      recovery_timeout_seconds: 1,
      persistence_reserve_seconds: 1,
      transport_retry_limit: 0,
      structured_repair_limit: 0,
    };
    const router = new PiStructuredTransportRouter({ execute });
    const result = await router.run({
      credential: { ...prepared.credential, execution_policy: policy },
      request: {
        ...prepared.request,
        deadline_at: new Date(Date.now() + input.timeoutMs + 2_000).toISOString(),
        policy: {
          ...prepared.request.policy,
          timeout_seconds: policy.deadline_seconds,
          primary_timeout_seconds: policy.primary_timeout_seconds,
          recovery_timeout_seconds: policy.recovery_timeout_seconds,
          persistence_reserve_seconds: policy.persistence_reserve_seconds,
          transport_retry_limit: 0,
          structured_repair_limit: 0,
        },
      },
      systemPrompt: prepared.systemPrompt,
      userPrompt: prepared.userPrompt,
      schema: prepared.schema,
      signal: input.signal,
      submit: async (value) =>
        validate(prepared.schema, value)
          ? { status: "completed", result: { accepted: true, value } }
          : {
              status: "failed",
              error_code: "agent_contract_validation_failed",
              result: { accepted: false },
            },
    });
    return {
      transport_completed: true,
      content: JSON.stringify(result.value),
      response_activity_observed: true,
      dns_at: null,
      tcp_at: null,
      tls_at: null,
      response_headers_at: null,
      first_content_at: result.audit.first_response_at ?? null,
      completed_at: result.audit.finished_at,
      http_status: 200,
      provider_request_id: result.audit.provider_trace_id ?? null,
      safe_error: null,
    };
  };
}

export async function runProviderConformance(
  options: ConformanceRunOptions,
  dependencies: ConformanceDependencies,
): Promise<ConformanceReportV2> {
  const perCaseTimeoutMs = boundedLimit(options.per_case_timeout_ms, 60_000, 60_000);
  const totalTimeoutMs = boundedLimit(options.total_timeout_ms, 360_000, 360_000);
  const maximumSubmissions = boundedLimit(options.maximum_submissions, 6, 6);
  const now = dependencies.now ?? (() => new Date());
  const startedAt = now();
  const runId = options.run_id;
  const exactRequest = buildPrimaryStructuredCompletionRequest(dependencies.prepared);
  const digests = productionRequestDigests(dependencies.prepared);
  const exactRequestBytes = byteCount(exactRequest);
  const exactSchemaBytes = byteCount(dependencies.prepared.schema);
  const deadlineAt = startedAt.getTime() + totalTimeoutMs;
  const results: ConformanceCaseResultV1[] = [];

  const executeCase = async (definition: CaseDefinition): Promise<ConformanceCaseResultV1> => {
    if (results.length >= maximumSubmissions || Date.now() >= deadlineAt) {
      return budgetFailure(definition, now());
    }
    const remainingMs = Math.max(1, deadlineAt - Date.now());
    const timeoutMs = Math.min(perCaseTimeoutMs, remainingMs);
    const dispatchedAt = now();
    const controller = new AbortController();
    const timer = setTimeout(
      () => controller.abort(new DOMException("Diagnostic deadline reached", "TimeoutError")),
      timeoutMs,
    );
    let observation: ConformanceExecutionObservation;
    try {
      observation = await definition.executor({
        caseId: definition.caseId,
        request: definition.request,
        signal: controller.signal,
        timeoutMs,
      });
    } catch (error) {
      const completedAt = now();
      const timedOut = controller.signal.aborted;
      observation = {
        transport_completed: false,
        response_activity_observed: null,
        dns_at: null,
        tcp_at: null,
        tls_at: null,
        response_headers_at: null,
        first_content_at: null,
        completed_at: completedAt.toISOString(),
        http_status: null,
        provider_request_id: null,
        safe_error: safeError(error, timedOut ? "conformance_case_timeout" : "conformance_transport_failed"),
      };
    } finally {
      clearTimeout(timer);
    }
    const parsed = parseJsonObject(observation.content);
    const contractValid = parsed !== undefined && validate(definition.schema, parsed);
    const completedAt = new Date(observation.completed_at);
    const status = controller.signal.aborted
      ? "timed_out"
      : observation.transport_completed && isSuccessStatus(observation.http_status) && contractValid
        ? "succeeded"
        : "failed";
    return {
      case_id: definition.caseId,
      transport: definition.transport,
      status,
      request_sha256: requestSha256(definition.request),
      request_bytes: byteCount(definition.request),
      schema_bytes: byteCount(definition.schema),
      transport_completed: observation.transport_completed,
      json_parsed: parsed !== undefined,
      contract_valid: contractValid,
      response_activity_observed: observation.response_activity_observed,
      dns_at: observation.dns_at,
      tcp_at: observation.tcp_at,
      tls_at: observation.tls_at,
      dispatched_at: dispatchedAt.toISOString(),
      response_headers_at: observation.response_headers_at,
      first_content_at: observation.first_content_at,
      completed_at: observation.completed_at,
      duration_ms: Math.max(0, completedAt.getTime() - dispatchedAt.getTime()),
      http_status: observation.http_status,
      provider_request_id: observation.provider_request_id,
      safe_error: observation.safe_error,
      changed_fields: definition.changedFields,
    };
  };

  const run = async (definition: CaseDefinition): Promise<ConformanceCaseResultV1> => {
    const value = await executeCase(definition);
    results.push(value);
    return value;
  };

  const mandatory = mandatoryCases(dependencies, exactRequest);
  const minimal = await run(mandatory[0]);
  if (succeeded(minimal)) {
    await run(mandatory[1]);
    await run(mandatory[2]);
    const exact = await run(mandatory[3]);
    if (succeeded(exact)) {
      const sdk = await run({
        caseId: "production_exact_sdk",
        transport: "openai_sdk",
        executor: dependencies.sdk,
        request: exactRequest,
        schema: dependencies.prepared.schema,
        changedFields: [],
      });
      if (succeeded(sdk)) {
        await run({
          caseId: "production_exact_pi",
          transport: "pi_structured_transport",
          executor: dependencies.pi,
          request: exactRequest,
          schema: dependencies.prepared.schema,
          changedFields: [],
        });
      }
    } else {
      await run({
        caseId: "production_exact_streaming",
        transport: "raw_streaming",
        executor: dependencies.rawStreaming,
        request: { ...exactRequest, stream: true },
        schema: dependencies.prepared.schema,
        changedFields: ["stream"],
      });
      const selection = selectReducedCase(results);
      await run(reducedCase(selection, dependencies, exactRequest));
    }
  }

  const completedAt = now().toISOString();
  return {
    schema_version: 2,
    run_id: runId,
    status: "completed",
    blocked_stage: null,
    operation: options.operation,
    provider: dependencies.prepared.credential.provider,
    model_ref: options.model_ref,
    started_at: startedAt.toISOString(),
    completed_at: completedAt,
    production_request_sha256: canonicalRequestSha256(exactRequest),
    production_request_bytes: exactRequestBytes,
    production_schema_bytes: exactSchemaBytes,
    ...digests,
    maximum_submissions: 6,
    submission_count: results.length,
    cases: results,
    verdict: classifyConformance(results),
  };
}

export function projectConformanceEvidence(value: unknown): ConformanceReportV2 {
  const report = value as ConformanceReportV2;
  assertReportInvariants(report);
  return {
    schema_version: 2,
    run_id: report.run_id,
    status: report.status,
    blocked_stage: report.blocked_stage,
    operation: report.operation,
    provider: report.provider,
    model_ref: report.model_ref,
    started_at: report.started_at,
    completed_at: report.completed_at,
    production_request_sha256: report.production_request_sha256,
    production_request_bytes: report.production_request_bytes,
    production_schema_bytes: report.production_schema_bytes,
    ...(report.frozen_agent_request_digest
      ? { frozen_agent_request_digest: report.frozen_agent_request_digest }
      : {}),
    ...(report.prompt_digest ? { prompt_digest: report.prompt_digest } : {}),
    ...(report.contract_schema_digest
      ? { contract_schema_digest: report.contract_schema_digest }
      : {}),
    ...(report.model_policy_digest
      ? { model_policy_digest: report.model_policy_digest }
      : {}),
    ...(report.semantic_request_digest
      ? { semantic_request_digest: report.semantic_request_digest }
      : {}),
    ...(report.contract_name ? { contract_name: report.contract_name } : {}),
    ...(report.contract_version ? { contract_version: report.contract_version } : {}),
    ...(typeof report.prompt_bytes === "number"
      ? { prompt_bytes: report.prompt_bytes }
      : {}),
    ...(typeof report.contract_schema_bytes === "number"
      ? { contract_schema_bytes: report.contract_schema_bytes }
      : {}),
    ...(typeof report.semantic_request_bytes === "number"
      ? { semantic_request_bytes: report.semantic_request_bytes }
      : {}),
    maximum_submissions: 6,
    submission_count: report.submission_count,
    cases: report.cases.map(projectCaseEvidence),
    verdict: report.verdict,
    ...(isOperatorErrorCode(report.operator_error_code)
      ? { operator_error_code: report.operator_error_code }
      : {}),
  };
}

export async function writeConformanceEvidence(
  outputDirectory: string,
  value: unknown,
): Promise<void> {
  const report = projectConformanceEvidence(value);
  await mkdir(outputDirectory, { recursive: true });
  const suffix = `${process.pid}-${Date.now()}`;
  const jsonTemporary = join(outputDirectory, `.report.json.${suffix}.tmp`);
  const markdownTemporary = join(outputDirectory, `.report.md.${suffix}.tmp`);
  const jsonPath = join(outputDirectory, "report.json");
  const markdownPath = join(outputDirectory, "report.md");
  await writeFile(jsonTemporary, `${JSON.stringify(report, null, 2)}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
  await writeFile(markdownTemporary, renderMarkdown(report), {
    encoding: "utf8",
    mode: 0o600,
  });
  await rename(jsonTemporary, jsonPath);
  await rename(markdownTemporary, markdownPath);
}

function mandatoryCases(
  dependencies: ConformanceDependencies,
  exactRequest: StructuredCompletionRequest,
): readonly [CaseDefinition, CaseDefinition, CaseDefinition, CaseDefinition] {
  const base = exactRequestBase(exactRequest);
  const promptOnly = {
    ...base,
    messages: [
      { role: "system", content: dependencies.prepared.systemPrompt },
      { role: "user", content: dependencies.prepared.userPrompt },
    ],
    response_format: { type: "json_object" },
  };
  const schemaOnly = requestWithJsonSchema(
    base,
    "Return exactly one JSON object matching the supplied schema.",
    "Return the requested object.",
    dependencies.prepared.schema,
  );
  return [
    {
      caseId: "minimal_json",
      transport: "raw_non_streaming",
      executor: dependencies.rawNonStreaming,
      request: requestWithJsonSchema(
        base,
        "Return exactly one JSON object matching the supplied schema.",
        "Return an object whose ok field is true.",
        MINIMAL_SCHEMA,
      ),
      schema: MINIMAL_SCHEMA,
      changedFields: ["system_prompt", "user_prompt", "schema"],
    },
    {
      caseId: "production_prompt_only",
      transport: "raw_non_streaming",
      executor: dependencies.rawNonStreaming,
      request: promptOnly,
      schema: ANY_OBJECT_SCHEMA,
      changedFields: ["schema"],
    },
    {
      caseId: "production_schema_only",
      transport: "raw_non_streaming",
      executor: dependencies.rawNonStreaming,
      request: schemaOnly,
      schema: dependencies.prepared.schema,
      changedFields: ["system_prompt", "user_prompt"],
    },
    {
      caseId: "production_exact_raw",
      transport: "raw_non_streaming",
      executor: dependencies.rawNonStreaming,
      request: exactRequest,
      schema: dependencies.prepared.schema,
      changedFields: [],
    },
  ];
}

function reducedCase(
  selection: ReducedCaseSelection,
  dependencies: ConformanceDependencies,
  exactRequest: StructuredCompletionRequest,
): CaseDefinition {
  const base = exactRequestBase(exactRequest);
  if (selection.case_id === "reduced_prompt") {
    return {
      caseId: selection.case_id,
      transport: "raw_non_streaming",
      executor: dependencies.rawNonStreaming,
      request: requestWithJsonSchema(
        base,
        "Return one concise JSON object matching the supplied schema.",
        "Classify the request as guided production.",
        dependencies.prepared.schema,
      ),
      schema: dependencies.prepared.schema,
      changedFields: selection.changed_fields,
    };
  }
  if (selection.case_id === "reduced_schema") {
    return {
      caseId: selection.case_id,
      transport: "raw_non_streaming",
      executor: dependencies.rawNonStreaming,
      request: {
        ...base,
        messages: [
          { role: "system", content: dependencies.prepared.systemPrompt },
          { role: "user", content: dependencies.prepared.userPrompt },
        ],
        response_format: { type: "json_object" },
      },
      schema: ANY_OBJECT_SCHEMA,
      changedFields: selection.changed_fields,
    };
  }
  return {
    caseId: selection.case_id,
    transport: "raw_non_streaming",
    executor: dependencies.rawNonStreaming,
    request: requestWithJsonSchema(
      base,
      "Return one JSON object.",
      "Return a concise guided-production classification.",
      ANY_OBJECT_SCHEMA,
    ),
    schema: ANY_OBJECT_SCHEMA,
    changedFields: selection.changed_fields,
  };
}

function exactRequestBase(request: StructuredCompletionRequest) {
  const { messages: _messages, tools: _tools, tool_choice: _toolChoice, ...base } = request;
  return { ...base, stream: false as const };
}

function requestWithJsonSchema(
  base: Readonly<Record<string, unknown>>,
  systemPrompt: string,
  userPrompt: string,
  schema: Readonly<Record<string, unknown>>,
) {
  return {
    ...base,
    messages: [
      {
        role: "system",
        content: `${systemPrompt}\n\nJSON Schema: ${JSON.stringify(schema)}`,
      },
      { role: "user", content: userPrompt },
    ],
    stream: false,
    response_format: { type: "json_object" },
  };
}

function budgetFailure(definition: CaseDefinition, completedAt: Date): ConformanceCaseResultV1 {
  return {
    case_id: definition.caseId,
    transport: definition.transport,
    status: "aborted",
    request_sha256: requestSha256(definition.request),
    request_bytes: byteCount(definition.request),
    schema_bytes: byteCount(definition.schema),
    transport_completed: false,
    json_parsed: false,
    contract_valid: false,
    response_activity_observed: null,
    dns_at: null,
    tcp_at: null,
    tls_at: null,
    dispatched_at: completedAt.toISOString(),
    response_headers_at: null,
    first_content_at: null,
    completed_at: completedAt.toISOString(),
    duration_ms: 0,
    http_status: null,
    provider_request_id: null,
    safe_error: { code: "conformance_budget_exhausted" },
    changed_fields: definition.changedFields,
  };
}

function projectCaseEvidence(value: ConformanceCaseResultV1): ConformanceCaseResultV1 {
  return {
    case_id: value.case_id,
    transport: value.transport,
    status: value.status,
    request_sha256: value.request_sha256,
    request_bytes: value.request_bytes,
    schema_bytes: value.schema_bytes,
    transport_completed: value.transport_completed,
    json_parsed: value.json_parsed,
    contract_valid: value.contract_valid,
    response_activity_observed: value.response_activity_observed,
    dns_at: value.dns_at,
    tcp_at: value.tcp_at,
    tls_at: value.tls_at,
    dispatched_at: value.dispatched_at,
    response_headers_at: value.response_headers_at,
    first_content_at: value.first_content_at,
    completed_at: value.completed_at,
    duration_ms: value.duration_ms,
    http_status: value.http_status,
    provider_request_id: value.provider_request_id,
    safe_error: projectSafeError(value.safe_error),
    changed_fields: [...value.changed_fields],
  };
}

function projectSafeError(
  value: ConformanceCaseResultV1["safe_error"],
): ConformanceCaseResultV1["safe_error"] {
  if (!value) return null;
  const allowed = ["code", "exception_class", "http_status", "timed_out"] as const;
  return Object.fromEntries(
    allowed.flatMap((key) =>
      typeof value[key] === "string" ||
      typeof value[key] === "number" ||
      typeof value[key] === "boolean"
        ? [[key, value[key]]]
        : [],
    ),
  );
}

function renderMarkdown(report: ConformanceReportV2): string {
  const rows = report.cases
    .map((item) => `| \`${item.case_id}\` | \`${item.transport}\` | \`${item.status}\` | ${item.duration_ms} |`)
    .join("\n");
  return [
    "# Provider Conformance Report",
    "",
    `Status: \`${report.status}\``,
    "",
    `Verdict: \`${report.verdict ?? "none"}\``,
    "",
    `Submissions: ${report.submission_count}/${report.maximum_submissions}`,
    "",
    ...(report.contract_name && report.contract_version
      ? [
          `Contract: \`${report.contract_name}\` (protocol \`${report.contract_version}\`)`,
          "",
        ]
      : []),
    ...(report.frozen_agent_request_digest
      ? [
          `Frozen request digest: \`${report.frozen_agent_request_digest}\``,
          `Prompt digest: \`${report.prompt_digest}\` (${report.prompt_bytes} bytes)`,
          `Contract Schema digest: \`${report.contract_schema_digest}\` (${report.contract_schema_bytes} bytes)`,
          `Model policy digest: \`${report.model_policy_digest}\``,
          `Semantic request digest: \`${report.semantic_request_digest}\` (${report.semantic_request_bytes} bytes)`,
          "",
        ]
      : []),
    "| Case | Transport | Status | Duration (ms) |",
    "| --- | --- | --- | ---: |",
    rows,
    "",
  ].join("\n");
}

async function sendRawHttpRequest(
  input: Parameters<RawHttpSender>[0],
): Promise<RawHttpResponseObservation> {
  const endpoint = new URL(input.url);
  const request = endpoint.protocol === "http:" ? httpRequest : httpsRequest;
  return await new Promise((resolve, reject) => {
    const timestamps = {
      dns_at: null as string | null,
      tcp_at: null as string | null,
      tls_at: null as string | null,
      response_headers_at: null as string | null,
      first_content_at: null as string | null,
    };
    const payload = JSON.stringify(input.payload);
    const call = request(
      endpoint,
      {
        method: "POST",
        headers: {
          authorization: `Bearer ${input.apiKey}`,
          "content-type": "application/json",
          "content-length": Buffer.byteLength(payload),
        },
        signal: input.signal,
      },
      (response) => {
        timestamps.response_headers_at = new Date().toISOString();
        const chunks: Buffer[] = [];
        let bytes = 0;
        response.on("data", (chunk: Buffer | string) => {
          timestamps.first_content_at ??= new Date().toISOString();
          const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
          bytes += buffer.byteLength;
          if (bytes > input.maximumResponseBytes) {
            call.destroy(
              Object.assign(new Error("response_limit_exceeded"), {
                code: "CONFORMANCE_RESPONSE_LIMIT",
              }),
            );
            return;
          }
          chunks.push(buffer);
        });
        response.on("end", () => {
          const body = Buffer.concat(chunks).toString("utf8");
          resolve({
            status: response.statusCode ?? 0,
            headers: normalizeHeaders(response.headers),
            content: responseContent(body, input.payload.stream === true),
            ...timestamps,
            completed_at: new Date().toISOString(),
          });
        });
      },
    );
    call.on("socket", (socket) => {
      socket.once("lookup", () => {
        timestamps.dns_at = new Date().toISOString();
      });
      socket.once("connect", () => {
        timestamps.tcp_at = new Date().toISOString();
      });
      socket.once("secureConnect", () => {
        timestamps.tls_at = new Date().toISOString();
      });
    });
    call.once("error", reject);
    call.end(payload);
  });
}

function terminalObservation(
  response: StructuredCompletionResponse,
): ConformanceExecutionObservation {
  return {
    transport_completed: true,
    content: completionContent(response),
    response_activity_observed: true,
    dns_at: null,
    tcp_at: null,
    tls_at: null,
    response_headers_at: null,
    first_content_at: null,
    completed_at: new Date().toISOString(),
    http_status: 200,
    provider_request_id: boundedHeader(response.id),
    safe_error: null,
  };
}

function responseContent(body: string, streaming: boolean): string | null {
  if (!streaming) {
    try {
      return completionContent(JSON.parse(body) as StructuredCompletionResponse);
    } catch {
      return null;
    }
  }
  const fragments: string[] = [];
  for (const line of body.split(/\r?\n/)) {
    if (!line.startsWith("data:") || line.slice(5).trim() === "[DONE]") continue;
    try {
      const event = JSON.parse(line.slice(5).trim()) as {
        readonly choices?: ReadonlyArray<{
          readonly delta?: { readonly content?: string };
        }>;
      };
      const content = event.choices?.[0]?.delta?.content;
      if (typeof content === "string") fragments.push(content);
    } catch {
      continue;
    }
  }
  return fragments.length > 0 ? fragments.join("") : null;
}

function completionContent(response: StructuredCompletionResponse): string | null {
  const message = response.choices?.[0]?.message;
  if (typeof message?.content === "string") return message.content;
  const calls = message?.tool_calls?.filter(
    (item) => item.function?.name === "submit_structured_result",
  );
  return calls?.length === 1 ? calls[0]?.function?.arguments ?? null : null;
}

function normalizeHeaders(
  headers: Readonly<Record<string, string | string[] | undefined>>,
): Readonly<Record<string, string | undefined>> {
  return Object.fromEntries(
    Object.entries(headers).map(([key, value]) => [
      key.toLowerCase(),
      Array.isArray(value) ? value[0] : value,
    ]),
  );
}

function completionUrl(baseUrl: string): string {
  return `${baseUrl.replace(/\/$/, "")}/chat/completions`;
}

function boundedHeader(value: string | null | undefined): string | null {
  return typeof value === "string" && /^[A-Za-z0-9._:/-]{1,320}$/.test(value)
    ? value
    : null;
}

function isOperatorErrorCode(value: unknown): value is string {
  return typeof value === "string" && new Set([
    "conformance_prerequisite_missing",
    "conformance_credential_unavailable",
    "conformance_request_preparation_failed",
    "conformance_parity_failed",
    "conformance_budget_exhausted",
    "conformance_evidence_write_failed",
    "conformance_unclassified_result",
  ]).has(value);
}

function assertReportInvariants(report: ConformanceReportV2): void {
  const blocked =
    report.schema_version === 2 &&
    report.status === "blocked" &&
    report.submission_count === 0 &&
    report.cases.length === 0 &&
    report.verdict === null &&
    report.blocked_stage !== null &&
    (report.blocked_stage !== "request_parity" ||
      report.operator_error_code === "conformance_parity_failed");
  const completed =
    report.schema_version === 2 &&
    report.status === "completed" &&
    report.submission_count >= 1 &&
    report.cases.length === report.submission_count &&
    report.submission_count <= 6 &&
    report.verdict !== null &&
    report.blocked_stage === null;
  if (!blocked && !completed) throw new Error("conformance_report_invalid");
}

function parseJsonObject(content: string | null | undefined): Readonly<Record<string, unknown>> | undefined {
  if (!content) return undefined;
  try {
    const value: unknown = JSON.parse(content);
    return value && typeof value === "object" && !Array.isArray(value)
      ? (value as Readonly<Record<string, unknown>>)
      : undefined;
  } catch {
    return undefined;
  }
}

function validate(schema: Readonly<Record<string, unknown>>, value: unknown): boolean {
  try {
    return new Ajv2020({ strict: false, allErrors: true }).compile(schema)(value) as boolean;
  } catch {
    return false;
  }
}

function requestSha256(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(canonical(value)), "utf8").digest("hex");
}

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Readonly<Record<string, unknown>>)
      .filter(([, item]) => item !== undefined)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, canonical(item)]),
  );
}

function byteCount(value: unknown): number {
  return new TextEncoder().encode(JSON.stringify(value)).byteLength;
}

function safeError(error: unknown, code: string) {
  const candidate = error as { readonly name?: unknown; readonly status?: unknown };
  return {
    code,
    ...(typeof candidate?.name === "string" ? { exception_class: candidate.name.slice(0, 120) } : {}),
    ...(typeof candidate?.status === "number" ? { http_status: candidate.status } : {}),
  };
}

function isSuccessStatus(status: number | null): boolean {
  return status !== null && status >= 200 && status < 300;
}

function boundedLimit(value: number | undefined, fallback: number, maximum: number): number {
  return Number.isInteger(value) && (value ?? 0) > 0
    ? Math.min(value as number, maximum)
    : fallback;
}

export function classifyConformance(
  results: ReadonlyArray<ConformanceCaseResultV1>,
): ConformanceVerdict {
  const byCase = new Map(results.map((result) => [result.case_id, result]));
  if (!succeeded(byCase.get("minimal_json"))) return "blocked_external";

  if (succeeded(byCase.get("production_exact_raw"))) {
    if (!succeeded(byCase.get("production_exact_sdk"))) return "sdk_incompatible";
    if (!succeeded(byCase.get("production_exact_pi"))) {
      return "pi_transport_incompatible";
    }
    return "verified";
  }

  const prompt = byCase.get("production_prompt_only");
  const schema = byCase.get("production_schema_only");
  if (!prompt || !schema) return "blocked_external";
  if (!succeeded(prompt) && succeeded(schema)) return "prompt_overload";
  if (succeeded(prompt) && !succeeded(schema)) return "schema_incompatible";
  if (succeeded(prompt) && succeeded(schema)) return "prompt_schema_interaction";
  if (succeeded(byCase.get("reduced_combined"))) return "prompt_overload";
  return "blocked_external";
}

export function selectReducedCase(
  results: ReadonlyArray<ConformanceCaseResultV1>,
): ReducedCaseSelection {
  const byCase = new Map(results.map((result) => [result.case_id, result]));
  const prompt = succeeded(byCase.get("production_prompt_only"));
  const schema = succeeded(byCase.get("production_schema_only"));
  if (!prompt && schema) {
    return {
      case_id: "reduced_prompt",
      changed_fields: ["system_prompt", "user_prompt"],
    };
  }
  if (prompt && !schema) {
    return { case_id: "reduced_schema", changed_fields: ["schema"] };
  }
  return {
    case_id: "reduced_combined",
    changed_fields: ["system_prompt", "user_prompt", "schema"],
  };
}

function succeeded(result: ConformanceCaseResultV1 | undefined): boolean {
  return (
    result?.status === "succeeded" &&
    result.transport_completed &&
    result.json_parsed &&
    result.contract_valid
  );
}
