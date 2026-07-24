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
});
