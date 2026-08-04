import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectsPage } from "./ProjectsPage.tsx";

const fixture = vi.hoisted(() => ({
  listWorkflowAssets: vi.fn(),
  renameProject: vi.fn(),
}));

vi.mock("../api/v2Client.ts", () => ({
  v2Api: {
    listWorkflowAssets: fixture.listWorkflowAssets,
  },
}));

vi.mock("../AppContextValue", () => ({
  useApp: () => ({
    savedProjects: [
      {
        project_id: "project-1",
        workflow_id: "workflow-1",
        name: "Summer launch",
        is_favorite: false,
        updated_at: "2026-07-24T08:00:00Z",
        cover_asset_id: null,
      },
    ],
    startNewProject: vi.fn(),
    openProject: vi.fn(async () => true),
    moveProjectToTrash: vi.fn(async () => true),
    renameProject: fixture.renameProject,
    toggleProjectFavorite: vi.fn(async () => true),
  }),
}));

function openRenameDialog() {
  const actionsTrigger = screen.getByRole("button", { name: "Open actions for Summer launch" });
  fireEvent.click(actionsTrigger);
  const trigger = screen.getByRole("menuitem", { name: "Rename Summer launch" });
  fireEvent.click(trigger);
  return actionsTrigger;
}

describe("ProjectsPage project rename", () => {
  beforeEach(() => {
    fixture.listWorkflowAssets.mockResolvedValue({ assets: [] });
    fixture.renameProject.mockResolvedValue(true);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("opens an accessible custom dialog from an icon-only rename action", () => {
    const promptSpy = vi.spyOn(window, "prompt");
    render(<ProjectsPage navigate={vi.fn()} />);

    const actionList = document.querySelector(".project-action-list") as HTMLDivElement;
    const hiddenRename = document.querySelector(".project-rename-btn") as HTMLButtonElement;
    expect(actionList.getAttribute("aria-hidden")).toBe("true");
    expect(hiddenRename.tabIndex).toBe(-1);

    fireEvent.click(screen.getByRole("button", { name: "Open actions for Summer launch" }));
    const trigger = screen.getByRole("menuitem", { name: "Rename Summer launch" });
    expect(actionList.getAttribute("aria-hidden")).toBe("false");
    expect(trigger.tabIndex).toBe(0);

    expect(trigger.querySelector("svg")).toBeTruthy();
    expect(trigger.textContent?.trim()).toBe("");
    fireEvent.click(trigger);

    expect(promptSpy).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Rename project" })).toBeTruthy();
    expect((screen.getByRole("textbox", { name: "Project name" }) as HTMLInputElement).value).toBe("Summer launch");

    const cancel = screen.getByRole("button", { name: "Cancel rename" });
    const confirm = screen.getByRole("button", { name: "Confirm rename" });
    expect(cancel.classList.contains("project-rename-action--cancel")).toBe(true);
    expect(confirm.classList.contains("project-rename-action--confirm")).toBe(true);
    expect(cancel.querySelector("svg")).toBeTruthy();
    expect(confirm.querySelector("svg")).toBeTruthy();
    expect(cancel.textContent?.trim()).toBe("");
    expect(confirm.textContent?.trim()).toBe("");
    expect(confirm.hasAttribute("disabled")).toBe(true);

    fireEvent.click(cancel);
    expect(screen.queryByRole("dialog", { name: "Rename project" })).toBeNull();
    expect(actionList.getAttribute("aria-hidden")).toBe("true");
    expect(hiddenRename.tabIndex).toBe(-1);
  });

  it("trims and submits a changed name, then closes the dialog", async () => {
    render(<ProjectsPage navigate={vi.fn()} />);
    openRenameDialog();

    const input = screen.getByRole("textbox", { name: "Project name" });
    fireEvent.change(input, { target: { value: "  Autumn campaign  " } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() => {
      expect(fixture.renameProject).toHaveBeenCalledWith("project-1", "Autumn campaign");
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Rename project" })).toBeNull();
    });
  });

  it("supports Escape cancellation and restores focus to the project actions trigger", async () => {
    render(<ProjectsPage navigate={vi.fn()} />);
    const trigger = openRenameDialog();

    fireEvent.keyDown(screen.getByRole("textbox", { name: "Project name" }), { key: "Escape" });

    expect(screen.queryByRole("dialog", { name: "Rename project" })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(fixture.renameProject).not.toHaveBeenCalled();
  });

  it("keeps keyboard focus inside the dialog in both tab directions", () => {
    render(<ProjectsPage navigate={vi.fn()} />);
    openRenameDialog();

    const input = screen.getByRole("textbox", { name: "Project name" });
    fireEvent.change(input, { target: { value: "Autumn campaign" } });
    const confirm = screen.getByRole("button", { name: "Confirm rename" });

    confirm.focus();
    fireEvent.keyDown(confirm, { key: "Tab" });
    expect(document.activeElement).toBe(input);

    input.focus();
    fireEvent.keyDown(input, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(confirm);
  });

  it("keeps the input focused and read-only while a rename request is pending", async () => {
    let resolveRename: ((value: boolean) => void) | undefined;
    fixture.renameProject.mockReturnValueOnce(new Promise<boolean>((resolve) => {
      resolveRename = resolve;
    }));
    render(<ProjectsPage navigate={vi.fn()} />);
    openRenameDialog();

    const input = screen.getByRole("textbox", { name: "Project name" }) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Autumn campaign" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() => expect(input.readOnly).toBe(true));
    expect(document.activeElement).toBe(input);
    expect(screen.getByRole("button", { name: "Renaming project" }).hasAttribute("disabled")).toBe(true);

    resolveRename?.(true);
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Rename project" })).toBeNull();
    });
  });

  it("closes from the backdrop and restores the page scroll state", () => {
    document.body.style.overflow = "auto";
    render(<ProjectsPage navigate={vi.fn()} />);
    openRenameDialog();

    const dialog = screen.getByRole("dialog", { name: "Rename project" });
    const backdrop = dialog.parentElement as HTMLDivElement;
    expect(backdrop.parentElement).toBe(document.body);
    expect(document.body.style.overflow).toBe("hidden");

    fireEvent.pointerDown(backdrop);

    expect(screen.queryByRole("dialog", { name: "Rename project" })).toBeNull();
    expect(document.body.style.overflow).toBe("auto");
  });

  it("keeps the draft open and reports an inline error when rename fails", async () => {
    fixture.renameProject.mockRejectedValueOnce(new Error("request failed"));
    render(<ProjectsPage navigate={vi.fn()} />);
    openRenameDialog();

    const input = screen.getByRole("textbox", { name: "Project name" });
    fireEvent.change(input, { target: { value: "Campaign retry" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("dialog", { name: "Rename project" })).toBeTruthy();
    expect((input as HTMLInputElement).value).toBe("Campaign retry");
  });
});
