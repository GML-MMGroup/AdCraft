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
  AgentPromptInputProjectionError,
  getPromptInputProjection,
} from "./prompt-input-projection.js";
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
  const schema = contractSchemaForRequest(request);
  if (
    request.operation === "decide_turn_intent" &&
    Buffer.byteLength(JSON.stringify(schema), "utf8") > 16_384
  ) {
    throw new Error("agent_intake_context_too_large");
  }
  const operationDescriptor = dependencies.getOperationDescriptor(request.operation);
  const userPrompt = promptInputForRequest(request, operationDescriptor);
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
  if (
    request.operation === "decide_turn_intent" &&
    Buffer.byteLength(
      JSON.stringify({
        model_ref: request.model_ref,
        operation: request.operation,
        system_prompt: systemPrompt,
        user_prompt: userPrompt,
        schema,
        policy: credential.execution_policy,
      }),
      "utf8",
    ) > 131_072
  ) {
    throw new Error("agent_intake_context_too_large");
  }
  return {
    credential,
    request,
    systemPrompt,
    userPrompt,
    schema,
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

export function promptInputForRequest(
  request: AgentRunRequest,
  descriptor: OperationDescriptor,
): string {
  const context = request.context as Readonly<Record<string, unknown>>;
  const projection = getPromptInputProjection(descriptor.context_contract_name);
  const primaryInput = projection.project(context);
  if (!primaryInput) {
    throw new AgentPromptInputProjectionError(
      "agent_context_input_missing",
      descriptor.context_contract_name,
      projection.projectionId,
    );
  }
  if (projection.renderMode === "primary_only") return primaryInput;

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
  if (transport === "non_streaming_json_schema") {
    return "Return exactly one strict schema-valid JSON object in assistant content. Do not call a tool.";
  }
  if (transport === "streaming_json_object") {
    return "Return exactly one JSON object in streamed assistant content. Do not call a tool.";
  }
  return "Call submit_structured_result with the final structured value.";
}
