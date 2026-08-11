import type { AgentRunRequest } from "./generated/agent-runtime.js";
import {
  structuredRepairPrompt,
  structuredSubmissionPrompt,
} from "./prompts/agents.js";
import {
  getPromptDescriptor,
  type PromptDescriptor,
} from "./prompts/registry.js";
import type {
  AgentCredentialSnapshot,
  PythonInternalClient,
} from "./python-internal-client.js";
import {
  getAgentDefinition,
  getOperationDescriptor,
  type OperationDescriptor,
} from "./registry.js";
import {
  loadRequiredSkills,
  type LoadedSkill,
} from "./skills.js";

export interface PreparedStructuredModelInput {
  readonly credential: AgentCredentialSnapshot;
  readonly request: AgentRunRequest;
  readonly systemPrompt: string;
  readonly userPrompt: string;
  readonly schema: Readonly<Record<string, unknown>>;
  readonly loadedSkills: ReadonlyArray<LoadedSkill>;
}

export interface StructuredModelInputDependencies {
  readonly getAgentDefinition: (
    name: AgentRunRequest["agent_name"],
  ) => { readonly operations: ReadonlyArray<string> };
  readonly getPromptDescriptor: (
    operation: string,
    contractName: string,
  ) => Pick<PromptDescriptor, "system_prompt">;
  readonly getOperationDescriptor: (operation: string) => OperationDescriptor;
  readonly loadRequiredSkills: (
    descriptor: OperationDescriptor,
  ) => Promise<ReadonlyArray<LoadedSkill>>;
}

const defaultDependencies: StructuredModelInputDependencies = {
  getAgentDefinition,
  getPromptDescriptor,
  getOperationDescriptor,
  loadRequiredSkills,
};

export async function prepareStructuredModelInput(
  request: AgentRunRequest,
  python: Pick<PythonInternalClient, "credential">,
  dependencies: StructuredModelInputDependencies = defaultDependencies,
): Promise<PreparedStructuredModelInput> {
  const definition = dependencies.getAgentDefinition(request.agent_name);
  if (!definition.operations.includes(request.operation)) {
    throw new Error("agent_operation_not_allowed");
  }
  const promptDescriptor = dependencies.getPromptDescriptor(
    request.operation,
    request.contract_name ?? "",
  );
  if (!request.model_ref) throw new Error("agent_protocol_mismatch");
  const credential = await python.credential(
    request.credential_ref ?? "llm-default",
    request.run_id,
    request.agent_name,
    request.operation,
    request.model_policy_id,
    request.model_ref,
  );
  validateCredentialExecutionPolicy(request, credential);
  const operationDescriptor = dependencies.getOperationDescriptor(request.operation);
  const loadedSkills = await dependencies.loadRequiredSkills(operationDescriptor);
  const skillContext = loadedSkills
    .map(
      (skill) =>
        `Skill: ${skill.skill_id}\nDigest: ${skill.sha256}\n\n${skill.content}`,
    )
    .join("\n\n---\n\n");
  const systemPrompt = [
    promptDescriptor.system_prompt,
    skillContext ? `Trusted skill context:\n\n${skillContext}` : "",
    structuredSubmissionPrompt,
    structuredRepairPrompt,
    transportSubmissionPrompt(credential.execution_policy.structured_transport),
    `Required contract: ${request.contract_name ?? "SpecialistDraft"}.`,
  ]
    .filter(Boolean)
    .join("\n\n");
  return {
    credential,
    request,
    systemPrompt,
    userPrompt: promptInputForRequest(request),
    schema: contractSchemaForRequest(request),
    loadedSkills,
  };
}

export function validateCredentialExecutionPolicy(
  request: AgentRunRequest,
  credential: AgentCredentialSnapshot,
): void {
  const runPolicy = request.policy;
  const executionPolicy = credential.execution_policy;
  if (
    credential.model_policy_id !== request.model_policy_id ||
    credential.model_ref !== request.model_ref ||
    executionPolicy.model_ref !== request.model_ref ||
    executionPolicy.operation !== request.operation ||
    !runPolicy?.operation_policy_id ||
    executionPolicy.operation_class !== runPolicy.operation_class ||
    executionPolicy.deadline_seconds !== runPolicy.timeout_seconds ||
    executionPolicy.primary_timeout_seconds !== runPolicy.primary_timeout_seconds ||
    executionPolicy.recovery_timeout_seconds !== runPolicy.recovery_timeout_seconds ||
    executionPolicy.persistence_reserve_seconds !==
      runPolicy.persistence_reserve_seconds ||
    executionPolicy.max_model_submissions !== runPolicy.max_model_submissions ||
    executionPolicy.recovery_mode !== runPolicy.recovery_mode ||
    executionPolicy.transport_retry_limit !== runPolicy.transport_retry_limit ||
    executionPolicy.structured_repair_limit !== runPolicy.structured_repair_limit ||
    typeof runPolicy.max_output_tokens !== "number" ||
    executionPolicy.max_output_tokens > runPolicy.max_output_tokens ||
    !Number.isFinite(Date.parse(request.deadline_at))
  ) {
    throw new Error("agent_protocol_mismatch");
  }
}

export function contractSchemaForRequest(
  request: AgentRunRequest,
): Readonly<Record<string, unknown>> {
  if (
    request.contract_schema &&
    typeof request.contract_schema === "object" &&
    !Array.isArray(request.contract_schema)
  ) {
    return request.contract_schema;
  }
  return "contract_schema" in request.context &&
    request.context.contract_schema &&
    typeof request.context.contract_schema === "object" &&
    !Array.isArray(request.context.contract_schema)
    ? request.context.contract_schema
    : {};
}

export function promptInputForRequest(request: AgentRunRequest): string {
  const context = request.context as Readonly<Record<string, unknown>>;
  let primaryInput = [
    "user_input",
    "user_instruction",
    "original_user_intent",
    "objective",
    "creative_goal",
  ]
    .map((key) => context[key])
    .find((value): value is string => typeof value === "string" && value.length > 0);
  if (
    !primaryInput &&
    context.context_kind === "video_parameter_intent" &&
    Array.isArray(context.sources)
  ) {
    primaryInput = context.sources
      .map((source) =>
        source && typeof source === "object" && "text" in source
          ? (source as Readonly<Record<string, unknown>>).text
          : undefined,
      )
      .filter((value): value is string => typeof value === "string" && value.length > 0)
      .join("\n\n");
  }
  if (!primaryInput) throw new Error("agent_context_input_missing");
  const hasTypedOperationContext =
    "context_kind" in request.context ||
    "session_exists" in request.context ||
    "capability_id" in request.context ||
    "policy" in request.context;
  if (!hasTypedOperationContext) return primaryInput;

  const typedContext = Object.fromEntries(
    Object.entries(request.context).filter(([key]) => key !== "contract_schema"),
  );
  return [
    `User request:\n${primaryInput}`,
    `Validated typed operation context:\n${JSON.stringify(typedContext)}`,
  ].join("\n\n");
}

function transportSubmissionPrompt(
  transport: AgentCredentialSnapshot["execution_policy"]["structured_transport"],
): string {
  if (transport === "non_streaming_json_object") {
    return "Return exactly one JSON object in assistant content. Do not call a tool.";
  }
  return "Call submit_structured_result with the final structured value.";
}
