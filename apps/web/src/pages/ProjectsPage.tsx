import { useCallback, useMemo, useRef, useState } from "react";
import { CreateCard } from "../components/Cards";
import { PageHeader } from "../components/Layout";
import { useApp } from "../AppContextValue";
import type { RouteName } from "../types";
import { ProjectList } from "./projects/ProjectList";
import type { ProjectListItem } from "./projects/ProjectList";
import { ProjectRenameDialog } from "./projects/ProjectRenameDialog";
import { ProjectCatalogNotice } from "./projects/ProjectCatalogNotice";
import { useProjectDisplayNames } from "../projects/useProjectDisplayNames.ts";
import "./projects.css";

export function ProjectsPage({ navigate }: { navigate: (route: RouteName) => void }) {
  const [tab, setTab] = useState<"all" | "favorite">("all");
  const [search, setSearch] = useState("");
  const [renameTarget, setRenameTarget] = useState<ProjectListItem | null>(null);
  const [projectOpenError, setProjectOpenError] = useState<{ projectId: string; message: string } | null>(null);
  const renameTriggerRef = useRef<HTMLButtonElement | null>(null);
  const {
    savedProjects,
    startNewProject,
    openProject,
    moveProjectToTrash,
    renameProject,
    toggleProjectFavorite,
    projectCatalogError,
    projectCatalogRefreshing,
    refreshProjects,
  } = useApp();
  const projectDisplayNames = useProjectDisplayNames(savedProjects);

  const createProject = useCallback(() => {
    void startNewProject().then((created) => {
      if (created) navigate("workflow");
    });
  }, [navigate, startNewProject]);

  const projects = useMemo(() => {
    return savedProjects.map((project) => ({
      key: project.project_id,
      source: "saved" as const,
      projectId: project.project_id,
      name: projectDisplayNames[project.project_id] ?? project.name,
      time: formatSavedProjectTime(project.updated_at),
      updatedAt: project.updated_at,
      favorite: project.is_favorite,
      workflowId: project.workflow_id,
      coverAssetId: project.cover_asset_id,
    })).filter((project) => {
      const visibleByTab = tab === "all" || project.favorite;
      const visibleBySearch = project.name.toLowerCase().includes(search.toLowerCase());
      return visibleByTab && visibleBySearch;
    });
  }, [projectDisplayNames, savedProjects, tab, search]);

  const attemptOpenProject = useCallback(async (projectId: string) => {
    setProjectOpenError(null);
    try {
      const opened = await openProject(projectId);
      if (opened) {
        navigate("workflow");
        return true;
      }
    } catch {
      // Keep the project list mounted so the user can retry without losing their place.
    }
    setProjectOpenError({ projectId, message: "Project could not be opened. Try again." });
    return false;
  }, [navigate, openProject]);

  const openSavedProject = useCallback((projectId: string) => {
    void attemptOpenProject(projectId);
  }, [attemptOpenProject]);

  const retryOpeningProject = useCallback(async () => {
    if (!projectOpenError) return false;
    return attemptOpenProject(projectOpenError.projectId);
  }, [attemptOpenProject, projectOpenError]);

  const trashSavedProject = useCallback((project: ProjectListItem) => {
    void moveProjectToTrash(project.projectId);
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

  return (
    <section className="content-wrap">
      <PageHeader title="All Projects" subtitle="Saved campaign workflows and creative drafts." />
      <div className="projects-toolbar">
        <div className="toolbar-row">
          <button className={`filter-btn clear-glass-control ${tab === "all" ? "is-active" : ""}`} onClick={() => setTab("all")}>
            All
          </button>
          <button className={`filter-btn clear-glass-control ${tab === "favorite" ? "is-active" : ""}`} onClick={() => setTab("favorite")}>
            Favorites
          </button>
        </div>
        <div className="project-toolbar-actions">
          <input className="search-box clear-glass-control is-active" placeholder="Search projects" value={search} onChange={(event) => setSearch(event.target.value)} />
        </div>
      </div>
      <ProjectCatalogNotice
        error={projectOpenError?.message ?? projectCatalogError}
        refreshing={projectCatalogRefreshing}
        onRetry={projectOpenError ? retryOpeningProject : refreshProjects}
      />
      <div className="grid">
        <CreateCard title="New Project" onClick={createProject} />
        <ProjectList
          projects={projects}
          onOpenProject={openSavedProject}
          onTrashProject={trashSavedProject}
          onToggleFavorite={toggleSavedProjectFavorite}
          onRenameProject={openRenameDialog}
        />
      </div>
      {renameTarget ? (
        <ProjectRenameDialog
          key={renameTarget.projectId}
          project={renameTarget}
          onClose={closeRenameDialog}
          onRename={renameProject}
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
