import { SkillBundleError, verifySkillBundle } from "../src/skills.js";

await verifySkillBundle().catch((error: unknown) => {
  const code =
    error instanceof SkillBundleError
      ? error.code
      : "agent_skill_verification_failed";
  console.error(`Skill bundle verification failed: ${code}.`);
  process.exit(1);
});
