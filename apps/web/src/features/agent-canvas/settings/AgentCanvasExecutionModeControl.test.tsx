import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { agentCanvasApi, V2ApiError } from "../../../api/agentCanvasApi.ts";
import { AgentCanvasExecutionModeControl } from "./AgentCanvasExecutionModeControl.tsx";

const manualSettings = {
  workflow_id: "workflow-1",
  media_execution_mode: "manual" as const,
  revision: 1,
  created_at: "2026-08-06T08:00:00Z",
  updated_at: "2026-08-06T08:00:00Z",
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("AgentCanvasExecutionModeControl", () => {
  it("does not claim a guidance authority before a guided session exists", async () => {
    vi.spyOn(agentCanvasApi, "agentCanvasExecutionSettings").mockResolvedValue({
      value: manualSettings,
      etag: '"1"',
    });

    render(
      <AgentCanvasExecutionModeControl
        workflowId="workflow-1"
        guidanceMode={null}
        eventRevision={0}
      />,
    );

    expect(await screen.findByText("Not started")).toBeTruthy();
  });

  it("keeps guidance authority and media execution as independent controls", async () => {
    vi.spyOn(agentCanvasApi, "agentCanvasExecutionSettings").mockResolvedValue({
      value: manualSettings,
      etag: '"1"',
    });
    const patch = vi.spyOn(agentCanvasApi, "patchAgentCanvasExecutionSettings")
      .mockResolvedValue({
        value: {
          ...manualSettings,
          media_execution_mode: "automatic",
          revision: 2,
          updated_at: "2026-08-06T08:01:00Z",
        },
        etag: '"2"',
      });

    render(
      <AgentCanvasExecutionModeControl
        workflowId="workflow-1"
        guidanceMode="collaborative"
        eventRevision={0}
      />,
    );

    expect(await screen.findByText("Collaborative")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Automatic media execution" }));

    await waitFor(() => expect(patch).toHaveBeenCalledWith(
      "workflow-1",
      { media_execution_mode: "automatic" },
      1,
    ));
    expect(screen.getByRole("button", { name: "Automatic media execution" })
      .getAttribute("aria-pressed")).toBe("true");
  });

  it("refreshes a stale setting and waits for an explicit retry after 412", async () => {
    const read = vi.spyOn(agentCanvasApi, "agentCanvasExecutionSettings")
      .mockResolvedValueOnce({ value: manualSettings, etag: '"1"' })
      .mockResolvedValueOnce({
        value: { ...manualSettings, revision: 2 },
        etag: '"2"',
      });
    const patch = vi.spyOn(agentCanvasApi, "patchAgentCanvasExecutionSettings")
      .mockRejectedValueOnce(new V2ApiError({
        status: 412,
        code: "agent_settings_revision_conflict",
        message: "Settings changed elsewhere.",
        details: { current_revision: 2 },
        violations: [],
        suggestedActions: [],
        payload: null,
      }))
      .mockResolvedValueOnce({
        value: {
          ...manualSettings,
          media_execution_mode: "automatic",
          revision: 3,
          updated_at: "2026-08-06T08:02:00Z",
        },
        etag: '"3"',
      });

    render(
      <AgentCanvasExecutionModeControl
        workflowId="workflow-1"
        guidanceMode="delegated"
        eventRevision={0}
      />,
    );

    await screen.findByText("Delegated");
    fireEvent.click(screen.getByRole("button", { name: "Automatic media execution" }));

    expect(await screen.findByText(/changed in another session/i)).toBeTruthy();
    expect(read).toHaveBeenCalledTimes(2);
    expect(patch).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Retry Automatic" }));

    await waitFor(() => expect(patch).toHaveBeenCalledTimes(2));
    expect(patch).toHaveBeenLastCalledWith(
      "workflow-1",
      { media_execution_mode: "automatic" },
      2,
    );
  });
});
