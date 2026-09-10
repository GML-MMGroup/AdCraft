import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ProjectV2Summary } from "../../types-v2";
import { HomeRecentProjects } from "./HomeRecentProjects";
import { HomeRecentLoading } from "../HomeRecentLoading";

const state = vi.hoisted(() => ({ projects: null as ProjectV2Summary[] | null, loading: true, error: false, refresh: vi.fn() }));
vi.mock("./useRecentProjects", () => ({ useRecentProjects: () => state }));
const callbacks = { onOpenProject: vi.fn(), onCreateProject: vi.fn(), loadingContent: <HomeRecentLoading /> };
const fixture = (id: string): ProjectV2Summary => ({ project_id: id, workflow_id: `workflow-${id}`, name: `Campaign ${id}`, updated_at: "2026-09-07T00:00:00Z", status: "active", is_favorite: false, project_version: 1, cover_asset_id: null, cover_state: "none" });
beforeEach(() => { state.projects = null; state.loading = true; state.error = false; vi.clearAllMocks(); });
afterEach(cleanup);

describe("HomeRecentProjects", () => {
  it("shows loading rather than demos or a premature empty state", () => {
    render(<HomeRecentProjects {...callbacks} />);
    expect(screen.getByRole("status").textContent).toContain("Loading recent projects");
    expect(screen.queryByText("No recent projects")).toBeNull();
    expect(screen.queryByText("New fragrance product reel")).toBeNull();
  });

  it("shows every real project including missing covers and opens exact project IDs", () => {
    state.projects = ["a", "b", "c", "d"].map(fixture); state.loading = false;
    const view = render(<HomeRecentProjects {...callbacks} />);
    for (const p of state.projects) { fireEvent.click(screen.getByRole("button", { name: `Open ${p.name}` })); expect(callbacks.onOpenProject).toHaveBeenLastCalledWith(p.project_id); }
    expect(screen.getAllByText("No cover yet")).toHaveLength(4);
    expect(view.container.querySelectorAll("time[datetime='2026-09-07T00:00:00Z']")).toHaveLength(4);
    expect(view.container.querySelectorAll(".recent-card[data-reveal-item]")).toHaveLength(4);
    expect(screen.queryByRole("button", { name: "View all" })).toBeNull();
    expect(view.container.querySelector(".home-recent-actions")).toBeNull();
  });

  it("uses image preview and video poster, never video content, and handles a broken image", async () => {
    state.projects = [fixture("a"), fixture("b")].map((p, i) => ({ ...p, cover_state: "ready", cover: { asset_id: `asset-${i}`, version_id: "v1", media_type: i ? "video" : "image", preview_url: `/preview-${i}.webp`, poster_url: `/poster-${i}.webp` } })); state.loading = false;
    const view = render(<HomeRecentProjects {...callbacks} />);
    await waitFor(() => expect(view.container.querySelector("img[src='/preview-0.webp']")).not.toBeNull());
    expect(view.container.querySelector("img[src='/poster-1.webp']")).not.toBeNull();
    expect(view.container.querySelector("video")).toBeNull();
    fireEvent.error(view.container.querySelector("img")!);
    expect(screen.getByText("Cover unavailable")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open Campaign a" }));
    expect(callbacks.onOpenProject).toHaveBeenCalledWith("a");
  });

  it("does not load broken summary covers", () => {
    state.projects = [{ ...fixture("a"), cover_state: "broken", cover: { asset_id: "a", version_id: "v", media_type: "image", preview_url: "/broken.webp", poster_url: null } }]; state.loading = false;
    const view = render(<HomeRecentProjects {...callbacks} />);
    expect(view.container.querySelector("img")).toBeNull();
  });

  it("shows empty only after success and supports creating a project", () => {
    state.projects = []; state.loading = false;
    render(<HomeRecentProjects {...callbacks} />);
    expect(screen.getByText("No recent projects")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Create project" }));
    expect(callbacks.onCreateProject).toHaveBeenCalledOnce();
  });

  it("keeps cached cards on refresh failure and disables repeat retry while loading", () => {
    state.projects = [fixture("a")]; state.error = true; state.loading = false;
    const view = render(<HomeRecentProjects {...callbacks} />);
    expect(screen.getByRole("alert").textContent).toContain("could not be refreshed");
    expect(screen.getByText("Campaign a")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(state.refresh).toHaveBeenCalledOnce();
    state.loading = true; view.rerender(<HomeRecentProjects {...callbacks} />);
    expect(screen.getByRole("button", { name: "Retry" }).hasAttribute("disabled")).toBe(true);
  });

  it("shows an initial error without fake or empty projects", () => {
    state.error = true; state.loading = false;
    render(<HomeRecentProjects {...callbacks} />);
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.queryByText("No recent projects")).toBeNull();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });
});
