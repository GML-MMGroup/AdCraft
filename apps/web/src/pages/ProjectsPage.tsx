import { CatalogToolbar, CatalogFilterButton, CatalogSearch } from "../components/CatalogToolbar";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CreateCard } from "../components/Cards";
import { PageHeader } from "../components/Layout";
import { useApp } from "../AppContextValue";
import type { AppNavigate } from "../types";
import { ProjectList } from "./projects/ProjectList";
import type { ProjectListItem } from "./projects/ProjectList";
import { ProjectRenameDialog } from "./projects/ProjectRenameDialog";
import { ProjectCoverDialog } from "./projects/ProjectCoverDialog";
import { ProjectCatalogNotice } from "./projects/ProjectCatalogNotice";
import { resolveV2ProjectCoverSummary } from "../projects/v2ProjectCover.ts";
import "./projects.css";
import { v2Api, V2ApiError } from "../api/v2Client.ts";

export function ProjectsPage({ navigate }: { navigate: AppNavigate }) {
  const [tab, setTab] = useState<"all" | "favorite">("all");
  const [search, setSearch] = useState("");
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedProjectIds, setSelectedProjectIds] = useState<Set<string>>(() => new Set());
  const [selectionNotice, setSelectionNotice] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [actionToastExiting, setActionToastExiting] = useState(false);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [batchAction, setBatchAction] = useState<"favorite" | "trash" | null>(null);
  const [renameTarget, setRenameTarget] = useState<ProjectListItem | null>(null);
  const [coverTarget, setCoverTarget] = useState<ProjectListItem | null>(null);
  const renameTriggerRef = useRef<HTMLButtonElement | null>(null);
  const {
    savedProjects,
    moveProjectToTrash,
    renameProject,
    toggleProjectFavorite,
    projectCatalogError,
    projectCatalogRefreshing,
    refreshProjects,
  } = useApp();
  const createProject = useCallback(() => {
    navigate("projects/new");
  }, [navigate]);

  const updateProjectCover = useCallback(async (projectId: string, selection: { assetId: string; versionId: string } | null) => {
    try {
      await v2Api.updateProject(projectId, {
        cover_asset_id: selection?.assetId ?? null,
        cover_version_id: selection?.versionId ?? null,
      });
      await refreshProjects();
    } catch (error) {
      if (error instanceof V2ApiError && [409, 412, 428].includes(error.status)) {
        await v2Api.projectWithEtag(projectId).catch(() => undefined);
        await refreshProjects();
        throw new Error("This project changed elsewhere. Review the latest cover and try again.");
      }
      throw error;
    }
  }, [refreshProjects]);

  const projects = useMemo(() => {
    return savedProjects.map((project) => ({
      key: project.project_id,
      source: "saved" as const,
      projectId: project.project_id,
      name: project.name,
      time: formatSavedProjectTime(project.updated_at),
      updatedAt: project.updated_at,
      favorite: project.is_favorite,
      mode: project.mode,
      workflowId: project.workflow_id,
      coverAssetId: project.cover_asset_id,
      coverVersionId: project.cover_version_id,
      coverState: project.cover_state,
      cover: resolveV2ProjectCoverSummary(project.cover),
    })).filter((project) => {
      const visibleByTab = tab === "all" || project.favorite;
      const visibleBySearch = project.name.toLowerCase().includes(search.toLowerCase());
      return visibleByTab && visibleBySearch;
    });
  }, [savedProjects, tab, search]);

  const selectedProjects = useMemo(
    () => projects.filter((project) => selectedProjectIds.has(project.projectId)),
    [projects, selectedProjectIds],
  );
  const allVisibleSelected = projects.length > 0 && projects.every((project) => selectedProjectIds.has(project.projectId));
  const partiallySelected = selectedProjects.length > 0 && !allVisibleSelected;
  const selectionBusy = batchAction !== null;
  const favoriteActionLabel = selectedProjects.length > 0 && selectedProjects.every((project) => project.favorite)
    ? "Remove favorite"
    : "Favorite";

  useEffect(() => {
    if (!selectionNotice) return undefined;
    const timeout = window.setTimeout(() => setSelectionNotice(null), 2800);
    return () => window.clearTimeout(timeout);
  }, [selectionNotice]);

  useEffect(() => {
    if (!actionNotice) return undefined;
    setActionToastExiting(false);
    const exitTimeout = window.setTimeout(() => setActionToastExiting(true), 2500);
    const removeTimeout = window.setTimeout(() => setActionNotice(null), 2800);
    return () => {
      window.clearTimeout(exitTimeout);
      window.clearTimeout(removeTimeout);
    };
  }, [actionNotice]);

  const openSavedProject = useCallback((projectId: string) => {
    navigate("workflow", { projectId });
  }, [navigate]);

  const trashSavedProject = useCallback(async (project: ProjectListItem) => {
    try {
      await moveProjectToTrash(project.projectId);
      setActionNotice(`${project.name} moved to trash.`);
    } catch {
      setActionNotice(`Could not move ${project.name} to trash.`);
    }
  }, [moveProjectToTrash]);

  const toggleSavedProjectFavorite = useCallback((project: ProjectListItem) => {
    const summary = savedProjects.find((item) => item.project_id === project.projectId);
    if (summary) void toggleProjectFavorite(summary);
  }, [savedProjects, toggleProjectFavorite]);

  const openRenameDialog = useCallback((project: ProjectListItem, trigger: HTMLButtonElement) => {
    renameTriggerRef.current = trigger;
    setRenameTarget(project);
  }, []);

  const closeRenameDialog = useCallback(() => {
    setRenameTarget(null);
    renameTriggerRef.current?.focus();
  }, []);

  const clearSelectionForListChange = useCallback(() => {
    if (selectedProjectIds.size > 0) setSelectionNotice("Selection cleared because the project list changed.");
    setSelectedProjectIds(new Set());
  }, [selectedProjectIds.size]);

  const changeTab = useCallback((nextTab: "all" | "favorite") => {
    if (nextTab === tab) return;
    clearSelectionForListChange();
    setTab(nextTab);
  }, [clearSelectionForListChange, tab]);

  const changeSearch = useCallback((value: string) => {
    if (value !== search) clearSelectionForListChange();
    setSearch(value);
  }, [clearSelectionForListChange, search]);

  const enterSelectionMode = useCallback(() => {
    setSelectionMode(true);
    setSelectedProjectIds(new Set());
    setSelectionError(null);
    setSelectionNotice(null);
  }, []);

  const exitSelectionMode = useCallback(() => {
    if (selectionBusy) return;
    setSelectionMode(false);
    setSelectedProjectIds(new Set());
    setSelectionError(null);
    setSelectionNotice(null);
  }, [selectionBusy]);

  const toggleProjectSelection = useCallback((projectId: string) => {
    if (selectionBusy) return;
    setSelectedProjectIds((current) => {
      const next = new Set(current);
      if (next.has(projectId)) next.delete(projectId);
      else next.add(projectId);
      return next;
    });
  }, [selectionBusy]);

  const toggleVisibleSelection = useCallback(() => {
    if (selectionBusy) return;
    setSelectedProjectIds(allVisibleSelected
      ? new Set()
      : new Set(projects.map((project) => project.projectId)));
  }, [allVisibleSelected, projects, selectionBusy]);

  const runBatchAction = useCallback(async (action: "favorite" | "trash") => {
    if (selectionBusy || selectedProjects.length === 0) return;
    if (action === "trash") {
      const confirmed = window.confirm(`Move ${selectedProjects.length} ${selectedProjects.length === 1 ? "project" : "projects"} to trash?`);
      if (!confirmed) return;
    }

    const snapshot = [...selectedProjects];
    setBatchAction(action);
    setSelectionError(null);
    setSelectionNotice(null);
    const results = await Promise.allSettled(snapshot.map(async (project) => {
      if (action === "trash") return moveProjectToTrash(project.projectId);
      const summary = savedProjects.find((item) => item.project_id === project.projectId);
      if (!summary) throw new Error(`Project ${project.projectId} is no longer available.`);
      return toggleProjectFavorite(summary);
    }));
    const failedProjectIds = new Set(
      snapshot
        .filter((_, index) => results[index]?.status === "rejected")
        .map((project) => project.projectId),
    );

    setBatchAction(null);
    if (failedProjectIds.size > 0) {
      const noun = action === "trash" ? "moved to trash" : "updated";
      setSelectionError(`${failedProjectIds.size} ${failedProjectIds.size === 1 ? "project could not be" : "projects could not be"} ${noun}.`);
      setSelectedProjectIds(failedProjectIds);
      return;
    }

    setSelectedProjectIds(new Set());
    setSelectionMode(false);
    if (action === "trash") {
      setActionNotice(`${snapshot.length} ${snapshot.length === 1 ? "project" : "projects"} moved to trash.`);
    }
  }, [moveProjectToTrash, savedProjects, selectedProjects, selectionBusy, toggleProjectFavorite]);

  return (
    <section className="content-wrap">
      <PageHeader title="All Projects" editorial />
      <CatalogToolbar className="projects-toolbar">
        <div className="toolbar-row">
          <CatalogFilterButton active={tab === "all"} onClick={() => changeTab("all")}>
            All
          </CatalogFilterButton>
          <CatalogFilterButton active={tab === "favorite"} onClick={() => changeTab("favorite")}>
            Favorites
          </CatalogFilterButton>
        </div>
        <div className="catalog-toolbar-actions">
          <CatalogSearch aria-label="Search projects" placeholder="Search projects" value={search} onChange={(event) => changeSearch(event.target.value)} />
          {!selectionMode ? (
            <CatalogFilterButton  type="button" onClick={enterSelectionMode}>
              Select
            </CatalogFilterButton>
          ) : (
            <>
              <CatalogFilterButton
                className={` project-selection-toggle${partiallySelected ? " is-partial" : ""}`}
                type="button"
                aria-pressed={allVisibleSelected}
                aria-label={partiallySelected ? "Select all projects" : undefined}
                disabled={selectionBusy || projects.length === 0}
                onClick={toggleVisibleSelection}
              >
                {allVisibleSelected ? "Clear selection" : "Select all"}
              </CatalogFilterButton>
              <CatalogFilterButton  type="button" disabled={selectionBusy} onClick={exitSelectionMode}>
                Done
              </CatalogFilterButton>
            </>
          )}
        </div>
      </CatalogToolbar>
      {selectionMode ? (
        <div className="project-selection-toolbar" aria-busy={selectionBusy}>
          <div className="project-selection-summary">
            <strong>{`${selectedProjects.length} selected`}</strong>
            {selectionNotice ? <span role="status">{selectionNotice}</span> : null}
            {selectionError ? <span className="project-selection-error" role="alert">{selectionError}</span> : null}
          </div>
          <div className="project-selection-actions">
            <CatalogFilterButton  type="button" disabled={selectionBusy || selectedProjects.length === 0} onClick={() => void runBatchAction("favorite")}>
              {selectionBusy && batchAction === "favorite" ? "Saving…" : favoriteActionLabel}
            </CatalogFilterButton>
            <CatalogFilterButton  type="button" disabled={selectionBusy || selectedProjects.length === 0} onClick={() => void runBatchAction("trash")}>
              {selectionBusy && batchAction === "trash" ? "Moving…" : "Move to trash"}
            </CatalogFilterButton>
          </div>
        </div>
      ) : null}
      <ProjectCatalogNotice
        error={projectCatalogError}
        refreshing={projectCatalogRefreshing}
        onRetry={refreshProjects}
      />
      {actionNotice ? <div className={`project-action-toast${actionToastExiting ? " is-exiting" : ""}`} role="status" aria-live="polite">{actionNotice}</div> : null}
      <ProjectList
        leading={<CreateCard title="New Project" onClick={createProject} />}
        projects={projects}
        onOpenProject={openSavedProject}
        onTrashProject={trashSavedProject}
        onToggleFavorite={toggleSavedProjectFavorite}
        onRenameProject={openRenameDialog}
        onChangeCoverProject={setCoverTarget}
        selectionMode={selectionMode}
        selectedProjectIds={selectedProjectIds}
        selectionDisabled={selectionBusy}
        onToggleSelect={toggleProjectSelection}
      />
      {renameTarget ? (
        <ProjectRenameDialog
          key={renameTarget.projectId}
          project={renameTarget}
          onClose={closeRenameDialog}
          onRename={renameProject}
        />
      ) : null}
      {coverTarget ? (
        <ProjectCoverDialog
          key={coverTarget.projectId}
          project={coverTarget}
          onClose={() => setCoverTarget(null)}
          onUpdateCover={updateProjectCover}
        />
      ) : null}
    </section>
  );
}

function formatSavedProjectTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString();
}
