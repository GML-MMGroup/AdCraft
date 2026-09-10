import type { ProjectV2ListResponse, ProjectV2Summary } from "../types-v2.ts";
import { resolveV2ProjectCoverSummary, type V2ProjectCover } from "./v2ProjectCover.ts";

export type V2ProjectListItem = {
  key: string;
  source: "saved";
  projectId: string;
  name: string;
  updatedAt: string;
  favorite: boolean;
  coverAssetId: string | null;
  coverVersionId?: string | null;
  coverState?: ProjectV2Summary["cover_state"];
  cover: V2ProjectCover | null;
};

export function projectSummaryToListItem(project: ProjectV2Summary): V2ProjectListItem {
  return {
    key: project.project_id,
    source: "saved",
    projectId: project.project_id,
    name: project.name,
    updatedAt: project.updated_at,
    favorite: project.is_favorite,
    coverAssetId: project.cover_asset_id,
    coverVersionId: project.cover_version_id,
    coverState: project.cover_state,
    cover: resolveV2ProjectCoverSummary(project.cover),
  };
}

export async function loadAllBackendProjectPages(
  loadPage: (cursor?: string | null) => Promise<ProjectV2ListResponse>,
): Promise<ProjectV2Summary[]> {
  const projects: ProjectV2Summary[] = [];
  const projectIds = new Set<string>();
  const cursors = new Set<string>();
  let cursor: string | null | undefined;

  do {
    const page = await loadPage(cursor);
    for (const project of page.items) {
      if (projectIds.has(project.project_id)) continue;
      projectIds.add(project.project_id);
      projects.push(project);
    }
    cursor = page.next_cursor;
    if (cursor && cursors.has(cursor)) {
      throw new Error("Project pagination returned a repeated cursor.");
    }
    if (cursor) cursors.add(cursor);
  } while (cursor);

  return projects;
}

type ProjectCatalogPageWithEtag = {
  value: ProjectV2ListResponse | null;
  etag: string | null;
  notModified: boolean;
};

type CachedProjectCatalog = {
  projects: ProjectV2Summary[];
  etag: string | null;
};

export async function loadAllBackendProjectPagesWithEtag(
  loadPage: (
    cursor?: string | null,
    ifNoneMatch?: string | null,
  ) => Promise<ProjectCatalogPageWithEtag>,
  cached?: CachedProjectCatalog,
): Promise<CachedProjectCatalog & { notModified: boolean }> {
  const first = await loadPage(undefined, cached?.etag);
  if (first.notModified) {
    if (!cached) throw new Error("Project catalog returned 304 without a cached catalog.");
    return { ...cached, notModified: true };
  }
  if (!first.value) throw new Error("Project catalog response is missing its page.");

  const projects: ProjectV2Summary[] = [];
  const projectIds = new Set<string>();
  const cursors = new Set<string>();
  let page = first.value;
  let cursor = page.next_cursor;
  const completeInFirstPage = cursor === null;

  for (;;) {
    for (const project of page.items) {
      if (projectIds.has(project.project_id)) continue;
      projectIds.add(project.project_id);
      projects.push(project);
    }
    if (!cursor) break;
    if (cursors.has(cursor)) throw new Error("Project pagination returned a repeated cursor.");
    cursors.add(cursor);
    const next = await loadPage(cursor);
    if (next.notModified || !next.value) {
      throw new Error("A paginated project catalog returned an invalid conditional response.");
    }
    page = next.value;
    cursor = page.next_cursor;
  }

  return {
    projects,
    etag: completeInFirstPage ? first.etag : null,
    notModified: false,
  };
}

export function shouldPersistWorkflowAsLocalDraft(workflow: { project_id?: string | null }): boolean {
  return !workflow.project_id;
}

export function shouldPersistMessagesAsLocalDraft(workflow: { project_id?: string | null } | null): boolean {
  return !workflow?.project_id;
}

export function projectTrashClearsActiveWorkflow(projectId: string, activeProjectId: string | null): boolean {
  return projectId === activeProjectId;
}
