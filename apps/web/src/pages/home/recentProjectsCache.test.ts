import { describe, expect, it, vi } from "vitest";
import type { ProjectV2Summary } from "../../types-v2";
import { createRecentProjectsCache } from "./recentProjectsCache";

export function project(id: string, updatedAt = "2026-09-07T00:00:00Z"): ProjectV2Summary {
  return { project_id: id, workflow_id: `workflow-${id}`, name: `Project ${id}`, status: "active", is_favorite: false, cover_asset_id: null, cover_state: "none", project_version: 1, updated_at: updatedAt };
}

describe("recent project query cache", () => {
  it("requests only four summaries, never follows the next cursor and reuses the exact query ETag", async () => {
    let now = 100_000;
    const items = [project("a")];
    const load = vi.fn().mockResolvedValueOnce({ value: { items, next_cursor: "page-2" }, etag: '"recent"', notModified: false })
      .mockResolvedValueOnce({ value: null, etag: '"recent"', notModified: true });
    const cache = createRecentProjectsCache(load, () => null, () => now);
    expect(await cache.load()).toEqual(items);
    expect(load).toHaveBeenCalledExactlyOnceWith("active", 4, undefined, undefined);
    await cache.load();
    expect(load).toHaveBeenCalledTimes(1);
    now += 10_001;
    expect(await cache.load()).toEqual(items);
    expect(load).toHaveBeenLastCalledWith("active", 4, undefined, '"recent"');
  });

  it("deduplicates concurrent requests including forced retry", async () => {
    let resolve!: (value: unknown) => void;
    const load = vi.fn().mockReturnValue(new Promise((done) => { resolve = done; }));
    const cache = createRecentProjectsCache(load);
    const first = cache.load();
    const second = cache.load(true);
    resolve({ value: { items: [], next_cursor: null }, etag: null, notModified: false });
    expect(await first).toEqual([]);
    expect(await second).toEqual([]);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("seeds sorted active projects without borrowing the full-list ETag or mutating that cache", async () => {
    const active = [project("a"), project("b"), project("c"), project("d"), project("e")];
    const seed = { active, trashed: [], activeEtag: '"all"', trashedEtag: null, activeSavedAt: 100, trashedSavedAt: 0 };
    const load = vi.fn().mockResolvedValue({ value: { items: [project("fresh")], next_cursor: "more" }, etag: '"recent"', notModified: false });
    const cache = createRecentProjectsCache(load, () => seed);
    expect(cache.peek()?.map((p) => p.project_id)).toEqual(["a", "b", "c", "d"]);
    await cache.load();
    expect(load).toHaveBeenCalledExactlyOnceWith("active", 4, undefined, undefined);
    expect(seed.active).toBe(active);
    expect(active.map((p) => p.project_id)).toEqual(["a", "b", "c", "d", "e"]);
    expect(seed.activeEtag).toBe('"all"');
  });

  it("preserves successful results after failure and permits an explicit retry", async () => {
    const items = [project("a")];
    const load = vi.fn().mockResolvedValueOnce({ value: { items, next_cursor: null }, etag: '"one"', notModified: false })
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ value: { items: [], next_cursor: null }, etag: '"empty"', notModified: false });
    const cache = createRecentProjectsCache(load);
    await cache.load();
    await expect(cache.load(true)).rejects.toThrow("offline");
    expect(cache.peek()).toEqual(items);
    expect(await cache.load(true)).toEqual([]);
  });

  it("rejects 304 without the matching query body, even when a catalog seed exists", async () => {
    const load = vi.fn().mockResolvedValue({ value: null, etag: '"other"', notModified: true });
    const cache = createRecentProjectsCache(load);
    await expect(cache.load()).rejects.toThrow(/304/);
    expect(cache.peek()).toBeNull();
  });

  it("revalidates within freshness when another page updated the project catalog", async () => {
    let savedAt = 0;
    const load = vi.fn().mockResolvedValue({ value: { items: [project("a")], next_cursor: null }, etag: null, notModified: false });
    const cache = createRecentProjectsCache(load, () => ({ active: [], trashed: [], activeEtag: null, trashedEtag: null, activeSavedAt: savedAt, trashedSavedAt: 0 }), () => 100);
    await cache.load();
    savedAt = 101;
    expect(cache.peek()).toEqual([]);
    await cache.load();
    expect(load).toHaveBeenCalledTimes(2);
  });
});
