import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { agentCanvasApi, V2ApiError } from "../../../api/agentCanvasApi.ts";
import { AgentCanvasExecutionModeControl } from "./AgentCanvasExecutionModeControl.tsx";
import { __resetExecutionSettingsReadsForTests } from "./useAgentCanvasExecutionSettings.ts";

const manualSettings = {
  workflow_id: "workflow-1",
  media_execution_mode: "manual" as const,
  revision: 1,
  created_at: "2026-08-06T08:00:00Z",
  updated_at: "2026-08-06T08:00:00Z",
};

afterEach(() => {
  cleanup();
  __resetExecutionSettingsReadsForTests();
  vi.restoreAllMocks();
});

describe("AgentCanvasExecutionModeControl", () => {
  it("renders one Collaboration control without guidance or authority modes", async () => {
    vi.spyOn(agentCanvasApi, "agentCanvasExecutionSettings").mockResolvedValue({
      value: manualSettings,
      etag: '"1"',
    });

    render(
      <AgentCanvasExecutionModeControl
        workflowId="workflow-1"
        eventRevision={0}
      />,
    );

    expect(await screen.findByText("Collaboration")).toBeTruthy();
    expect(screen.getByRole("switch", { name: "Automatic media collaboration" })).toBeTruthy();
    expect(screen.queryByText("Guidance")).toBeNull();
    expect(screen.queryByText("Delegated")).toBeNull();
    expect(screen.queryByText("Collaborative")).toBeNull();
  });

  it("reuses the initial settings read when StrictMode mounts the control twice", async () => {
    const read = vi.spyOn(agentCanvasApi, "agentCanvasExecutionSettings")
      .mockResolvedValue({ value: manualSettings, etag: '"1"' });

    render(
      <StrictMode>
        <AgentCanvasExecutionModeControl workflowId="workflow-1" eventRevision={0} />
      </StrictMode>,
    );

    expect(await screen.findByText("Collaboration")).toBeTruthy();
    expect(read).toHaveBeenCalledOnce();
  });

  it("changes only future eligible media Draft auto-run behavior", async () => {
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
        eventRevision={0}
      />,
    );

    const collaboration = await screen.findByRole("switch", { name: "Automatic media collaboration" });
    fireEvent.click(collaboration);

    await waitFor(() => expect(patch).toHaveBeenCalledWith(
      "workflow-1",
      { media_execution_mode: "automatic" },
      1,
    ));
    expect(collaboration.getAttribute("aria-checked")).toBe("true");
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
        eventRevision={0}
      />,
    );

    fireEvent.click(await screen.findByRole("switch", { name: "Automatic media collaboration" }));

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
