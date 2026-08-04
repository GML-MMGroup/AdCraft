import { readFileSync, readdirSync, statSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const sourceRoot = resolve(process.cwd(), "src");
const agentCanvasRoot = resolve(sourceRoot, "features/agent-canvas");

const retiredRoutePatterns = [
  /plan-from-(?:prompt|chat)/,
  /\/items\//,
  /\/slots\//,
  /working-version/,
  /selected-version/,
  /chat-target/,
  /chat-actions/,
  /free-nodes?/,
  /final-composition/,
  /\/provider-tasks\//,
  /continue_planning/,
];

const retiredClientMethods = [
  "planFromPrompt",
  "planFromChat",
  "generateSlot",
  "regenerateSlot",
  "selectSlotVersion",
  "discardWorkingVersion",
  "resolveChatTarget",
  "applyChatAction",
  "createFreeNode",
  "renderFinalComposition",
  "pollProviderTask",
];

function sourceFiles(directory: string): string[] {
  return readdirSync(directory)
    .flatMap((entry) => {
      const path = resolve(directory, entry);
      if (statSync(path).isDirectory()) return sourceFiles(path);
      return /\.[cm]?[jt]sx?$/.test(entry) && !entry.includes(".test.")
        ? [path]
        : [];
    });
}

describe("Agent Canvas production route boundary", () => {
  it("cannot import the broad legacy V2 client or reference retired routes", () => {
    const violations = sourceFiles(agentCanvasRoot).flatMap((path) => {
      const source = readFileSync(path, "utf8");
      const relativePath = path.slice(sourceRoot.length + 1);
      const reasons = [
        ...(source.includes("/api/v2Client") || source.includes("../../api/v2Client")
          ? ["imports v2Client directly"]
          : []),
        ...retiredRoutePatterns
          .filter((pattern) => pattern.test(source))
          .map((pattern) => `contains ${pattern.source}`),
        ...retiredClientMethods
          .filter((method) => source.includes(method))
          .map((method) => `uses ${method}`),
      ];
      return reasons.map((reason) => `${relativePath}: ${reason}`);
    });

    expect(violations).toEqual([]);
  });

  it("keeps the workflow route on the Agent Canvas page", () => {
    const workflowPage = readFileSync(resolve(sourceRoot, "pages/WorkflowPage.tsx"), "utf8");
    expect(workflowPage).toContain('features/agent-canvas/AgentCanvasPage.tsx');
    expect(workflowPage).not.toContain("features/workflow/");
  });

  it("keeps retired capabilities out of the narrow Agent Canvas API facade", () => {
    const facade = readFileSync(resolve(sourceRoot, "api/agentCanvasApi.ts"), "utf8");
    const violations = [
      ...retiredRoutePatterns
        .filter((pattern) => pattern.test(facade))
        .map((pattern) => `contains ${pattern.source}`),
      ...retiredClientMethods
        .filter((method) => facade.includes(method))
        .map((method) => `exposes ${method}`),
    ];
    expect(violations).toEqual([]);
  });
});
