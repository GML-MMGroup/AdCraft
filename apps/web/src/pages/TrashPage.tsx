import { useMemo, useState } from "react";
import { EmptyState, PageHeader } from "../components/Layout";
import { useApp } from "../AppContextValue";
import { ProjectCatalogNotice } from "./projects/ProjectCatalogNotice";
import "./projects.css";

export function TrashPage() {
  const [search, setSearch] = useState("");
  const {
    trashedProjects,
    restoreTrashedProject,
    projectCatalogError,
    projectCatalogRefreshing,
    refreshProjects,
  } = useApp();

  const localTrashItems = useMemo(
    () => trashedProjects.map((project) => ({
      key: project.project_id,
      projectId: project.project_id,
      name: project.name,
      meta: `Deleted project · ${new Date(project.updated_at).toLocaleDateString()}`,
    })),
    [trashedProjects],
  );

  const list = useMemo(() => localTrashItems.filter((item) => (
    item.name.toLowerCase().includes(search.toLowerCase())
  )), [localTrashItems, search]);

  return (
    <section className="content-wrap">
      <PageHeader title="Trash" subtitle="Trashed projects can be restored here." />
      <div className="page-toolbar">
        <div className="toolbar-row"><span className="filter-btn is-active">Projects</span></div>
        <input className="search-box" placeholder="Search deleted items" value={search} onChange={(event) => setSearch(event.target.value)} />
      </div>
      <ProjectCatalogNotice
        error={projectCatalogError}
        refreshing={projectCatalogRefreshing}
        onRetry={refreshProjects}
      />
      {list.length ? (
        <div className="trash-layout">
          {list.map((item) => (
            <article key={item.key} className="trash-card" data-trash-card={item.name.toLowerCase()}>
              <div className="trash-thumb" />
              <div className="card-body">
                <h3>{item.name}</h3>
                <p>{item.meta}</p>
              </div>
              <div className="trash-actions">
                <button
                  className="small-action"
                  title="Restore project"
                  onClick={(event) => {
                    event.stopPropagation();
                    if (item.projectId) void restoreTrashedProject(item.projectId);
                  }}
                >
                  Restore
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <EmptyState text="Trash is empty" />
      )}
    </section>
  );
}
