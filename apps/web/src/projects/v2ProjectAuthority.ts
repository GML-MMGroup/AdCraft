import type { ProjectV2Summary } from "../types-v2.ts";

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

export function shouldPersistWorkflowAsLocalDraft(workflow: { project_id?: string | null }): boolean {
  return !workflow.project_id;
}

export function projectTrashClearsActiveWorkflow(projectId: string, activeProjectId: string | null): boolean {
  return projectId === activeProjectId;
}
