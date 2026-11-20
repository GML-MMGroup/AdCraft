import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "../i18n/locale.tsx";

const mockState = vi.hoisted(() => ({
  trashedProjects: [
    {
      project_id: "project-trash-1",
      workflow_id: "workflow-trash-1",
      name: "Archived campaign",
      project_version: 2, updated_at: "2026-08-18T00:00:00Z",
    },
  ],
  restoreTrashedProject: vi.fn(async () => true),
  permanentlyDeleteTrashedProject: vi.fn(async (_projectId: string, _projectVersion: number) => true),
  refreshProjects: vi.fn(async () => true),
}));

vi.mock("../AppContextValue", () => ({
  useApp: () => ({
    trashedProjects: mockState.trashedProjects,
    restoreTrashedProject: mockState.restoreTrashedProject,
    permanentlyDeleteTrashedProject: mockState.permanentlyDeleteTrashedProject,
    projectCatalogError: null,
    projectCatalogRefreshing: false,
    refreshProjects: mockState.refreshProjects,
  }),
}));

import { TrashPage } from "./TrashPage.tsx";

describe("TrashPage", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.restoreAllMocks();
    window.localStorage.removeItem("adcraft.locale");
    mockState.permanentlyDeleteTrashedProject.mockResolvedValue(true);
    mockState.trashedProjects = [{
      project_id: "project-trash-1",
      workflow_id: "workflow-trash-1",
      name: "Archived campaign",
      project_version: 2, updated_at: "2026-08-18T00:00:00Z",
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
        project_version: 2, updated_at: "2026-08-18T00:00:00Z",
      },
      {
        project_id: "project-trash-2",
        workflow_id: "workflow-trash-2",
        name: "Old product film",
        project_version: 2, updated_at: "2026-08-17T00:00:00Z",
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
        project_version: 2, updated_at: "2026-08-18T00:00:00Z",
      },
      {
        project_id: "project-trash-2",
        workflow_id: "workflow-trash-2",
        name: "Old product film",
        project_version: 2, updated_at: "2026-08-17T00:00:00Z",
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
        project_version: 2, updated_at: "2026-08-18T00:00:00Z",
      },
      {
        project_id: "project-trash-2",
        workflow_id: "workflow-trash-2",
        name: "Old product film",
        project_version: 2, updated_at: "2026-08-17T00:00:00Z",
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

  it("requires confirmation before permanently deleting a project", async () => {
    const confirmation = vi.spyOn(window, "confirm");
    render(<TrashPage />);
    const button = screen.getByRole("button", { name: "Delete permanently" });
    expect((button as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(button);
    let dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByText("Archived campaign")).toBeTruthy();
    expect(within(dialog).getByText(/Shared assets/)).toBeTruthy();
    expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(mockState.permanentlyDeleteTrashedProject).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(mockState.permanentlyDeleteTrashedProject).not.toHaveBeenCalled();
    fireEvent.click(button);
    dialog = screen.getByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(mockState.permanentlyDeleteTrashedProject).toHaveBeenCalledWith("project-trash-1", 2));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(mockState.refreshProjects).toHaveBeenCalledTimes(1);
    expect(confirmation).not.toHaveBeenCalled();
  });

  it("deletes only selected projects and retains failures for retry", async () => {
    mockState.permanentlyDeleteTrashedProject.mockRejectedValueOnce(new Error("Still running"));
    render(<TrashPage />);
    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    fireEvent.click(screen.getByRole("button", { name: "Select Archived campaign" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete selected" }));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Still running"));
    expect(mockState.permanentlyDeleteTrashedProject).toHaveBeenCalledTimes(1);
    expect((screen.getByRole("checkbox", { name: "Select Archived campaign" }) as HTMLInputElement).checked).toBe(true);
  });

  it("empty trash confirms the complete snapshot even when search filters the list", async () => {
    mockState.trashedProjects.push({ project_id: "project-trash-2", workflow_id: "workflow-trash-2", name: "Second campaign", project_version: 2, updated_at: "2026-08-18T00:00:00Z" });
    render(<TrashPage />);
    fireEvent.change(screen.getByPlaceholderText("Search deleted items"), { target: { value: "Archived" } });
    fireEvent.click(screen.getByRole("button", { name: "Empty trash" }));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByRole("heading", { name: "Permanently delete 2 projects?" })).toBeTruthy();
    expect(within(dialog).getByText("Second campaign")).toBeTruthy();
    expect(mockState.permanentlyDeleteTrashedProject).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(mockState.permanentlyDeleteTrashedProject).toHaveBeenCalledTimes(2));
  });

  it("contains keyboard focus and restores it after Escape or backdrop dismissal", () => {
    render(<TrashPage />);
    const trigger = screen.getByRole("button", { name: "Delete permanently" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("alertdialog");
    const first = within(dialog).getByRole("button", { name: "Close" });
    const last = within(dialog).getByRole("button", { name: "Delete permanently" });
    first.focus();
    fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
    fireEvent.keyDown(last, { key: "Tab" });
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(first, { key: "Escape" });
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
    fireEvent.click(trigger);
    fireEvent.pointerDown(screen.getByRole("alertdialog").parentElement!);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(mockState.permanentlyDeleteTrashedProject).not.toHaveBeenCalled();
  });

  it("keeps the confirmation open and prevents duplicate submissions while deleting", async () => {
    let resolveDelete!: (result: boolean) => void;
    mockState.permanentlyDeleteTrashedProject.mockReturnValueOnce(new Promise((resolve) => { resolveDelete = resolve; }));
    render(<TrashPage />);
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    const dialog = screen.getByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete permanently" }));
    expect(dialog.getAttribute("aria-busy")).toBe("true");
    const cancelDeletion = within(dialog).getByRole("button", { name: "Cancel deletion" });
    expect((cancelDeletion as HTMLButtonElement).disabled).toBe(false);
    expect(within(dialog).queryByRole("button", { name: "Delete permanently" })).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    fireEvent.keyDown(dialog, { key: "Escape" });
    fireEvent.pointerDown(dialog.parentElement!);
    expect(screen.getByRole("alertdialog")).toBe(dialog);
    expect(mockState.permanentlyDeleteTrashedProject).toHaveBeenCalledTimes(1);
    resolveDelete(true);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("cancels subsequent deletions, settles the current project and allows the remaining selection to be retried", async () => {
    let resolveCurrent!: (result: boolean) => void;
    mockState.trashedProjects = [1, 2, 3].map((index) => ({
      project_id: `project-trash-${index}`, workflow_id: `workflow-trash-${index}`,
      name: `Campaign ${index}`, project_version: 2, updated_at: "2026-08-18T00:00:00Z",
    }));
    mockState.permanentlyDeleteTrashedProject
      .mockResolvedValueOnce(true)
      .mockReturnValueOnce(new Promise((resolve) => { resolveCurrent = resolve; }));
    mockState.refreshProjects.mockImplementationOnce(async () => {
      mockState.trashedProjects = mockState.trashedProjects.filter((project) => project.project_id === "project-trash-3");
      return true;
    });
    render(<TrashPage />);
    fireEvent.click(screen.getByRole("button", { name: "Empty trash" }));
    let dialog = screen.getByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(within(dialog).getByRole("progressbar").getAttribute("value")).toBe("1"));
    expect(within(dialog).getByText("Processed 1/3 projects")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel deletion" }));
    expect((within(dialog).getByRole("button", { name: "Cancelling…" }) as HTMLButtonElement).disabled).toBe(true);
    expect(within(dialog).getByText("Cancelling. The current project will finish before deletion stops.")).toBeTruthy();
    expect(mockState.permanentlyDeleteTrashedProject).toHaveBeenCalledTimes(2);
    await act(async () => resolveCurrent(true));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(mockState.permanentlyDeleteTrashedProject).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Deletion stopped. 2 deleted; 1 left in Trash.")).toBeTruthy();
    expect((screen.getByRole("checkbox", { name: "Select Campaign 3" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Delete selected" }));
    dialog = screen.getByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(mockState.permanentlyDeleteTrashedProject).toHaveBeenCalledTimes(3));
    expect(mockState.permanentlyDeleteTrashedProject).toHaveBeenLastCalledWith("project-trash-3", 2);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("uses the project version displayed when the confirmation opened", async () => {
    const { rerender } = render(<TrashPage />);
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    mockState.trashedProjects = mockState.trashedProjects.map((project) => ({ ...project, project_version: 3 }));
    rerender(<TrashPage />);
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(mockState.permanentlyDeleteTrashedProject).toHaveBeenCalledWith("project-trash-1", 2));
  });

  it("advances progress only as requests settle, counts failures and resets for the next deletion", async () => {
    let resolveFirst!: (result: boolean) => void;
    let rejectSecond!: (reason: unknown) => void;
    let resolveThird!: (result: boolean) => void;
    let resolveRefresh!: (result: boolean) => void;
    let resolveRetry!: (result: boolean) => void;
    mockState.trashedProjects = [1, 2, 3].map((index) => ({
      project_id: `project-trash-${index}`, workflow_id: `workflow-trash-${index}`,
      name: `Campaign ${index}`, project_version: 2, updated_at: "2026-08-18T00:00:00Z",
    }));
    mockState.permanentlyDeleteTrashedProject
      .mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve; }))
      .mockReturnValueOnce(new Promise((_, reject) => { rejectSecond = reject; }))
      .mockReturnValueOnce(new Promise((resolve) => { resolveThird = resolve; }))
      .mockReturnValueOnce(new Promise((resolve) => { resolveRetry = resolve; }));
    mockState.refreshProjects.mockReturnValueOnce(new Promise((resolve) => { resolveRefresh = resolve; }));
    render(<LocaleProvider initialLocale="zh-CN"><TrashPage /></LocaleProvider>);
    fireEvent.click(screen.getByRole("button", { name: "清空回收站" }));
    let dialog = screen.getByRole("alertdialog");
    expect(within(dialog).queryByRole("progressbar")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "彻底删除" }));
    const progress = within(dialog).getByRole("progressbar", { name: "删除进度" });
    expect(progress.getAttribute("max")).toBe("3");
    expect(progress.getAttribute("value")).toBe("0");
    expect(within(dialog).getByText("已处理 0/3 个项目")).toBeTruthy();
    expect(mockState.permanentlyDeleteTrashedProject).toHaveBeenCalledTimes(1);

    await act(async () => resolveFirst(true));
    expect(progress.getAttribute("value")).toBe("1");
    expect(within(dialog).getByText("已处理 1/3 个项目")).toBeTruthy();
    expect(mockState.permanentlyDeleteTrashedProject).toHaveBeenCalledTimes(2);

    await act(async () => rejectSecond({ code: "project_deletion_busy" }));
    expect(progress.getAttribute("value")).toBe("2");
    expect(within(dialog).getByText("1 个删除失败，将保留在回收站。")).toBeTruthy();
    expect(mockState.permanentlyDeleteTrashedProject).toHaveBeenCalledTimes(3);

    await act(async () => resolveThird(true));
    expect(progress.getAttribute("value")).toBe("3");
    expect(within(dialog).getByText("已处理 3/3 个项目")).toBeTruthy();
    expect((within(dialog).getByRole("button", { name: "正在刷新回收站…" }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => resolveRefresh(true));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByRole("alert").textContent).toContain("该项目仍有运行中的任务");

    fireEvent.click(screen.getAllByRole("button", { name: "彻底删除" })[0]);
    dialog = screen.getByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "彻底删除" }));
    expect(within(dialog).getByRole("progressbar").getAttribute("value")).toBe("0");
    expect(within(dialog).getByRole("progressbar").getAttribute("max")).toBe("1");
    expect(within(dialog).getByText("已处理 0/1 个项目")).toBeTruthy();
    expect(within(dialog).queryByText("1 个删除失败，将保留在回收站。")).toBeNull();
    await act(async () => resolveRetry(true));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("shows Chinese confirmation copy in Chinese mode", () => {
    render(<LocaleProvider initialLocale="zh-CN"><TrashPage /></LocaleProvider>);
    fireEvent.click(screen.getByRole("button", { name: "彻底删除" }));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByRole("heading", { name: "彻底删除这个项目？" })).toBeTruthy();
    expect(within(dialog).getByText("项目、工作流及其独占媒体将被永久删除，无法恢复。")).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "取消" })).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "关闭" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });
});
