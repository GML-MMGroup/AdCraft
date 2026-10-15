import { useTranslation } from "../../i18n/useTranslation";
import { NavLink } from "react-router-dom";
import { useLogProjects } from "./useLogProjects";
import type { ProjectV2Status } from "../../types-v2";

export function LogProjectDirectory({ status, workflowId }: { status: ProjectV2Status; workflowId: string }) {
  const t = useTranslation();
  const { items, loading, error, cooldown, canLoadMore, refresh, more } = useLogProjects(status);
  return <>
    <div className="log-projects__heading"><strong>{t("Project logs")}</strong><button type="button" onClick={() => void refresh()} disabled={loading || cooldown} aria-label={t("Refresh project list")}>{t("Refresh")}</button></div>
    <nav className="log-projects__list" aria-label={t("Project log list")} aria-busy={loading}>
      {workflowId && !items.some(project => project.workflow_id === workflowId) ? (
        <NavLink to={`/logs/${encodeURIComponent(workflowId)}`} className="log-projects__item is-selected">
          <strong>{t("Current Workflow")}</strong><small>{workflowId}</small>
        </NavLink>
      ) : null}
      {items.map(project => <NavLink
        key={project.project_id}
        to={`/logs/${encodeURIComponent(project.workflow_id)}`}
        className={({ isActive }) => `log-projects__item${isActive ? " is-selected" : ""}`}
        state={{ projectName: project.name }}
      >
        <strong>{project.name || t("Untitled Project")}</strong>
        <small>{project.workflow_id}</small>
        <span>{t(project.mode === "brand" ? "Brand Professional" : "Personal Creation")}</span>
      </NavLink>)}
      {loading ? <p role="status">{t("Loading projects…")}</p> : null}
      {!loading && !error && !items.length ? <p>{t("No projects are available in this scope.")}</p> : null}
      {error ? <p role="alert" className="llm-call-history__error">{error}</p> : null}
    </nav>
    {canLoadMore ? <button className="log-projects__more" type="button" disabled={loading || cooldown} onClick={() => void more()}>{t("Load more projects")}</button> : null}
    <p className="log-projects__hint">{t("Choose a project to read its existing calls. Projects without records will be empty.")}</p>
  </>;
}
