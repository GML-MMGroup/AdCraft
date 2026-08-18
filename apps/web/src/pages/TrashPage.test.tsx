import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const restoreTrashedProject = vi.fn(async () => true);

vi.mock("../AppContextValue", () => ({
  useApp: () => ({
    trashedProjects: [{
      project_id: "project-trash-1",
      workflow_id: "workflow-trash-1",
      name: "Archived campaign",
      updated_at: "2026-08-18T00:00:00Z",
    }],
    restoreTrashedProject,
    projectCatalogError: null,
    projectCatalogRefreshing: false,
    refreshProjects: vi.fn(async () => true),
  }),
}));

import { TrashPage } from "./TrashPage.tsx";

describe("TrashPage", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders only backend projects and restores them through the Project API action", () => {
    render(<TrashPage />);

    expect(screen.getByText("Archived campaign")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Roles" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Scenes" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Restore" }));
    expect(restoreTrashedProject).toHaveBeenCalledWith("project-trash-1");
  });
});
