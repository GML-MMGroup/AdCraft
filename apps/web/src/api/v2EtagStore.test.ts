import { beforeEach, expect, it } from "vitest";
import { v2EtagStore } from "./v2EtagStore.ts";

beforeEach(() => v2EtagStore.clear());

it("does not roll back a workflow revision when an older response arrives later", () => {
  v2EtagStore.set("workflow", "one", '"workflow-one-v12"');
  v2EtagStore.set("workflow", "one", '"workflow-one-v11"');
  expect(v2EtagStore.getWorkflow("one")).toBe('"workflow-one-v12"');
  v2EtagStore.set("workflow", "two", '"workflow-two-v1"');
  expect(v2EtagStore.getWorkflow("two")).toBe('"workflow-two-v1"');
});
