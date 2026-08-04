import type { ProjectV2ListResponse, ProjectV2Summary } from "../types-v2.ts";

export type V2ProjectListItem = {
  key: string;
  source: "saved";
  projectId: string;
  name: string;
  updatedAt: string;
  favorite: boolean;
  coverAssetId: string | null;
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

export function shouldPersistWorkflowAsLocalDraft(workflow: { project_id?: string | null }): boolean {
  return !workflow.project_id;
}

export function shouldPersistMessagesAsLocalDraft(workflow: { project_id?: string | null } | null): boolean {
  return !workflow?.project_id;
}

export function projectTrashClearsActiveWorkflow(projectId: string, activeProjectId: string | null): boolean {
  return projectId === activeProjectId;
}
