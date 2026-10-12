import { useState } from "react";
import { Link, Navigate, useLocation, useParams } from "react-router-dom";
import type { ProjectV2Status } from "../types-v2";
import { LogProjectDirectory } from "../features/model-call-history/LogProjectDirectory";
import { WorkflowCallHistory } from "../features/model-call-history/WorkflowCallHistory";
import "./workflow-model-call-history.css";
import "./log-workspace.css";

/** Intentionally outside Layout/WorkspaceRoute: opening logs never mounts canvas runtime. */
export function WorkflowModelCallHistoryPage() {
  const { workflowId = "" } = useParams<{ workflowId: string }>();
  const [status, setStatus] = useState<ProjectV2Status>("active");
  const location = useLocation();
  const projectName = typeof location.state?.projectName === "string" ? location.state.projectName : undefined;

  return <main className="llm-call-history log-workspace" aria-label="项目调用日志">
    <aside className="log-projects" aria-label="日志项目导航">
      <Link className="log-projects__brand" to="/logs">Logs<span>AdCraft · 只读调用记录</span></Link>
      <label className="log-projects__scope">项目范围
        <select value={status} onChange={event => setStatus(event.target.value as ProjectV2Status)}>
          <option value="active">正常项目</option><option value="archived">归档项目</option><option value="trashed">回收站项目</option>
        </select>
      </label>
      <LogProjectDirectory key={status} status={status} workflowId={workflowId}/>
    </aside>
    {workflowId ? <WorkflowCallHistory key={workflowId} workflowId={workflowId} projectName={projectName}/> : (
      <section className="log-workspace__welcome">
        <span className="llm-call-history__eyebrow">PROJECT LOGS</span>
        <h1>所有项目的调用记录，一处查看</h1>
        <p>从左侧选择项目，查看模型的实际输入、参数、输出与错误。</p>
        <p className="llm-call-history__muted">这里仅展示已有记录，不会启动、重试或推进 Workflow。</p>
      </section>
    )}
  </main>;
}

export function LegacyCallHistoryRedirect() {
  const { workflowId = "" } = useParams<{ workflowId: string }>();
  return <Navigate to={`/logs/${encodeURIComponent(workflowId)}`} replace/>;
}
