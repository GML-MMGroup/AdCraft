import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const agentRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(agentRoot, "../../..");

describe("Skill bundle packaging", () => {
  it("provides a verifier command and runs it before the Docker build", async () => {
    const packageJson = JSON.parse(
      await readFile(resolve(agentRoot, "package.json"), "utf-8"),
    ) as { scripts: Record<string, string> };
    const dockerfile = await readFile(resolve(agentRoot, "Dockerfile"), "utf-8");

    expect(packageJson.scripts["verify:skills"]).toBe(
      "tsx scripts/verify-skills.ts",
    );
    expect(dockerfile).toContain(
      "COPY agent/scripts/verify-skills.ts ./scripts/verify-skills.ts",
    );
    expect(dockerfile.indexOf("RUN npm run verify:skills")).toBeGreaterThan(-1);
    expect(dockerfile.indexOf("RUN npm run verify:skills")).toBeLessThan(
      dockerfile.indexOf("RUN npm run build"),
    );
  });

  it("forces LF checkout for manifest-pinned Skill resources", async () => {
    const attributes = await readFile(
      resolve(repositoryRoot, ".gitattributes"),
      "utf-8",
    );

    expect(attributes).toContain(
      "apps/api/agent/skills/**/SKILL.md text eol=lf",
    );
    expect(attributes).toContain(
      "apps/api/agent/skills/manifest.json text eol=lf",
    );
  });
});
