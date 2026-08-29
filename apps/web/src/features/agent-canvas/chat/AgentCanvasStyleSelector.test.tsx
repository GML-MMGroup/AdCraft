import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { agentCanvasApi, V2ApiError } from "../../../api/agentCanvasApi.ts";
import type { ActiveStyleSkillSummaryV2, VideoSkillCatalogResponseV2 } from "../../../types-v2.ts";
import { __resetStableMediaCacheForTests } from "../../../workflow/stableMediaCache.ts";
import { AgentCanvasStyleSelector } from "./AgentCanvasStyleSelector.tsx";
import { SkillPreview } from "./SkillPreview.tsx";

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
      preview: { kind: "image", summary: "Internal preview description.", media_url: "/styles/cinematic.jpg" },
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
  __resetStableMediaCacheForTests();
  vi.restoreAllMocks();
});

describe("AgentCanvasStyleSelector", () => {
  it("renders the backend-provided Skill preview URL without a frontend Skill map", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("image", { status: 200 }));
    render(
      <SkillPreview
        preview={{
          kind: "image",
          summary: "Public preview.",
          media_url: "/api/v2/video-skills/cinematic/preview?v=1.0.0",
        }}
      />,
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v2/video-skills/cinematic/preview?v=1.0.0",
      expect.objectContaining({ cache: "force-cache", credentials: "same-origin" }),
    ));
    expect(document.querySelector("img")?.getAttribute("loading")).toBe("lazy");
  });

  it("uses the Skill asset for the compact trigger and exposes a Skill tooltip", () => {
    render(
      <AgentCanvasStyleSelector
        workflowId="workflow-1"
        activeStyle={activeStyle}
        onWorkflowRefresh={vi.fn()}
      />,
    );

    const trigger = screen.getByRole("button", { name: "Skill" });
    expect(trigger.getAttribute("title")).toBe("Skill");
    expect(trigger.querySelector("img")?.getAttribute("src")).toBe("/imgs/ui-icons/skill.svg");
    expect(trigger.textContent).toBe("");
  });

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
    fireEvent.click(screen.getByRole("button", { name: "Skill" }));

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
    expect(within(dialog).queryByText("general advertising")).toBeNull();
    expect(within(dialog).queryByText("commercial")).toBeNull();
    expect(within(dialog).getByText("Choose visual language")).toBeTruthy();
    expect(within(dialog).queryByText("Using · Platform Default")).toBeNull();
  });

  it("renders the Skill picker in a viewport-level modal like Agent Documents", async () => {
    vi.spyOn(agentCanvasApi, "listVideoSkills").mockResolvedValue(catalog);

    render(
      <AgentCanvasStyleSelector
        workflowId="workflow-1"
        activeStyle={activeStyle}
        onWorkflowRefresh={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Skill" }));
    const dialog = await screen.findByRole("dialog", { name: "Choose video Style" });
    const overlay = document.body.querySelector(".agent-chat__style-overlay");

    expect(overlay?.contains(dialog)).toBe(true);
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(dialog.parentElement).toBe(overlay);
  });

  it("uses the Agent Documents monochrome shell and a mobile-safe card layout", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const panelRule = css.match(/\.agent-chat__style-menu\s*\{([\s\S]*?)\n\}/m)?.[1];
    const headerRule = css.match(/\.agent-chat__style-menu-header\s*\{([\s\S]*?)\n\}/m)?.[1];
    const closeRule = css.match(/\.agent-chat__style-menu-header button\s*\{([\s\S]*?)\n\}/m)?.[1];
    const categoryButtonRule = css.match(/\.agent-chat__style-categories button\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(css).toContain("--style-panel: #181818;");
    expect(css).toContain("--style-header: #1c1c1c;");
    expect(css).toContain("--style-surface: #222222;");
    expect(panelRule).toContain("background: var(--style-panel)");
    expect(panelRule).toContain("width: min(880px, calc(100vw - 48px))");
    expect(panelRule).toContain("max-height: min(860px, calc(100dvh - 48px))");
    expect(panelRule).toContain("box-shadow: 0 24px 58px rgb(0 0 0 / 58%)");
    expect(headerRule).toContain("background: var(--style-header)");
    expect(closeRule).toContain("width: 30px");
    expect(closeRule).toContain("border: 1px solid var(--style-border)");
    expect(css).toMatch(
      /@media \(max-width: 560px\)[\s\S]*\.agent-chat__style-list\s*\{[\s\S]*grid-template-columns: minmax\(0, 1fr\)/,
    );
    expect(panelRule).toBeTruthy();
    const styleListRule = css.match(/\.agent-chat__style-list\s*\{([\s\S]*?)\n\}/m)?.[1];
    expect(styleListRule).toContain("height: min(602px, calc(56.25vw + 89px))");
    expect(styleListRule).toContain("max-height: calc(100dvh - 170px)");
    expect(styleListRule).toContain("grid-auto-rows: max-content");
    expect(styleListRule).toContain("overflow-y: auto");
    expect(css).toContain("height: min(620px, calc(100dvh - 170px))");
    expect(css).toContain("min-height: 32px");
    expect(css).toContain("padding: 7px 11px");
    expect(categoryButtonRule).toContain("font-size: 11px");
  });

  it("fills the modal with a card-shaped loading state while the catalog is pending", async () => {
    let resolveCatalog!: (value: VideoSkillCatalogResponseV2) => void;
    const pendingCatalog = new Promise<VideoSkillCatalogResponseV2>((resolve) => {
      resolveCatalog = resolve;
    });
    vi.spyOn(agentCanvasApi, "listVideoSkills").mockReturnValue(pendingCatalog);

    render(
      <AgentCanvasStyleSelector
        workflowId="workflow-1"
        activeStyle={activeStyle}
        onWorkflowRefresh={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Skill" }));
    const dialog = await screen.findByRole("dialog", { name: "Choose video Style" });
    expect(within(dialog).getByRole("status", { name: "Loading Style previews" })).toBeTruthy();
    expect(within(dialog).getAllByTestId("style-loading-card")).toHaveLength(4);

    resolveCatalog(catalog);
    await waitFor(() => expect(within(dialog).getByRole("button", { name: /Platform Default/ })).toBeTruthy());
  });

  it("projects each Style as a visual card without internal catalog metadata", async () => {
    vi.spyOn(agentCanvasApi, "listVideoSkills").mockResolvedValue(catalog);

    render(
      <AgentCanvasStyleSelector
        workflowId="workflow-1"
        activeStyle={activeStyle}
        onWorkflowRefresh={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Skill" }));
    const dialog = await screen.findByRole("dialog", { name: "Choose video Style" });
    fireEvent.click(within(dialog).getByRole("tab", { name: "Cinematic Narrative" }));

    const option = within(dialog).getByRole("button", { name: /Cinematic Poetic Realism/ });
    expect(option.className).toContain("agent-chat__style-option");
    expect(option.querySelector("img")?.getAttribute("src")).toBe("/styles/cinematic.jpg");
    expect(within(option).getByText("A restrained cinematic treatment.")).toBeTruthy();
    expect(within(option).queryByText("Internal preview description.")).toBeNull();
    expect(within(option).queryByText("cinematic")).toBeNull();
    expect(within(option).queryByText("brand film")).toBeNull();
    expect(within(option).queryByText("1.0.0")).toBeNull();
  });

  it("uses a film placeholder when a Style has no public preview", async () => {
    vi.spyOn(agentCanvasApi, "listVideoSkills").mockResolvedValue(catalog);

    render(
      <AgentCanvasStyleSelector
        workflowId="workflow-1"
        activeStyle={activeStyle}
        onWorkflowRefresh={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Skill" }));
    const dialog = await screen.findByRole("dialog", { name: "Choose video Style" });
    expect(within(dialog).getByRole("button", { name: /Platform Default/ }).getAttribute("data-preview"))
      .toBe("placeholder");
  });

  it("never renders a Skill search box, even for a large catalog", async () => {
    const largeCatalog: VideoSkillCatalogResponseV2 = {
      ...catalog,
      items: Array.from({ length: 9 }, (_, index) => ({
        ...catalog.items[0],
        skill_id: `cinematic-${index}`,
        title: `Cinematic ${index}`,
        display_order: index,
      })),
    };
    vi.spyOn(agentCanvasApi, "listVideoSkills").mockResolvedValue(largeCatalog);

    render(
      <AgentCanvasStyleSelector
        workflowId="workflow-1"
        activeStyle={activeStyle}
        onWorkflowRefresh={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Skill" }));
    const dialog = await screen.findByRole("dialog", { name: "Choose video Style" });
    expect(within(dialog).queryByRole("searchbox")).toBeNull();
    fireEvent.click(within(dialog).getByRole("tab", { name: "Cinematic Narrative" }));
    expect(within(dialog).getAllByText(/^Cinematic \d+$/)).toHaveLength(9);

    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const listRule = css.match(/\.agent-chat__style-list\s*\{([\s\S]*?)\n\}/m)?.[1];
    const cardRule = css.match(/\.agent-chat__style-menu \.agent-chat__style-option\s*\{([\s\S]*?)\n\}/m)?.[1];
    const previewRule = css.match(/\.agent-chat__style-preview\s*\{([\s\S]*?)\n\}/m)?.[1];
    expect(listRule).toContain("grid-template-columns: repeat(2, minmax(0, 1fr))");
    expect(listRule).toContain("flex: 0 1 auto");
    expect(listRule).toContain("min-height: 0");
    expect(listRule).toContain("overflow-y: auto");
    expect(cardRule).toContain("display: flex");
    expect(cardRule).toContain("flex-direction: column");
    expect(previewRule).toContain("width: 100%");
    expect(previewRule).toContain("aspect-ratio: 16 / 9");
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

    fireEvent.click(screen.getByRole("button", { name: "Skill" }));
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

    fireEvent.click(screen.getByRole("button", { name: "Skill" }));
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

    fireEvent.click(screen.getByRole("button", { name: "Skill" }));
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

    fireEvent.click(screen.getByRole("button", { name: "Skill" }));
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
