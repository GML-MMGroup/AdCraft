import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { agentCanvasApi } from "../../../api/agentCanvasApi.ts";
import type {
  AgentWorkingDocumentV2,
  ChatAgentDocumentReferenceV2,
} from "../../../types-v2.ts";
import {
  AgentCanvasDocumentBrowser,
  AgentCanvasDocumentReferenceCard,
} from "./AgentCanvasDocuments.tsx";

const storyboardDocument: AgentWorkingDocumentV2 = {
  document_id: "doc-plan-1",
  workflow_id: "workflow-1",
  guidance_session_id: "session-1",
  kind: "storyboard_production_plan",
  title: "Pressure cooker storyboard plan",
  revision: 4,
  content_digest: "sha256:plan",
  content: {
    narrative_outline: "A high-pressure day resolves into a calm family dinner.",
    global_parameters: {
      aspect_ratio: "16:9",
      total_duration_seconds: 15,
      segment_count: 1,
    },
    segments: [{
      sequence_id: "sequence-1",
      order: 1,
      start_seconds: 0,
      end_seconds: 15,
      narrative_goal: "Reveal the benefit.",
      start_state: "Busy kitchen.",
      end_state: "Dinner served.",
      continuity_from_previous: null,
    }],
    rows: [{
      shot_index: 1,
      sequence_id: "sequence-1",
      panel_index: 1,
      content_beat: "Steam clears to reveal the cooker.",
      anchor_aliases: ["PRODUCT"],
      camera_description: "Slow push in.",
    }],
    node_records: [{
      sequence_id: "sequence-1",
      node_role: "storyboard_grid",
      node_id: "node-grid-1",
    }],
    materialized_panel_cursor: 1,
    segment_materializations: [{
      sequence_id: "sequence-1",
      status: "materialized",
      generation_prompt: "Generate a calm product reveal with a slow push in.",
    }],
    visual_anchor: {
      node_id: "node-grid-1",
      asset_id: "asset-grid-1",
      node_revision: 3,
      document_revision: 4,
    },
  },
  created_by_agent_run_id: "run-1",
  updated_by_agent_run_id: "run-2",
  linked_nodes: [{
    node_id: "node-grid-1",
    node_type: "image",
    creative_role: "storyboard_sequence",
    status: "ready",
    revision: 3,
  }],
  created_at: "2026-08-06T08:00:00Z",
  updated_at: "2026-08-06T08:03:00Z",
};

