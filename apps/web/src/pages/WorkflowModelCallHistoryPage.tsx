import { useTranslation } from "../i18n/useTranslation";
import { LanguageSwitcher } from "../components/LanguageSwitcher";
import { useState } from "react";
import { Link, Navigate, useLocation, useParams } from "react-router-dom";
import type { ProjectV2Status } from "../types-v2";
import { LogProjectDirectory } from "../features/model-call-history/LogProjectDirectory";
import { WorkflowCallHistory } from "../features/model-call-history/WorkflowCallHistory";
import "./workflow-model-call-history.css";
import "./log-workspace.css";

/** Intentionally outside Layout/WorkspaceRoute: opening logs never mounts canvas runtime. */
export function WorkflowModelCallHistoryPage() {
  const t = useTranslation();
  const { workflowId = "" } = useParams<{ workflowId: string }>();
  const [status, setStatus] = useState<ProjectV2Status>("active");
  const location = useLocation();
  const projectName = typeof location.state?.projectName === "string" ? location.state.projectName : undefined;

  return <main className="llm-call-history log-workspace" aria-label={t("Project logs")}>
    <div className="log-workspace__toolbar" aria-label={t("Log workspace tools")}>
      <LanguageSwitcher workflowId={workflowId || null} />
    </div>
    <aside className="log-projects" aria-label={t("Project log list")}>
      <Link className="log-projects__brand" to="/logs">{t("Logs")}<span>{t("AdCraft · Read-only call records")}</span></Link>
      <label className="log-projects__scope">{t("Project scope")}
        <select value={status} onChange={event => setStatus(event.target.value as ProjectV2Status)}>
          <option value="active">{t("Active projects")}</option><option value="archived">{t("Archived projects")}</option><option value="trashed">{t("Trashed projects")}</option>
        </select>
      </label>
      <LogProjectDirectory key={status} status={status} workflowId={workflowId}/>
    </aside>
    {workflowId ? <WorkflowCallHistory key={workflowId} workflowId={workflowId} projectName={projectName}/> : (
      <section className="log-workspace__welcome">
        <span className="llm-call-history__eyebrow">{t("PROJECT LOGS")}</span>
        <h1>{t("All project calls, in one place")}</h1>
        <p>{t("Choose a project on the left to inspect actual model inputs, parameters, outputs and errors.")}</p>
        <p className="llm-call-history__muted">{t("Only existing records are shown. This page never starts, retries or advances a Workflow.")}</p>
      </section>
    )}
  </main>;
}

export function LegacyCallHistoryRedirect() {
  const { workflowId = "" } = useParams<{ workflowId: string }>();
  return <Navigate to={`/logs/${encodeURIComponent(workflowId)}`} replace/>;
}
