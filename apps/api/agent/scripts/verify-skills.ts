import { listOperationDescriptors } from "../src/registry.js";
import { loadRequiredSkills, SkillBundleError, verifySkillBundle } from "../src/skills.js";

let operation = "bundle";
try {
  await verifySkillBundle();
  for (const descriptor of listOperationDescriptors()) {
    operation = descriptor.operation;
    await loadRequiredSkills(descriptor);
  }
} catch (error: unknown) {
  const code = error instanceof SkillBundleError
    ? error.code
    : error instanceof Error ? error.message : "agent_skill_verification_failed";
  console.error(`Skill bundle verification failed (${operation}): ${code}.`);
  process.exit(1);
}
