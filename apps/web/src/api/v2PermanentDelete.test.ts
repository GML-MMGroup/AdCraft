import { afterEach, describe, expect, it, vi } from "vitest";
import { v2Api, v2AuthoringPreconditionTarget } from "./v2Client.ts";

afterEach(() => vi.unstubAllGlobals());

describe("permanent project deletion", () => {
  it("uses the confirmed project version and the separate permanent endpoint", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await v2Api.permanentlyDeleteProject("project-delete", 7);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/projects/project-delete/permanent");
    expect(options.method).toBe("DELETE");
    expect(new Headers(options.headers).get("If-Match")).toBe('"project:project-delete:7"');
    expect(v2AuthoringPreconditionTarget("/projects/project-delete/permanent", "DELETE")).toEqual({ resource: "project", id: "project-delete" });
  });

  it("does not resubmit a destructive action after a version conflict", async () => {
    const fetchMock = vi.fn(async (_url: string, options?: RequestInit) => options?.method === "DELETE"
      ? new Response(JSON.stringify({ detail: { code: "project_state_conflict", message: "Changed" } }), { status: 412 })
      : new Response(JSON.stringify({ project_id: "project-delete" }), { status: 200, headers: { ETag: '"project:project-delete:8"' } }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(v2Api.permanentlyDeleteProject("project-delete", 7)).rejects.toMatchObject({ code: "project_state_conflict" });
    expect(fetchMock.mock.calls.filter(([, options]) => options?.method === "DELETE")).toHaveLength(1);
  });
});
