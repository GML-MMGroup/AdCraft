import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { dirname, isAbsolute, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { OperationDescriptor } from "./registry.js";

interface ManifestEntry {
  readonly skill_id: string;
  readonly path: string;
  readonly sha256: string;
}

interface SkillManifest {
  readonly version: "1";
  readonly skills: ReadonlyArray<ManifestEntry>;
}

export interface LoadedSkill {
  readonly skill_id: string;
  readonly version: "1";
  readonly sha256: string;
  readonly content: string;
}

export interface VerifiedSkillBundle {
  readonly version: "1";
  readonly skills: ReadonlyMap<string, LoadedSkill>;
}

export class SkillBundleError extends Error {
  constructor(readonly code: string) {
    super(code);
    this.name = "SkillBundleError";
  }
}

const bundleRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../skills");
let defaultBundle: Promise<VerifiedSkillBundle> | undefined;

export function verifySkillBundle(
  root: string = bundleRoot,
): Promise<VerifiedSkillBundle> {
  const resolvedRoot = resolve(root);
  if (resolvedRoot !== bundleRoot) {
    return verifyBundleAt(resolvedRoot);
  }
  defaultBundle ??= verifyBundleAt(resolvedRoot);
  return defaultBundle;
}

export async function loadRequiredSkills(
  descriptor: OperationDescriptor,
  selectedOptionalIds: ReadonlyArray<string> = [],
): Promise<ReadonlyArray<LoadedSkill>> {
  const optional = new Set(descriptor.optional_skills);
  if (selectedOptionalIds.some((skillId) => !optional.has(skillId))) {
    throw new Error("agent_optional_skill_not_allowed");
  }
  const selectedIds = [
    ...descriptor.required_skills,
    ...selectedOptionalIds.filter(
      (skillId) => !descriptor.required_skills.includes(skillId),
    ),
  ];
  const bundle = await verifySkillBundle();
  const skills = selectedIds.map((skillId) => {
    const skill = bundle.skills.get(skillId);
    if (!skill) throw new Error("agent_required_skill_missing");
    return skill;
  });
  const contextBytes = skills.reduce(
    (total, skill) => total + Buffer.byteLength(skill.content),
    0,
  );
  if (contextBytes > descriptor.max_skill_context_bytes) {
    throw new Error("agent_skill_context_budget_exceeded");
  }
  return skills;
}

async function verifyBundleAt(root: string): Promise<VerifiedSkillBundle> {
  const manifest = await readManifest(root);
  const skills = new Map<string, LoadedSkill>();
  for (const entry of manifest.skills) {
    if (skills.has(entry.skill_id)) {
      throw new SkillBundleError("agent_skill_manifest_duplicate_id");
    }
    const path = resolveSkillPath(root, entry.path);
    let bytes: Buffer;
    try {
      bytes = await readFile(path);
    } catch {
      throw new SkillBundleError("agent_skill_file_missing");
    }
    const content = canonicalSkillContent(bytes);
    const digest = createHash("sha256").update(content, "utf8").digest("hex");
    if (digest !== entry.sha256) {
      throw new SkillBundleError("agent_skill_digest_mismatch");
    }
    skills.set(entry.skill_id, {
      skill_id: entry.skill_id,
      version: manifest.version,
      sha256: digest,
      content,
    });
  }
  return { version: manifest.version, skills };
}

export function canonicalSkillContent(bytes: Uint8Array): string {
  return Buffer.from(bytes)
    .toString("utf-8")
    .replace(/\r\n?/g, "\n")
    .replace(/\n+$/g, "")
    .concat("\n");
}

function resolveSkillPath(root: string, declaredPath: string): string {
  if (!/^[a-z0-9_]+\/SKILL\.md$/.test(declaredPath)) {
    throw new SkillBundleError("agent_skill_path_invalid");
  }
  const path = resolve(root, declaredPath);
  const relativePath = relative(root, path);
  if (!relativePath || relativePath.startsWith("..") || isAbsolute(relativePath)) {
    throw new SkillBundleError("agent_skill_path_invalid");
  }
  return path;
}

async function readManifest(root: string): Promise<SkillManifest> {
  let value: unknown;
  try {
    const bytes = await readFile(resolve(root, "manifest.json"));
    value = JSON.parse(bytes.toString("utf-8"));
  } catch {
    throw new SkillBundleError("agent_skill_manifest_invalid");
  }
  if (
    !value ||
    typeof value !== "object" ||
    (value as { version?: unknown }).version !== "1" ||
    !Array.isArray((value as { skills?: unknown }).skills) ||
    !(value as { skills: unknown[] }).skills.every(
      (entry) =>
        entry !== null &&
        typeof entry === "object" &&
        typeof (entry as { skill_id?: unknown }).skill_id === "string" &&
        typeof (entry as { path?: unknown }).path === "string" &&
        typeof (entry as { sha256?: unknown }).sha256 === "string",
    )
  ) {
    throw new SkillBundleError("agent_skill_manifest_invalid");
  }
  return value as SkillManifest;
}
