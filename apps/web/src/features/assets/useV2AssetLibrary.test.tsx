import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { assetLibraryQueryResource, useV2AssetLibrary } from "./useV2AssetLibrary.ts";

const fixture = vi.hoisted(() => ({
  listAssetLibraryEntities: vi.fn(),
}));

vi.mock("../../api/v2Client.ts", () => ({
  v2Api: fixture,
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

function entity(entityId: string) {
  return {
    entity_id: entityId,
    scope: "my" as const,
    entity_type: "character",
    library_category: "characters" as const,
    display_name: entityId,
    description: "",
    tags: [],
    is_favorite: false,
    status: "active" as const,
    preview_member: null,
    preview_url: null,
    member_count: 1,
  };
}

describe("useV2AssetLibrary", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    fixture.listAssetLibraryEntities.mockReset();
    assetLibraryQueryResource.invalidate();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("debounces searches, aborts the obsolete request, and ignores late results", async () => {
    const stale = deferred<{ entities: ReturnType<typeof entity>[]; next_cursor: string | null }>();
    const fresh = deferred<{ entities: ReturnType<typeof entity>[]; next_cursor: string | null }>();
    fixture.listAssetLibraryEntities
      .mockReturnValueOnce(stale.promise)
      .mockReturnValueOnce(fresh.promise);
    const { result, rerender } = renderHook(
      ({ search }) => useV2AssetLibrary({ scope: "my", category: "characters", search }),
      { initialProps: { search: "" } },
    );

    expect(fixture.listAssetLibraryEntities).toHaveBeenCalledTimes(1);
    rerender({ search: "portrait" });
    act(() => { vi.advanceTimersByTime(249); });
    expect(fixture.listAssetLibraryEntities).toHaveBeenCalledTimes(1);

    act(() => { vi.advanceTimersByTime(1); });
    expect(fixture.listAssetLibraryEntities).toHaveBeenLastCalledWith(
      { scope: "my", category: "characters", search: "portrait", cursor: null, limit: 40 },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(fixture.listAssetLibraryEntities.mock.calls[0]?.[1]?.signal.aborted).toBe(true);

    await act(async () => { fresh.resolve({ entities: [entity("fresh")], next_cursor: null }); });
    expect(result.current.entities.map((item) => item.entity_id)).toEqual(["fresh"]);
    await act(async () => { stale.resolve({ entities: [entity("stale")], next_cursor: null }); });
    expect(result.current.entities.map((item) => item.entity_id)).toEqual(["fresh"]);
  });

  it("keeps pagination scoped to the active category and scope", async () => {
    fixture.listAssetLibraryEntities
      .mockResolvedValueOnce({ entities: [entity("first")], next_cursor: "next-page" })
      .mockResolvedValueOnce({ entities: [entity("second")], next_cursor: null })
      .mockResolvedValueOnce({ entities: [entity("recommended-scene")], next_cursor: null });
    const { result, rerender } = renderHook(
      ({ scope, category }) => useV2AssetLibrary({ scope, category, search: "" }),
      { initialProps: { scope: "my" as const, category: "characters" as const } },
    );

    await act(async () => {});
    expect(result.current.entities.map((item) => item.entity_id)).toEqual(["first"]);
    await act(async () => { await result.current.loadMore(); });
    expect(fixture.listAssetLibraryEntities).toHaveBeenLastCalledWith(
      { scope: "my", category: "characters", search: "", cursor: "next-page", limit: 40 },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(result.current.entities.map((item) => item.entity_id)).toEqual(["first", "second"]);

    rerender({ scope: "recommended", category: "scenes" });
    await act(async () => {});
    expect(fixture.listAssetLibraryEntities).toHaveBeenLastCalledWith(
      { scope: "recommended", category: "scenes", search: "", cursor: null, limit: 40 },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(result.current.entities.map((item) => item.entity_id)).toEqual(["recommended-scene"]);
  });

  it("keeps a deduplicated query alive when one hook unmounts", async () => {
    const pending = deferred<{ entities: ReturnType<typeof entity>[]; next_cursor: string | null }>();
    fixture.listAssetLibraryEntities.mockReturnValue(pending.promise);
    const first = renderHook(() => useV2AssetLibrary({ scope: "my", category: "characters", search: "" }));
    const second = renderHook(() => useV2AssetLibrary({ scope: "my", category: "characters", search: "" }));

    expect(fixture.listAssetLibraryEntities).toHaveBeenCalledTimes(1);
    const signal = fixture.listAssetLibraryEntities.mock.calls[0]?.[1]?.signal as AbortSignal;
    first.unmount();
    expect(signal.aborted).toBe(false);

    await act(async () => { pending.resolve({ entities: [entity("survivor")], next_cursor: null }); });
    expect(second.result.current.entities.map((item) => item.entity_id)).toEqual(["survivor"]);
  });

  it("aborts a deduplicated query only after its final hook unmounts", () => {
    const pending = deferred<{ entities: ReturnType<typeof entity>[]; next_cursor: string | null }>();
    fixture.listAssetLibraryEntities.mockReturnValue(pending.promise);
    const first = renderHook(() => useV2AssetLibrary({ scope: "my", category: "characters", search: "" }));
    const second = renderHook(() => useV2AssetLibrary({ scope: "my", category: "characters", search: "" }));

    const signal = fixture.listAssetLibraryEntities.mock.calls[0]?.[1]?.signal as AbortSignal;
    first.unmount();
    expect(signal.aborted).toBe(false);
    second.unmount();
    expect(signal.aborted).toBe(true);
  });

  it("keeps a refreshed result fresh across unmount and remount", async () => {
    fixture.listAssetLibraryEntities
      .mockResolvedValueOnce({ entities: [entity("before-upload")], next_cursor: null })
      .mockResolvedValueOnce({ entities: [entity("after-upload")], next_cursor: null });
    const first = renderHook(() => useV2AssetLibrary({ scope: "my", category: "characters", search: "" }));

    await act(async () => {});
    expect(first.result.current.entities.map((item) => item.entity_id)).toEqual(["before-upload"]);
    await act(async () => { first.result.current.refresh(); });
    expect(first.result.current.entities.map((item) => item.entity_id)).toEqual(["after-upload"]);
    first.unmount();

    const second = renderHook(() => useV2AssetLibrary({ scope: "my", category: "characters", search: "" }));
    await act(async () => {});

    expect(fixture.listAssetLibraryEntities).toHaveBeenCalledTimes(2);
    expect(second.result.current.entities.map((item) => item.entity_id)).toEqual(["after-upload"]);
  });

  it("runs duplicate loadMore calls from one render as one operation", async () => {
    const nextPage = deferred<{ entities: ReturnType<typeof entity>[]; next_cursor: string | null }>();
    fixture.listAssetLibraryEntities
      .mockResolvedValueOnce({ entities: [entity("first")], next_cursor: "next-page" })
      .mockReturnValueOnce(nextPage.promise);
    const view = renderHook(() => useV2AssetLibrary({ scope: "my", category: "characters", search: "" }));

    await act(async () => {});
    let firstLoad!: Promise<void>;
    let duplicateLoad!: Promise<void>;
    await act(async () => {
      firstLoad = view.result.current.loadMore();
      duplicateLoad = view.result.current.loadMore();
    });

    expect(firstLoad).toBe(duplicateLoad);
    expect(fixture.listAssetLibraryEntities).toHaveBeenCalledTimes(2);
    await act(async () => {
      nextPage.resolve({ entities: [entity("second")], next_cursor: null });
      await Promise.all([firstLoad, duplicateLoad]);
    });
    expect(view.result.current.entities.map((item) => item.entity_id)).toEqual(["first", "second"]);
  });

  it("does not join pre-refresh pagination still owned by another hook", async () => {
    const stalePage = deferred<{ entities: ReturnType<typeof entity>[]; next_cursor: string | null }>();
    const freshPage = deferred<{ entities: ReturnType<typeof entity>[]; next_cursor: string | null }>();
    fixture.listAssetLibraryEntities
      .mockResolvedValueOnce({ entities: [entity("before-upload")], next_cursor: "next-page" })
      .mockReturnValueOnce(stalePage.promise)
      .mockResolvedValueOnce({ entities: [entity("after-upload")], next_cursor: "next-page" })
      .mockReturnValueOnce(freshPage.promise);
    const first = renderHook(() => useV2AssetLibrary({ scope: "my", category: "characters", search: "" }));
    const second = renderHook(() => useV2AssetLibrary({ scope: "my", category: "characters", search: "" }));

    await act(async () => {});
    void first.result.current.loadMore();
    void second.result.current.loadMore();
    expect(fixture.listAssetLibraryEntities).toHaveBeenCalledTimes(2);

    await act(async () => { first.result.current.refresh(); });
    expect(first.result.current.entities.map((item) => item.entity_id)).toEqual(["after-upload"]);
    void first.result.current.loadMore();

    expect(fixture.listAssetLibraryEntities).toHaveBeenCalledTimes(4);
    await act(async () => {
      stalePage.resolve({ entities: [entity("stale-page")], next_cursor: null });
      freshPage.resolve({ entities: [entity("fresh-page")], next_cursor: null });
    });
    expect(first.result.current.entities.map((item) => item.entity_id)).toEqual(["after-upload", "fresh-page"]);
    expect(second.result.current.entities.map((item) => item.entity_id)).toEqual(["before-upload", "stale-page"]);
  });

  it("aborts pagination after duplicate calls unmount and does not retain its one-shot cache entry", async () => {
    const nextPage = deferred<{ entities: ReturnType<typeof entity>[]; next_cursor: string | null }>();
    fixture.listAssetLibraryEntities
      .mockResolvedValueOnce({ entities: [entity("first")], next_cursor: "next-page" })
      .mockReturnValueOnce(nextPage.promise)
      .mockResolvedValueOnce({ entities: [entity("second")], next_cursor: "next-page" })
      .mockResolvedValueOnce({ entities: [entity("third")], next_cursor: null });
    const first = renderHook(() => useV2AssetLibrary({ scope: "my", category: "characters", search: "" }));

    await act(async () => {});
    void first.result.current.loadMore();
    void first.result.current.loadMore();
    const signal = fixture.listAssetLibraryEntities.mock.calls[1]?.[1]?.signal as AbortSignal;
    first.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => { nextPage.resolve({ entities: [entity("late")], next_cursor: null }); });

    const second = renderHook(() => useV2AssetLibrary({ scope: "my", category: "characters", search: "" }));
    await act(async () => {});
    await act(async () => { await second.result.current.loadMore(); });
    await act(async () => { await second.result.current.loadMore(); });
    expect(fixture.listAssetLibraryEntities).toHaveBeenCalledTimes(4);
  });
});
