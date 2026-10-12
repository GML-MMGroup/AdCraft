import { NavLink } from "react-router-dom";
import { useLogProjects } from "./useLogProjects";
import type { ProjectV2Status } from "../../types-v2";

export function LogProjectDirectory({ status, workflowId }: { status: ProjectV2Status; workflowId: string }) {
  const { items, loading, error, cooldown, canLoadMore, refresh, more } = useLogProjects(status);
  return <>
    <div className="log-projects__heading"><strong>项目日志</strong><button type="button" onClick={() => void refresh()} disabled={loading || cooldown} aria-label="刷新项目列表">刷新</button></div>
    <nav className="log-projects__list" aria-label="项目日志列表" aria-busy={loading}>
      {workflowId && !items.some(project => project.workflow_id === workflowId) ? (
        <NavLink to={`/logs/${encodeURIComponent(workflowId)}`} className="log-projects__item is-selected">
          <strong>当前 Workflow</strong><small>{workflowId}</small>
        </NavLink>
      ) : null}
      {items.map(project => <NavLink
        key={project.project_id}
        to={`/logs/${encodeURIComponent(project.workflow_id)}`}
        className={({ isActive }) => `log-projects__item${isActive ? " is-selected" : ""}`}
        state={{ projectName: project.name }}
      >
        <strong>{project.name || "Untitled Project"}</strong>
        <small>{project.workflow_id}</small>
        <span>{project.mode === "brand" ? "品牌专业" : "个人创作"}</span>
      </NavLink>)}
      {loading ? <p role="status">正在读取项目…</p> : null}
      {!loading && !error && !items.length ? <p>此范围暂无可查看的项目。</p> : null}
      {error ? <p role="alert" className="llm-call-history__error">{error}</p> : null}
    </nav>
    {canLoadMore ? <button className="log-projects__more" type="button" disabled={loading || cooldown} onClick={() => void more()}>加载更多项目</button> : null}
    <p className="log-projects__hint">选择项目后读取已有调用记录。无记录的项目会显示为空。</p>
  </>;
}
