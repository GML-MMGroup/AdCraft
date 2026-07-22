import { useCallback, useMemo, useState } from "react";
import { CreateCard } from "../components/Cards";
import { PageHeader } from "../components/Layout";
import { useApp } from "../AppContextValue";
import { PlusIcon } from "../icons";
import type { RouteName } from "../types";
import { ProjectList } from "./projects/ProjectList";
import type { ProjectListItem } from "./projects/ProjectList";

export function ProjectsPage({ navigate }: { navigate: (route: RouteName) => void }) {
  const [tab, setTab] = useState<"all" | "favorite">("all");
  const [search, setSearch] = useState("");
  const { savedProjects, startNewProject, openProject, moveProjectToTrash, renameProject, toggleProjectFavorite } = useApp();

  const createProject = useCallback(() => {
    startNewProject();
    navigate("workflow");
  }, [navigate, startNewProject]);

  const projects = useMemo(() => {
    return savedProjects.map((project) => ({
      key: project.project_id,
      source: "saved" as const,
      projectId: project.project_id,
      name: project.name,
      time: formatSavedProjectTime(project.updated_at),
      updatedAt: project.updated_at,
      favorite: project.is_favorite,
      img: null,
    })).filter((project) => {
      const visibleByTab = tab === "all" || project.favorite;
      const visibleBySearch = project.name.toLowerCase().includes(search.toLowerCase());
      return visibleByTab && visibleBySearch;
    });
  }, [savedProjects, tab, search]);

  const openSavedProject = useCallback((projectId: string) => {
    void openProject(projectId).then((opened) => {
      if (opened) navigate("workflow");
    });
  }, [navigate, openProject]);

  const trashSavedProject = useCallback((project: ProjectListItem) => {
    void moveProjectToTrash(project.projectId);
  }, [moveProjectToTrash]);

  const toggleSavedProjectFavorite = useCallback((project: ProjectListItem) => {
    const summary = savedProjects.find((item) => item.project_id === project.projectId);
    if (summary) void toggleProjectFavorite(summary);
  }, [savedProjects, toggleProjectFavorite]);

  const renameSavedProject = useCallback((project: ProjectListItem) => {
    const name = window.prompt("Project name", project.name)?.trim();
    if (name && name !== project.name) void renameProject(project.projectId, name);
  }, [renameProject]);

  return (
    <section className="content-wrap">
      <PageHeader title="All Projects" subtitle="Saved campaign workflows and creative drafts." />
      <div className="page-toolbar">
        <div className="toolbar-row">
          <button className={`filter-btn ${tab === "all" ? "is-active" : ""}`} onClick={() => setTab("all")}>
            All
          </button>
          <button className={`filter-btn ${tab === "favorite" ? "is-active" : ""}`} onClick={() => setTab("favorite")}>
            Favorites
          </button>
        </div>
        <div className="project-toolbar-actions">
          <input className="search-box" placeholder="Search projects" value={search} onChange={(event) => setSearch(event.target.value)} />
          <button className="small-action toolbar-new-project" type="button" onClick={createProject}>
            <PlusIcon />
            <span>New Project</span>
          </button>
        </div>
      </div>
      <div className="grid">
        <CreateCard title="New Project" onClick={createProject} />
        <ProjectList
          projects={projects}
          onOpenProject={openSavedProject}
          onTrashProject={trashSavedProject}
          onToggleFavorite={toggleSavedProjectFavorite}
          onRenameProject={renameSavedProject}
        />
      </div>
    </section>
  );
}

function formatSavedProjectTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Saved";
  return "Updated " + date.toLocaleDateString();
}
