import type { ProjectV2ListResponse, ProjectV2Summary } from "../../types-v2";
import { loadProjectCatalogCache } from "../../projects/projectCatalogCache";

type LoadPage = (status: "active", limit: number, cursor?: string, etag?: string | null) => Promise<{
  value: ProjectV2ListResponse | null;
  etag: string | null;
  notModified: boolean;
}>;

export function createRecentProjectsCache(
  loadPage: LoadPage,
  loadSeed = loadProjectCatalogCache,
  now = Date.now,
) {
  let response: { items: ProjectV2Summary[]; etag: string | null; savedAt: number } | null = null;
  let inFlight: Promise<ProjectV2Summary[]> | null = null;

  return {
    peek(): ProjectV2Summary[] | null {
      const seed = loadSeed();
      if (seed && seed.activeSavedAt > (response?.savedAt ?? 0)) {
        return seed.active.filter((p) => p.status === "active").sort((a, b) =>
          Date.parse(b.updated_at) - Date.parse(a.updated_at)
          || (a.project_id < b.project_id ? -1 : a.project_id > b.project_id ? 1 : 0),
        ).slice(0, 4);
      }
      return response?.items ?? null;
    },
    load(force = false): Promise<ProjectV2Summary[]> {
      if (inFlight) return inFlight;
      const seedUpdatedAt = loadSeed()?.activeSavedAt ?? 0;
      if (!force && response && now() - response.savedAt < 10_000 && seedUpdatedAt <= response.savedAt) {
        return Promise.resolve(response.items);
      }
      // An ETag is valid only for the response body from this exact four-item query.
      inFlight = loadPage("active", 4, undefined, response?.etag).then((result) => {
        if (result.notModified) {
          if (!response) throw new Error("Recent projects returned 304 without a cached response.");
          response = { ...response, etag: result.etag ?? response.etag, savedAt: now() };
        } else {
          if (!result.value) throw new Error("Recent projects response is missing its page.");
          response = { items: result.value.items.slice(0, 4), etag: result.etag, savedAt: now() };
        }
        return response.items;
      }).finally(() => { inFlight = null; });
      return inFlight;
    },
  };
}
