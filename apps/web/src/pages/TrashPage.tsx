import { useMemo, useState } from "react";
import { EmptyState, PageHeader } from "../components/Layout";
import { trashItems } from "../data";
import { useApp } from "../AppContextValue";

export function TrashPage() {
  const [type, setType] = useState<"project" | "role" | "scene">("project");
  const [search, setSearch] = useState("");
  const { trashedProjects, restoreTrashedProject } = useApp();

  const localTrashItems = useMemo(
    () => trashedProjects.map((project) => ({
      key: project.project_id,
      projectId: project.project_id,
      isBackendProject: true,
      type: "project" as const,
      name: project.name,
      meta: `Deleted project · ${new Date(project.updated_at).toLocaleDateString()}`,
    })),
    [trashedProjects],
  );

  const list = useMemo(() => {
    const staticTrashItems = trashItems.map((item) => ({ key: `${item.type}-${item.name}`, projectId: null, isBackendProject: false, ...item }));
    return [...staticTrashItems, ...localTrashItems].filter((item) => item.type === type && item.name.toLowerCase().includes(search.toLowerCase()));
  }, [localTrashItems, search, type]);

  return (
    <section className="content-wrap">
      <PageHeader title="Trash" subtitle="Trashed projects can be restored here." />
      <div className="page-toolbar">
        <div className="toolbar-row">
          {(["project", "role", "scene"] as const).map((item) => (
            <button key={item} className={`filter-btn ${type === item ? "is-active" : ""}`} onClick={() => setType(item)}>
              {item.charAt(0).toUpperCase() + item.slice(1)}s
            </button>
          ))}
        </div>
        <input className="search-box" placeholder="Search deleted items" value={search} onChange={(event) => setSearch(event.target.value)} />
      </div>
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
                  disabled={!item.isBackendProject}
                  title={item.isBackendProject ? "Restore project" : "Static item"}
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
