import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { agentCanvasApi, V2ApiError } from "../../../api/agentCanvasApi.ts";
import type { ActiveStyleSkillSummaryV2, VideoSkillCatalogResponseV2 } from "../../../types-v2.ts";
import { AgentCanvasStyleSelector } from "./AgentCanvasStyleSelector.tsx";

const activeStyle: ActiveStyleSkillSummaryV2 = {
  skill_run_id: "style-run-1",
  skill_id: "platform-default",
  skill_version: "1.0.0",
  title: "Platform Default",
  summary: "Balanced commercial video direction.",
  category: "commercial-craft",
  creative_direction_snapshot_id: "direction-1",
};

const catalog: VideoSkillCatalogResponseV2 = {
  catalog_version: "1",
  categories: [
    { category_id: "cinematic-narrative", title: "Cinematic Narrative", display_order: 30 },
    { category_id: "commercial-craft", title: "Commercial Craft", display_order: 10 },
  ],
  items: [
    {
      skill_id: "cinematic-poetic-realism",
      version: "1.0.0",
      title: "Cinematic Poetic Realism",
      summary: "A restrained cinematic treatment.",
      category: "cinematic-narrative",
      tags: ["cinematic", "poetic"],
      supported_use_cases: ["brand film"],
      preview: { kind: "none", summary: "Text-only public preview.", media_url: null },
      display_order: 20,
    },
    {
      skill_id: "platform-default",
      version: "1.0.0",
      title: "Platform Default",
      summary: "Balanced commercial video direction.",
      category: "commercial-craft",
      tags: ["commercial"],
      supported_use_cases: ["general advertising"],
      preview: null,
      display_order: 10,
    },
  ],
  next_cursor: null,
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("AgentCanvasStyleSelector", () => {
  it("loads and orders the backend-driven public catalog when opened", async () => {
    vi.spyOn(agentCanvasApi, "listVideoSkills").mockResolvedValue(catalog);

    render(
      <AgentCanvasStyleSelector
        workflowId="workflow-1"
        activeStyle={activeStyle}
        onWorkflowRefresh={vi.fn()}
      />,
    );

    expect(agentCanvasApi.listVideoSkills).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Style: Platform Default" }));

    const dialog = await screen.findByRole("dialog", { name: "Choose video Style" });
    expect(agentCanvasApi.listVideoSkills).toHaveBeenCalledWith({ limit: 100 });
    expect(within(dialog).getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Commercial Craft",
      "Cinematic Narrative",
    ]);
    expect(within(dialog).getByRole("button", { name: /Platform Default/ }).getAttribute(
      "aria-pressed",
    )).toBe("true");
    expect(within(dialog).queryByRole("img")).toBeNull();
    expect(within(dialog).getByText("general advertising")).toBeTruthy();
  });

  it("loads all catalog pages and deduplicates stable Skill versions", async () => {
    const listVideoSkills = vi.spyOn(agentCanvasApi, "listVideoSkills")
      .mockResolvedValueOnce({
        ...catalog,
        items: [catalog.items[1]!],
        next_cursor: "page-2",
      })
      .mockResolvedValueOnce({
        ...catalog,
        items: [catalog.items[1]!, catalog.items[0]!],
        next_cursor: null,
      });

    render(
      <AgentCanvasStyleSelector
        workflowId="workflow-1"
        activeStyle={activeStyle}
        onWorkflowRefresh={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Style: Platform Default" }));
    const dialog = await screen.findByRole("dialog", { name: "Choose video Style" });

    expect(listVideoSkills).toHaveBeenNthCalledWith(1, { limit: 100 });
    expect(listVideoSkills).toHaveBeenNthCalledWith(2, { limit: 100, cursor: "page-2" });
    expect(within(dialog).getAllByRole("button", { name: /Platform Default/ })).toHaveLength(1);

    fireEvent.click(within(dialog).getByRole("tab", { name: "Cinematic Narrative" }));
    expect(within(dialog).getByRole("button", { name: /Cinematic Poetic Realism/ })).toBeTruthy();
  });

  it("activates one Style with the current run and refreshes the Workflow", async () => {
    vi.spyOn(agentCanvasApi, "listVideoSkills").mockResolvedValue(catalog);
    const activate = vi.spyOn(agentCanvasApi, "createAgentCanvasVideoSkillRun").mockResolvedValue({
      skill_run_id: "style-run-2",
      workflow_id: "workflow-1",
      skill_id: "cinematic-poetic-realism",
      skill_version: "1.0.0",
      source_skill_run_id: "style-run-1",
      status: "active",
      active_creative_direction_snapshot_id: "direction-2",
      public_skill: catalog.items[0]!,
      created_at: "2026-08-05T01:00:00Z",
      updated_at: null,
    });
    const refreshWorkflow = vi.fn().mockResolvedValue(undefined);

    render(
      <AgentCanvasStyleSelector
        workflowId="workflow-1"
        activeStyle={activeStyle}
        onWorkflowRefresh={refreshWorkflow}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Style: Platform Default" }));
    const dialog = await screen.findByRole("dialog", { name: "Choose video Style" });
    fireEvent.click(within(dialog).getByRole("tab", { name: "Cinematic Narrative" }));
    fireEvent.click(within(dialog).getByRole("button", { name: /Cinematic Poetic Realism/ }));

    await waitFor(() => expect(activate).toHaveBeenCalledOnce());
    expect(activate).toHaveBeenCalledWith(
      "workflow-1",
      {
        skill_id: "cinematic-poetic-realism",
        skill_version: "1.0.0",
        source_skill_run_id: "style-run-1",
      },
      expect.stringMatching(/^style-/),
    );
    await waitFor(() => expect(refreshWorkflow).toHaveBeenCalledOnce());
  });

  it("refreshes authoritative state and keeps the picker open on activation conflict", async () => {
    vi.spyOn(agentCanvasApi, "listVideoSkills").mockResolvedValue(catalog);
    vi.spyOn(agentCanvasApi, "createAgentCanvasVideoSkillRun").mockRejectedValue(new V2ApiError({
      status: 409,
      code: "style_skill_activation_conflict",
      message: "The active Style changed in another session.",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }));
    const refreshWorkflow = vi.fn().mockResolvedValue(undefined);

    render(
      <AgentCanvasStyleSelector
        workflowId="workflow-1"
        activeStyle={activeStyle}
        onWorkflowRefresh={refreshWorkflow}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Style: Platform Default" }));
    const dialog = await screen.findByRole("dialog", { name: "Choose video Style" });
    fireEvent.click(within(dialog).getByRole("tab", { name: "Cinematic Narrative" }));
    fireEvent.click(within(dialog).getByRole("button", { name: /Cinematic Poetic Realism/ }));

    await waitFor(() => expect(refreshWorkflow).toHaveBeenCalledOnce());
    expect(screen.getByRole("dialog", { name: "Choose video Style" })).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toMatch(/changed in another session/i);
  });

  it("keeps a bounded conflict message when authoritative refresh also fails", async () => {
    vi.spyOn(agentCanvasApi, "listVideoSkills").mockResolvedValue(catalog);
    vi.spyOn(agentCanvasApi, "createAgentCanvasVideoSkillRun").mockRejectedValue(new V2ApiError({
      status: 409,
      code: "style_skill_activation_conflict",
      message: "The active Style changed in another session.",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }));
    const refreshWorkflow = vi.fn().mockRejectedValue(new Error("Workflow refresh failed."));

    render(
      <AgentCanvasStyleSelector
        workflowId="workflow-1"
        activeStyle={activeStyle}
        onWorkflowRefresh={refreshWorkflow}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Style: Platform Default" }));
    const dialog = await screen.findByRole("dialog", { name: "Choose video Style" });
    fireEvent.click(within(dialog).getByRole("tab", { name: "Cinematic Narrative" }));
    fireEvent.click(within(dialog).getByRole("button", { name: /Cinematic Poetic Realism/ }));

    await waitFor(() => expect(refreshWorkflow).toHaveBeenCalledOnce());
    expect((await screen.findByRole("alert")).textContent).toContain(
      "The active Style changed in another session.",
    );
    expect(screen.getByRole("dialog", { name: "Choose video Style" })).toBeTruthy();
  });
});
