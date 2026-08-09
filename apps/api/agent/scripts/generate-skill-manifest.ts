import { createHash } from "node:crypto";
import { readdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const agentRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const skillsRoot = resolve(agentRoot, "skills");
const manifestPath = resolve(skillsRoot, "manifest.json");

const entries: Array<{ path: string; sha256: string; skill_id: string }> = [];
for (const skillId of (await readdir(skillsRoot, { withFileTypes: true }))
  .filter((entry) => entry.isDirectory())
  .map((entry) => entry.name)
  .sort()) {
  const path = `${skillId}/SKILL.md`;
  let bytes: Uint8Array;
  try {
    bytes = await readFile(resolve(skillsRoot, path));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") continue;
    throw error;
  }
  const content = canonicalSkillContent(bytes);
  entries.push({
    path,
    sha256: createHash("sha256").update(content, "utf8").digest("hex"),
    skill_id: skillId,
  });
}

await writeFile(
  manifestPath,
  `${JSON.stringify({ skills: entries, version: "1" }, null, 2)}\n`,
  "utf8",
);

function canonicalSkillContent(bytes: Uint8Array): string {
  return Buffer.from(bytes)
    .toString("utf-8")
    .replace(/\r\n?/g, "\n")
    .replace(/\n+$/g, "")
    .concat("\n");
}
