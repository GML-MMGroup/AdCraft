import { StrictMode } from "react";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const loadPage = vi.hoisted(() => vi.fn());
vi.mock("../../api/v2Client", () => ({ v2Api: { listProjectsWithEtag: loadPage } }));
beforeEach(() => { vi.resetModules(); loadPage.mockReset(); window.localStorage.clear(); });
afterEach(cleanup);

describe("useRecentProjects", () => {
  it("deduplicates StrictMode mount requests and settles loading", async () => {
    let resolve!: (value: unknown) => void;
    loadPage.mockReturnValue(new Promise((done) => { resolve = done; }));
    const { useRecentProjects } = await import("./useRecentProjects");
    const view = renderHook(useRecentProjects, { wrapper: StrictMode });
    expect(view.result.current.projects).toBeNull();
    expect(view.result.current.loading).toBe(true);
    await act(async () => resolve({ value: { items: [], next_cursor: null }, etag: null, notModified: false }));
    expect(loadPage).toHaveBeenCalledTimes(1);
    expect(view.result.current.projects).toEqual([]);
    expect(view.result.current.loading).toBe(false);
  });

  it("recovers from request failure on explicit retry", async () => {
    loadPage.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({ value: { items: [], next_cursor: null }, etag: null, notModified: false });
    const { useRecentProjects } = await import("./useRecentProjects");
    const view = renderHook(useRecentProjects);
    await waitFor(() => expect(view.result.current.error).toBe(true));
    expect(view.result.current.projects).toBeNull();
    act(() => view.result.current.refresh());
    await waitFor(() => expect(view.result.current.error).toBe(false));
    expect(view.result.current.projects).toEqual([]);
    expect(loadPage).toHaveBeenCalledTimes(2);
  });

  it("ignores a completion after unmount while leaving it reusable by the next mount", async () => {
    let resolve!: (value: unknown) => void;
    loadPage.mockReturnValue(new Promise((done) => { resolve = done; }));
    const { useRecentProjects } = await import("./useRecentProjects");
    const view = renderHook(useRecentProjects);
    view.unmount();
    await act(async () => resolve({ value: { items: [], next_cursor: null }, etag: null, notModified: false }));
    expect(view.result.current.projects).toBeNull();
    const next = renderHook(useRecentProjects);
    await waitFor(() => expect(next.result.current.loading).toBe(false));
    expect(next.result.current.projects).toEqual([]);
    expect(loadPage).toHaveBeenCalledTimes(1);
  });
});
