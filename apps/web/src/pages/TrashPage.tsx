import { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { EmptyState, PageHeader } from "../components/Layout";
import { imageUrl, trashItems } from "../data";
import { useApp } from "../AppContextValue";

export function TrashPage() {
  const [type, setType] = useState<"project" | "role" | "scene">("project");
  const [search, setSearch] = useState("");
  const { trashedProjects, deleteTrashedProject } = useApp();

  const localTrashItems = useMemo(
    () => trashedProjects.map((project) => ({
      key: project.project_id,
      projectId: project.project_id,
      isLocal: true,
      type: project.type,
      name: project.name,
      meta: project.meta,
      img: project.img,
    })),
    [trashedProjects],
  );

  const list = useMemo(() => {
    const staticTrashItems = trashItems.map((item) => ({ key: `${item.type}-${item.name}`, projectId: null, isLocal: false, ...item }));
    return [...staticTrashItems, ...localTrashItems].filter((item) => item.type === type && item.name.toLowerCase().includes(search.toLowerCase()));
  }, [localTrashItems, search, type]);

  return (
    <section className="content-wrap">
      <PageHeader title="Trash" subtitle="Deleted projects and assets stay here before permanent cleanup." />
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
              <div className="trash-thumb" style={{ "--img": imageUrl(item.img) } as CSSProperties} />
              <div className="card-body">
                <h3>{item.name}</h3>
                <p>{item.meta}</p>
              </div>
              <div className="trash-actions">
                <button className="small-action">Restore</button>
                <button
                  className="small-action danger"
                  disabled={!item.isLocal}
                  title={item.isLocal ? "Delete permanently" : "Static demo item"}
                  onClick={(event) => {
                    event.stopPropagation();
                    if (item.projectId) deleteTrashedProject(item.projectId);
                  }}
                >
                  Delete
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
