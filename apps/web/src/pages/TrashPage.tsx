import { CatalogToolbar, CatalogFilterButton, CatalogSearch } from "../components/CatalogToolbar";
import { useCallback, useMemo, useRef, useState } from "react";
import { EmptyState, PageHeader } from "../components/Layout";
import { useApp } from "../AppContextValue";
import type { RouteName } from "../types";
import { ProjectCatalogNotice } from "./projects/ProjectCatalogNotice";
import "./projects.css";
import { useLocale, localeText } from "../i18n/locale.tsx";
import { TrashIcon } from "../icons";

type TrashListItem = {
  key: string;
  projectId: string;
  projectVersion: number;
  name: string;
  meta: string;
};

export function TrashPage({ navigate }: { navigate?: (route: RouteName) => void } = {}) {
  const { locale } = useLocale();
  const labels = locale === "zh-CN" ? localeText.zh.trashPage : localeText.en.trashPage;
  const deletionInFlight = useRef(false);
  const [search, setSearch] = useState("");
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedProjectIds, setSelectedProjectIds] = useState<Set<string>>(() => new Set());
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [batchAction, setBatchAction] = useState<"restore" | "delete" | null>(null);
  const {
    trashedProjects,
    restoreTrashedProject,
    permanentlyDeleteTrashedProject,
    projectCatalogError,
    projectCatalogRefreshing,
    refreshProjects,
  } = useApp();

  const localTrashItems = useMemo(
    () => trashedProjects.map((project) => ({
      key: project.project_id,
      projectId: project.project_id,
      projectVersion: project.project_version,
      name: project.name,
      meta: labels.deletedMeta.replace("{date}", new Date(project.updated_at).toLocaleDateString()),
    })),
    [labels, trashedProjects],
  );

  const list = useMemo(() => localTrashItems.filter((item) => (
    item.name.toLowerCase().includes(search.toLowerCase())
  )), [localTrashItems, search]);

  const selectedProjects = useMemo(
    () => list.filter((item) => selectedProjectIds.has(item.projectId)),
    [list, selectedProjectIds],
  );
  const allVisibleSelected = list.length > 0 && list.every((item) => selectedProjectIds.has(item.projectId));
  const partiallySelected = selectedProjects.length > 0 && !allVisibleSelected;
  const selectionBusy = batchAction !== null;

  const clearSelectionForListChange = useCallback(() => {
    setSelectedProjectIds((current) => current.size > 0 ? new Set() : current);
    setSelectionError(null);
  }, []);

  const changeSearch = useCallback((value: string) => {
    if (value !== search) clearSelectionForListChange();
    setSearch(value);
  }, [clearSelectionForListChange, search]);

  const enterSelectionMode = useCallback(() => {
    setSelectionMode(true);
    setSelectedProjectIds(new Set());
    setSelectionError(null);
  }, []);

  const exitSelectionMode = useCallback(() => {
    if (selectionBusy) return;
    setSelectionMode(false);
    setSelectedProjectIds(new Set());
    setSelectionError(null);
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
      : new Set(list.map((item) => item.projectId)));
  }, [allVisibleSelected, list, selectionBusy]);

  const runBatchRestore = useCallback(async () => {
    if (selectionBusy || selectedProjects.length === 0) return;

    const snapshot = [...selectedProjects];
    setBatchAction("restore");
    setSelectionError(null);
    const results = await Promise.allSettled(
      snapshot.map((item) => restoreTrashedProject(item.projectId)),
    );
    const failedProjectIds = new Set(
      snapshot
        .filter((_, index) => {
          const result = results[index];
          return result?.status === "rejected" || (result?.status === "fulfilled" && result.value !== true);
        })
        .map((item) => item.projectId),
    );

    setBatchAction(null);
    if (failedProjectIds.size > 0) {
      setSelectionError(labels.restoredFailed
        .replace("{count}", String(failedProjectIds.size))
        .replace("{noun}", failedProjectIds.size === 1 ? "project" : "projects"));
      setSelectedProjectIds(failedProjectIds);
      return;
    }

    setSelectedProjectIds(new Set());
    setSelectionMode(false);
  }, [labels, restoreTrashedProject, selectedProjects, selectionBusy]);

  const runPermanentDelete = useCallback(async (items: TrashListItem[]) => {
    if (selectionBusy || deletionInFlight.current || items.length === 0) return;
    const snapshot = [...items];
    if (!window.confirm(`${labels.confirmDelete.replace("{count}", String(snapshot.length))}\n\n${snapshot.slice(0, 10).map((item) => item.name).join("\n")}`)) return;
    deletionInFlight.current = true;
    setBatchAction("delete");
    setSelectionError(null);
    const failed = new Set<string>();
    const reasons: string[] = [];
    try {
      for (const item of snapshot) {
        try {
          if (!await permanentlyDeleteTrashedProject(item.projectId, item.projectVersion)) throw new Error(labels.deleteFailed.replace("{count}", "1"));
        } catch (error) {
          failed.add(item.projectId);
          const code = error && typeof error === "object" && "code" in error ? error.code : undefined;
          reasons.push(code === "project_deletion_busy" ? labels.deleteBusy
            : code === "project_state_conflict" || code === "project_not_trashed" ? labels.deleteStale
            : error instanceof Error ? error.message : labels.deleteFailed.replace("{count}", "1"));
        }
      }
      setSelectedProjectIds(failed);
      if (failed.size === 0) setSelectionMode(false);
      else setSelectionError(`${labels.deleteFailed.replace("{count}", String(failed.size))} ${[...new Set(reasons)].join(" ")}`);
      await refreshProjects();
    } finally {
      deletionInFlight.current = false;
      setBatchAction(null);
    }
  }, [labels, permanentlyDeleteTrashedProject, refreshProjects, selectionBusy]);

  return (
    <section className="content-wrap trash-page">
      <PageHeader title={labels.title} editorial />
      <CatalogToolbar className="projects-toolbar">
        <div className="toolbar-row">
          <CatalogFilterButton className=" is-active" type="button" onClick={() => navigate?.("projects")}>
            {labels.projects}
          </CatalogFilterButton>
        </div>
        <div className="catalog-toolbar-actions">
          <CatalogSearch aria-label={labels.search} placeholder={labels.search} value={search} disabled={selectionBusy} onChange={(event) => changeSearch(event.target.value)} />
          {!selectionMode ? (
            <CatalogFilterButton  type="button" disabled={selectionBusy} onClick={enterSelectionMode}>
              {labels.select}
            </CatalogFilterButton>
          ) : (
            <>
              <CatalogFilterButton
                className={` project-selection-toggle${partiallySelected ? " is-partial" : ""}`}
                type="button"
                aria-pressed={allVisibleSelected}
                aria-label={partiallySelected ? (locale === "zh-CN" ? "全选已删除项目" : "Select all deleted projects") : undefined}
                disabled={selectionBusy || list.length === 0}
                onClick={toggleVisibleSelection}
              >
                {allVisibleSelected ? labels.clearSelection : labels.selectAll}
              </CatalogFilterButton>
              <CatalogFilterButton  type="button" disabled={selectionBusy} onClick={exitSelectionMode}>
                {labels.done}
              </CatalogFilterButton>
            </>
          )}
          <CatalogFilterButton
            className="trash-delete-action"
            disabled={selectionBusy || localTrashItems.length === 0}
            onClick={() => void runPermanentDelete(localTrashItems)}
          >
            <TrashIcon />
            {batchAction === "delete" ? labels.deleting : labels.emptyTrash}
          </CatalogFilterButton>
        </div>
      </CatalogToolbar>
      {selectionError ? <p className="project-selection-error" role="alert">{selectionError}</p> : null}
      {selectionMode ? (
        <div className="project-selection-toolbar" aria-busy={selectionBusy}>
          <div className="project-selection-summary">
            <strong>{`${selectedProjects.length} ${labels.selected}`}</strong>
          </div>
          <div className="project-selection-actions">
            <CatalogFilterButton  type="button" disabled={selectionBusy || selectedProjects.length === 0} onClick={() => void runBatchRestore()}>
              {selectionBusy ? labels.restoring : labels.restoreSelected}
            </CatalogFilterButton>
            <CatalogFilterButton
              className="trash-delete-action"
              disabled={selectionBusy || selectedProjects.length === 0}
              onClick={() => void runPermanentDelete(selectedProjects)}
            >
              <TrashIcon />
              {labels.deleteSelected}
            </CatalogFilterButton>
          </div>
        </div>
      ) : null}
      <ProjectCatalogNotice
        error={projectCatalogError}
        refreshing={projectCatalogRefreshing}
        onRetry={refreshProjects}
      />
      {list.length ? (
        <div className="trash-layout">
          {list.map((item) => (
            <article key={item.key} className={`trash-card${selectionMode ? " is-selection-mode" : ""}${selectedProjectIds.has(item.projectId) ? " is-selected" : ""}`} data-trash-card={item.name.toLowerCase()}>
              {selectionMode ? (
                <button
                  className="trash-card-select-area"
                  type="button"
                  aria-label={`${selectedProjectIds.has(item.projectId) ? "Deselect" : "Select"} ${item.name}`}
                  aria-pressed={selectedProjectIds.has(item.projectId)}
                  disabled={selectionBusy}
                  onClick={() => toggleProjectSelection(item.projectId)}
                >
                  <div className="trash-thumb" />
                  <div className="card-body">
                    <h3>{item.name}</h3>
                    <p>{item.meta}</p>
                  </div>
                </button>
              ) : (
                <>
                  <div className="trash-thumb" />
                  <div className="card-body">
                    <h3>{item.name}</h3>
                    <p>{item.meta}</p>
                  </div>
                </>
              )}
              {selectionMode ? (
                <input
                  className="trash-card-select"
                  type="checkbox"
                  checked={selectedProjectIds.has(item.projectId)}
                  disabled={selectionBusy}
                  aria-label={`Select ${item.name}`}
                  onClick={(event) => event.stopPropagation()}
                  onChange={() => toggleProjectSelection(item.projectId)}
                />
              ) : (
                <div className="trash-actions">
                  <button
                    className="small-action"
                    title={labels.restore}
                    disabled={selectionBusy}
                    onClick={(event) => {
                      event.stopPropagation();
                      void restoreTrashedProject(item.projectId);
                    }}
                  >
                    {labels.restore}
                  </button>
                  <button
                    type="button"
                    className="small-action trash-delete-action"
                    disabled={selectionBusy}
                    onClick={() => void runPermanentDelete([item])}
                  >
                    <TrashIcon />
                    {labels.deletePermanently}
                  </button>
                </div>
              )}
            </article>
          ))}
        </div>
      ) : (
        <EmptyState text={labels.empty} />
      )}
    </section>
  );
}
