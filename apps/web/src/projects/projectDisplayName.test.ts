import { describe, expect, it } from "vitest";
import {
  isPlaceholderProjectName,
  resolveProjectDisplayName,
} from "./projectDisplayName.ts";

describe("project display name projection", () => {
  it("keeps a user-defined project name", () => {
    expect(resolveProjectDisplayName({
      projectName: "Summer necklace campaign",
      firstUserMessage: "Make a necklace ad",
      goalSummary: "Create a necklace advertisement",
    })).toBe("Summer necklace campaign");
  });

  it("uses the first user request for a default project", () => {
    expect(resolveProjectDisplayName({
      projectName: "Untitled Project",
      firstUserMessage: "我想做一款项链的创意广告",
      goalSummary: "为一款项链创作创意广告，启动广告制作流程",
    })).toBe("我想做一款项链的创意广告");
  });

  it("falls back to the structured goal before the placeholder name", () => {
    expect(resolveProjectDisplayName({
      projectName: "Untitled Project",
      firstUserMessage: null,
      goalSummary: "Create a cinematic coffee advertisement",
    })).toBe("Create a cinematic coffee advertisement");
    expect(resolveProjectDisplayName({
      projectName: "Untitled Project",
      firstUserMessage: null,
      goalSummary: null,
    })).toBe("Untitled Project");
  });

  it("recognizes the default names without changing real names", () => {
    expect(isPlaceholderProjectName(" Untitled Project ")).toBe(true);
    expect(isPlaceholderProjectName("New Project")).toBe(true);
    expect(isPlaceholderProjectName("Untitled Project 2")).toBe(false);
  });
});
