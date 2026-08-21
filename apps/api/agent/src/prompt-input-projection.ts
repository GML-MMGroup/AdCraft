import type { OperationDescriptor } from "./registry.js";

export type PromptInputRenderMode =
  | "primary_only"
  | "primary_plus_typed_context";

export interface PromptInputProjectionDefinition {
  readonly contextContractName: string;
  readonly projectionId: string;
  readonly renderMode: PromptInputRenderMode;
  readonly project: (
    context: Readonly<Record<string, unknown>>,
  ) => string | undefined;
}

export interface PromptInputProjectionRegistry {
  readonly resolve: (contextContractName: string) => PromptInputProjectionDefinition;
  readonly definitions: () => ReadonlyArray<PromptInputProjectionDefinition>;
}

export class AgentPromptInputProjectionError extends Error {
  constructor(
    readonly code:
      | "agent_prompt_input_registry_invalid"
      | "agent_context_input_missing",
    readonly contextContractName: string,
    readonly projectionId?: string,
  ) {
    super(code);
    this.name = "AgentPromptInputProjectionError";
  }
}

const primaryOnly = "primary_only" as const;
const primaryPlusTypedContext = "primary_plus_typed_context" as const;

const definitions = Object.freeze([
  definition(
    "AgentRunContext",
    "agent-run-user-input-v1",
    primaryOnly,
    topLevelString("user_input"),
  ),
  ...[
    "FrontDeskIntentAgentContext",
    "IntentContractAgentContext",
    "ScriptWriterAgentContext",
    "ProductExpertAgentContext",
    "CharacterExpertAgentContext",
    "SceneExpertAgentContext",
    "BgmExpertAgentContext",
    "QuickMediaAgentContext",
    "WorkflowConversationAgentContext",
    "ConversationSummaryAgentContext",
    "TurnIntentContextV2",
  ].map((contextContractName) =>
    definition(
      contextContractName,
      `${contextContractName}-user-input-v1`,
      primaryPlusTypedContext,
      topLevelString("user_input"),
    ),
  ),
  definition(
    "AgentCommandReplanContextV2",
    "agent-command-replan-original-intent-v1",
    primaryPlusTypedContext,
    topLevelString("original_user_intent"),
  ),
  definition(
    "RolePromptPreparationContextV2",
    "role-prompt-selected-direction-v1",
    primaryPlusTypedContext,
    firstTopLevelString("selected_direction", "user_prompt"),
  ),
  ...["NextActionContextV1", "CapabilityInvocationContextV2"].map(
    (contextContractName) =>
      definition(
        contextContractName,
        `${contextContractName}-objective-v1`,
        primaryPlusTypedContext,
        topLevelString("objective"),
      ),
  ),
  definition(
    "CapabilityMaterializationContextV1",
    "capability-materialization-creative-goal-v1",
    primaryPlusTypedContext,
    topLevelString("creative_goal"),
  ),
  definition(
    "VideoParameterIntentContextV3",
    "video-parameter-ordered-sources-v3",
    primaryPlusTypedContext,
    joinedSourceText("sources", "text"),
  ),
  definition(
    "StoryboardSegmentAuthoringContextV2",
    "storyboard-segment-narrative-goal-v1",
    primaryPlusTypedContext,
    nestedString("sequence", "narrative_goal"),
  ),
]);

const registry = createPromptInputProjectionRegistry(definitions);

export function getPromptInputProjection(
  contextContractName: string,
): PromptInputProjectionDefinition {
  return registry.resolve(contextContractName);
}

export function listPromptInputProjections(): ReadonlyArray<PromptInputProjectionDefinition> {
  return registry.definitions();
}

export function createPromptInputProjectionRegistry(
  candidates: ReadonlyArray<PromptInputProjectionDefinition>,
): PromptInputProjectionRegistry {
  const frozenDefinitions = Object.freeze(
    candidates.map((candidate) => Object.freeze(candidate)),
  );
  const byContextContractName = new Map<string, PromptInputProjectionDefinition>();
  for (const candidate of frozenDefinitions) {
    if (
      !candidate.contextContractName ||
      !candidate.projectionId ||
      typeof candidate.project !== "function" ||
      (candidate.renderMode !== "primary_only" &&
        candidate.renderMode !== "primary_plus_typed_context") ||
      byContextContractName.has(candidate.contextContractName)
    ) {
      throw new AgentPromptInputProjectionError(
        "agent_prompt_input_registry_invalid",
        candidate.contextContractName,
        candidate.projectionId,
      );
    }
    byContextContractName.set(candidate.contextContractName, candidate);
  }
  return Object.freeze({
    resolve(contextContractName: string): PromptInputProjectionDefinition {
      const found = byContextContractName.get(contextContractName);
      if (!found) {
        throw new AgentPromptInputProjectionError(
          "agent_prompt_input_registry_invalid",
          contextContractName,
        );
      }
      return found;
    },
    definitions(): ReadonlyArray<PromptInputProjectionDefinition> {
      return frozenDefinitions;
    },
  });
}

export function validatePromptInputProjectionParity(
  operations: ReadonlyArray<OperationDescriptor>,
  candidates: ReadonlyArray<PromptInputProjectionDefinition>,
): void {
  const candidateRegistry = createPromptInputProjectionRegistry(candidates);
  const usedContextContracts = new Set<string>();
  for (const operation of operations) {
    usedContextContracts.add(operation.context_contract_name);
    candidateRegistry.resolve(operation.context_contract_name);
  }
  const registeredContextContracts = new Set(
    candidateRegistry.definitions().map((item) => item.contextContractName),
  );
  if (
    usedContextContracts.size !== registeredContextContracts.size ||
    [...registeredContextContracts].some(
      (contextContractName) => !usedContextContracts.has(contextContractName),
    )
  ) {
    throw new AgentPromptInputProjectionError(
      "agent_prompt_input_registry_invalid",
      "operation_projection_parity",
    );
  }
}

function definition(
  contextContractName: string,
  projectionId: string,
  renderMode: PromptInputRenderMode,
  project: PromptInputProjectionDefinition["project"],
): PromptInputProjectionDefinition {
  return Object.freeze({
    contextContractName,
    projectionId,
    renderMode,
    project,
  });
}

function topLevelString(
  key: string,
): PromptInputProjectionDefinition["project"] {
  return (context) => nonEmptyString(context[key]);
}

function firstTopLevelString(
  ...keys: ReadonlyArray<string>
): PromptInputProjectionDefinition["project"] {
  return (context) => {
    for (const key of keys) {
      const value = nonEmptyString(context[key]);
      if (value !== undefined) return value;
    }
    return undefined;
  };
}

function nestedString(
  parentKey: string,
  childKey: string,
): PromptInputProjectionDefinition["project"] {
  return (context) => {
    const parent = context[parentKey];
    return parent && typeof parent === "object" && !Array.isArray(parent)
      ? nonEmptyString((parent as Readonly<Record<string, unknown>>)[childKey])
      : undefined;
  };
}

function joinedSourceText(
  collectionKey: string,
  textKey: string,
): PromptInputProjectionDefinition["project"] {
  return (context) => {
    const collection = context[collectionKey];
    if (!Array.isArray(collection)) return undefined;
    const parts = collection
      .map((item) =>
        item && typeof item === "object" && !Array.isArray(item)
          ? nonEmptyString((item as Readonly<Record<string, unknown>>)[textKey])
          : undefined,
      )
      .filter((item): item is string => item !== undefined);
    return parts.length > 0 ? parts.join("\n\n") : undefined;
  };
}

function nonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}
