import { AGENT_CAPABILITY_CONTRACT } from "./generated/agent-capabilities.js";
import {
  listOperationDescriptors,
  type OperationDescriptor,
} from "./registry.js";
import {
  listPromptInputProjections,
  type PromptInputProjectionDefinition,
  validatePromptInputProjectionParity,
} from "./prompt-input-projection.js";
import { verifySkillBundle } from "./skills.js";

interface ListenableServer {
  listen(port: number, host: string): unknown;
}

export async function startVerifiedServer(
  server: ListenableServer,
  port: number,
  host: string,
  verify: () => Promise<unknown> = verifyRuntimeIntegrity,
): Promise<void> {
  await verify();
  server.listen(port, host);
}

export async function verifyRuntimeIntegrity(): Promise<void> {
  const bundle = await verifySkillBundle();
  const operations = listOperationDescriptors();
  validateRuntimeRegistries(
    operations,
    AGENT_CAPABILITY_CONTRACT.agents[0].operations,
    [...bundle.skills.keys()],
    listPromptInputProjections(),
  );
}

export function validateRuntimeRegistries(
  descriptors: ReadonlyArray<OperationDescriptor>,
  capabilityOperations: ReadonlyArray<string>,
  skillIds: ReadonlyArray<string>,
  projections: ReadonlyArray<PromptInputProjectionDefinition>,
): void {
  validateOperationRegistry(descriptors, capabilityOperations, skillIds);
  validatePromptInputProjectionParity(descriptors, projections);
}

interface RuntimeOperationDeclaration {
  readonly agent_name: string;
  readonly operation: string;
  readonly required_skill?: string | null;
  readonly required_skills?: ReadonlyArray<string>;
  readonly allowed_tools: ReadonlyArray<string>;
  readonly max_handoffs: number;
}

export function validateOperationRegistry(
  descriptors: ReadonlyArray<RuntimeOperationDeclaration | OperationDescriptor>,
  capabilityOperations: ReadonlyArray<string>,
  skillIds: ReadonlyArray<string>,
): void {
  const declared = descriptors.map(({ operation }) => operation);
  const declaredSet = new Set(declared);
  const capabilitySet = new Set(capabilityOperations);
  const availableSkills = new Set(skillIds);
  const valid =
    descriptors.length === capabilityOperations.length &&
    declaredSet.size === descriptors.length &&
    capabilitySet.size === capabilityOperations.length &&
    declaredSet.size === capabilitySet.size &&
    [...declaredSet].every((operation) => capabilitySet.has(operation)) &&
    descriptors.every((descriptor) => {
      const legacySkills: ReadonlyArray<string> =
        "required_skills" in descriptor ? descriptor.required_skills ?? [] : [];
      const requiredSkill = descriptor.required_skill ?? null;
      return (
        descriptor.agent_name === "video_agent" &&
        descriptor.max_handoffs === 0 &&
        descriptor.allowed_tools.length === 1 &&
        descriptor.allowed_tools[0] === "submit_structured_result" &&
        legacySkills.length <= 1 &&
        !(requiredSkill && legacySkills.length > 0) &&
        (!requiredSkill || availableSkills.has(requiredSkill)) &&
        legacySkills.every((skillId) => availableSkills.has(skillId))
      );
    });
  if (!valid) throw new Error("agent_operation_registry_invalid");
}
