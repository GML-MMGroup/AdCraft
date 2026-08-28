import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentCanvasChatViewTimelineV2, GuidedSessionStateV2, ProjectV2Summary } from "../types-v2.ts";
import { useProjectDisplayNames } from "./useProjectDisplayNames.ts";

const fixture = vi.hoisted(() => ({
  agentCanvasChatTimeline: vi.fn(),
  agentCanvasCreativeSession: vi.fn(),
}));

vi.mock("../api/agentCanvasApi.ts", () => ({
  agentCanvasApi: fixture,
}));

function Harness({ projects }: { projects: ProjectV2Summary[] }) {
  const names = useProjectDisplayNames(projects);
  return <output>{names[projects[0]?.project_id] ?? projects[0]?.name}</output>;
}

function project(name: string): ProjectV2Summary {
  return {
    project_id: "project-1",
    workflow_id: "workflow-1",
    name,
    status: "active",
    is_favorite: false,
    cover_asset_id: null,
    project_version: 1,
    updated_at: "2026-08-27T08:00:00Z",
  };
}

describe("useProjectDisplayNames", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("loads the first user request for a placeholder project", async () => {
    fixture.agentCanvasChatTimeline.mockResolvedValue({
      presentationItems: [{ item: { item_type: "message", speaker: "user", text: "Make a necklace advertisement" } }],
      items: [],
    } as unknown as AgentCanvasChatViewTimelineV2);

    render(<Harness projects={[project("Untitled Project")]} />);

    await waitFor(() => expect(screen.getByText("Make a necklace advertisement")).toBeTruthy());
    expect(fixture.agentCanvasChatTimeline).toHaveBeenCalledWith("workflow-1", 0, 100, {
      signal: expect.any(AbortSignal),
    });
    expect(fixture.agentCanvasCreativeSession).not.toHaveBeenCalled();
  });

  it("falls back to the creative goal when the timeline has no user request", async () => {
    fixture.agentCanvasChatTimeline.mockResolvedValue({ presentationItems: [], items: [] });
    fixture.agentCanvasCreativeSession.mockResolvedValue({
      goal: { summary: "Create a cinematic coffee advertisement" },
    } as unknown as GuidedSessionStateV2);

    render(<Harness projects={[project("Untitled Project")]} />);

    await waitFor(() => expect(screen.getByText("Create a cinematic coffee advertisement")).toBeTruthy());
    expect(fixture.agentCanvasCreativeSession).toHaveBeenCalledWith("workflow-1", {
      signal: expect.any(AbortSignal),
    });
  });

  it("does not fetch metadata for an explicitly named project", async () => {
    render(<Harness projects={[project("Summer launch")]} />);

    expect(screen.getByText("Summer launch")).toBeTruthy();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fixture.agentCanvasChatTimeline).not.toHaveBeenCalled();
    expect(fixture.agentCanvasCreativeSession).not.toHaveBeenCalled();
  });
});
