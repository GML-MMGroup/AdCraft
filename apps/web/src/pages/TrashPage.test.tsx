import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockState = vi.hoisted(() => ({
  trashedProjects: [
    {
      project_id: "project-trash-1",
      workflow_id: "workflow-trash-1",
      name: "Archived campaign",
      updated_at: "2026-08-18T00:00:00Z",
    },
  ],
  restoreTrashedProject: vi.fn(async () => true),
}));

vi.mock("../AppContextValue", () => ({
  useApp: () => ({
    trashedProjects: mockState.trashedProjects,
    restoreTrashedProject: mockState.restoreTrashedProject,
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
    mockState.trashedProjects = [{
      project_id: "project-trash-1",
      workflow_id: "workflow-trash-1",
      name: "Archived campaign",
      updated_at: "2026-08-18T00:00:00Z",
    }];
  });

  it("renders only backend projects and restores them through the Project API action", () => {
    render(<TrashPage />);

    expect(screen.getByText("Archived campaign")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Roles" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Scenes" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Restore" }));
    expect(mockState.restoreTrashedProject).toHaveBeenCalledWith("project-trash-1");
  });

  it("uses the Projects toolbar and lets a card be selected without restoring it", () => {
    render(<TrashPage />);

    expect(screen.getByRole("button", { name: "Projects" }).className).toContain("filter-btn clear-glass-control");
    expect(screen.getByPlaceholderText("Search deleted items").className).toContain("search-box clear-glass-control is-active");

    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    expect(screen.getByRole("button", { name: "Select all" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Done" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Restore" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Select Archived campaign" }));

    expect((screen.getByRole("checkbox", { name: "Select Archived campaign" }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText("1 selected")).toBeTruthy();
    expect(mockState.restoreTrashedProject).not.toHaveBeenCalled();
  });

  it("selects only the filtered trash results and clears selection when search changes", () => {
    mockState.trashedProjects = [
      {
        project_id: "project-trash-1",
        workflow_id: "workflow-trash-1",
        name: "Archived campaign",
        updated_at: "2026-08-18T00:00:00Z",
      },
      {
        project_id: "project-trash-2",
        workflow_id: "workflow-trash-2",
        name: "Old product film",
        updated_at: "2026-08-17T00:00:00Z",
      },
    ];
    render(<TrashPage />);

    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    fireEvent.click(screen.getByRole("button", { name: "Select all" }));
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
    expect(screen.getAllByRole("checkbox").every((checkbox) => (checkbox as HTMLInputElement).checked)).toBe(true);
    expect(screen.getByRole("button", { name: "Clear selection" })).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText("Search deleted items"), { target: { value: "product" } });

    expect(screen.getByText("0 selected")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Select all" })).toBeTruthy();
    expect((screen.getByRole("checkbox", { name: "Select Old product film" }) as HTMLInputElement).checked).toBe(false);
    expect(screen.queryByRole("checkbox", { name: "Select Archived campaign" })).toBeNull();
  });

  it("restores selected projects in one batch and exits selection mode after success", async () => {
    mockState.trashedProjects = [
      {
        project_id: "project-trash-1",
        workflow_id: "workflow-trash-1",
        name: "Archived campaign",
        updated_at: "2026-08-18T00:00:00Z",
      },
      {
        project_id: "project-trash-2",
        workflow_id: "workflow-trash-2",
        name: "Old product film",
        updated_at: "2026-08-17T00:00:00Z",
      },
    ];
    render(<TrashPage />);

    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    fireEvent.click(screen.getByRole("button", { name: "Select all" }));
    fireEvent.click(screen.getByRole("button", { name: "Restore selected" }));

    await waitFor(() => expect(mockState.restoreTrashedProject).toHaveBeenCalledTimes(2));
    expect(mockState.restoreTrashedProject).toHaveBeenNthCalledWith(1, "project-trash-1");
    expect(mockState.restoreTrashedProject).toHaveBeenNthCalledWith(2, "project-trash-2");
    expect(screen.getByRole("button", { name: "Select" })).toBeTruthy();
  });

  it("keeps failed projects selected and reports a partial restore failure", async () => {
    mockState.trashedProjects = [
      {
        project_id: "project-trash-1",
        workflow_id: "workflow-trash-1",
        name: "Archived campaign",
        updated_at: "2026-08-18T00:00:00Z",
      },
      {
        project_id: "project-trash-2",
        workflow_id: "workflow-trash-2",
        name: "Old product film",
        updated_at: "2026-08-17T00:00:00Z",
      },
    ];
    mockState.restoreTrashedProject.mockImplementation(async (projectId) => {
      if (projectId === "project-trash-2") throw new Error("restore failed");
      return true;
    });
    render(<TrashPage />);

    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    fireEvent.click(screen.getByRole("button", { name: "Select Old product film" }));
    fireEvent.click(screen.getByRole("button", { name: "Restore selected" }));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("1 project could not be restored"));
    expect((screen.getByRole("checkbox", { name: "Select Old product film" }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole("button", { name: "Done" })).toBeTruthy();
  });

  it("clears all selection state when Done is pressed", () => {
    render(<TrashPage />);

    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    fireEvent.click(screen.getByRole("button", { name: "Select Archived campaign" }));
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    expect(screen.getByRole("button", { name: "Select" })).toBeTruthy();
    expect(screen.queryByText("1 selected")).toBeNull();
    expect(screen.queryByRole("checkbox", { name: "Select Archived campaign" })).toBeNull();
  });
});
