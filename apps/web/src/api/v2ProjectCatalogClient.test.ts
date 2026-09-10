import { afterEach, describe, expect, it, vi } from "vitest";

import { v2Api } from "./v2Client.ts";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("V2 project catalog conditional reads", () => {
  it("sends If-None-Match and exposes a 304 without parsing a payload", async () => {
    const fetchMock = vi.fn(async () => new Response(null, {
      status: 304,
      headers: { ETag: '"active-v1"' },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await (v2Api as typeof v2Api & {
      listProjectsWithEtag: (
        status: string,
        limit: number,
        cursor: string | undefined,
        etag: string,
      ) => Promise<{ value: unknown; etag: string | null; notModified: boolean }>;
    }).listProjectsWithEtag("active", 100, undefined, '"active-v1"');

    const request = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(request.headers).get("If-None-Match")).toBe('"active-v1"');
    expect(result).toEqual({ value: null, etag: '"active-v1"', notModified: true });
  });

  it("normalizes a changed catalog and exposes its response ETag", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      items: [{
        project_id: "project-1",
        workflow_id: "workflow-1",
        name: "Campaign",
        status: "active",
        is_favorite: false,
        cover_asset_id: null,
        cover_version_id: null,
        cover_state: "none",
        cover_source: null,
        cover_updated_at: null,
        cover: null,
        project_version: 1,
        updated_at: "2026-09-03T00:00:00Z",
      }],
      next_cursor: null,
    }), {
      status: 200,
      headers: { "Content-Type": "application/json", ETag: '"active-v2"' },
    })));

    const result = await (v2Api as typeof v2Api & {
      listProjectsWithEtag: (
        status: string,
        limit: number,
      ) => Promise<{ value: { items: Array<{ project_id: string }> }; etag: string | null; notModified: boolean }>;
    }).listProjectsWithEtag("active", 100);

    expect(result.value?.items[0]?.project_id).toBe("project-1");
    expect(result.etag).toBe('"active-v2"');
    expect(result.notModified).toBe(false);
  });
});