const reference: ChatAgentDocumentReferenceV2 = {
  item_type: "agent_document",
  document_id: "doc-plan-1",
  document_kind: "storyboard_production_plan",
  revision: 4,
  content_digest: "sha256:plan",
  title: "Pressure cooker storyboard plan",
  sequence: 3,
  created_at: "2026-08-06T08:03:00Z",
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Agent Canvas Documents", () => {
  it("keeps a timeline document compact and loads its details in a viewport dialog on demand", async () => {
    const getDocument = vi.spyOn(agentCanvasApi, "agentCanvasDocument").mockResolvedValue(storyboardDocument);
    const focusNode = vi.fn();

    const { container } = render(
      <AgentCanvasDocumentReferenceCard
        workflowId="workflow-1"
        reference={reference}
        documentEvents={[]}
        onFocusNode={focusNode}
      />,
    );

    const entry = screen.getByRole("button", { name: "Open Pressure cooker storyboard plan" });
    expect(screen.getByText("Storyboard Production Plan · revision 4")).toBeTruthy();
    expect(screen.queryByText("15s")).toBeNull();
    expect(getDocument).not.toHaveBeenCalled();

    fireEvent.click(entry);

    const dialog = await screen.findByRole("dialog", { name: "Pressure cooker storyboard plan" });
    expect(container.contains(dialog)).toBe(false);
    expect(getDocument).toHaveBeenCalledWith("workflow-1", "doc-plan-1");
    expect(await screen.findByText("15s")).toBeTruthy();
    expect(screen.getByText("16:9")).toBeTruthy();
    expect(screen.getByText("Steam clears to reveal the cooker.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Open storyboard grid/i }));
    expect(focusNode).toHaveBeenCalledWith("node-grid-1");
    expect(screen.queryByRole("dialog", { name: "Pressure cooker storyboard plan" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Run/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /Delete/i })).toBeNull();
  });

  it("uses the same compact timeline entry for Anchor Registry documents", () => {
    const getDocument = vi.spyOn(agentCanvasApi, "agentCanvasDocument");

    render(
      <AgentCanvasDocumentReferenceCard
        workflowId="workflow-1"
        reference={{
          ...reference,
          document_id: "doc-anchors-1",
          document_kind: "anchor_registry",
          revision: 8,
          content_digest: "sha256:anchors",
          title: "Anchor Registry",
        }}
        documentEvents={[]}
        onFocusNode={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Open Anchor Registry" })).toBeTruthy();
    expect(screen.getByText("Anchor Registry · revision 8")).toBeTruthy();
    expect(getDocument).not.toHaveBeenCalled();
  });

  it("filters and paginates the document browser using backend cursors", async () => {
    const list = vi.spyOn(agentCanvasApi, "listAgentCanvasDocuments")
      .mockResolvedValueOnce({ items: [storyboardDocument], next_cursor: "cursor-2" })
      .mockResolvedValue({ items: [], next_cursor: null });

    render(
      <AgentCanvasDocumentBrowser
        workflowId="workflow-1"
        documentEvents={[]}
        onFocusNode={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open Agent Documents" }));
    expect(await screen.findByText("Pressure cooker storyboard plan")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Load more documents" }));

    await waitFor(() => expect(list).toHaveBeenLastCalledWith("workflow-1", {
      kind: undefined,
      cursor: "cursor-2",
      limit: 20,
    }));
    fireEvent.click(screen.getByRole("button", { name: "Storyboard plans" }));
    await waitFor(() => expect(list).toHaveBeenLastCalledWith("workflow-1", {
      kind: "storyboard_production_plan",
      cursor: undefined,
      limit: 20,
    }));
  });

  it("opens Agent Documents in a viewport portal and closes it with Escape", async () => {
    vi.spyOn(agentCanvasApi, "listAgentCanvasDocuments")
      .mockResolvedValue({ items: [storyboardDocument], next_cursor: null });
    const { container } = render(
      <AgentCanvasDocumentBrowser
        workflowId="workflow-1"
        documentEvents={[]}
        onFocusNode={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open Agent Documents" }));

    const dialog = await screen.findByRole("dialog", { name: "Agent Documents" });
    expect(container.contains(dialog)).toBe(false);
    expect(document.body.querySelector(".agent-document-browser__overlay")?.contains(dialog)).toBe(true);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Agent Documents" })).toBeNull();
  });

  it("centers the Agent Documents overlay in the viewport", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/documents/agent-canvas-documents.css");
    const css = readFileSync(cssPath, "utf8");
    const overlayRule = css.match(/\.agent-document-browser__overlay\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(overlayRule).toBeTruthy();
    expect(overlayRule).toContain("position: fixed");
    expect(overlayRule).toContain("inset: 0");
    expect(overlayRule).toContain("place-items: center");
  });

  it("uses the dedicated monochrome production-document palette", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/documents/agent-canvas-documents.css");
    const css = readFileSync(cssPath, "utf8");
    const panelRule = css.match(/\.agent-document-browser__panel\s*\{([\s\S]*?)\n\}/m)?.[1];
    const selectedFilterRule = css.match(/\.agent-document-browser__filters button\.is-selected\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(css).toContain("--document-panel: #181818");
    expect(css).toContain("--document-surface: #222222");
    expect(css).toContain("--document-text: #f2f2f2");
    expect(css).toContain("--document-danger: #ca6f6f");
    expect(panelRule).toContain("background: var(--document-panel)");
    expect(selectedFilterRule).toContain("background: #e5e5e5");
    expect(selectedFilterRule).toContain("color: #181818");
    expect(css).not.toContain("var(--accent)");
    expect(css).not.toContain("var(--brand-hover)");
  });
});
