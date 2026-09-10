import { useState, type CSSProperties, type ReactNode } from "react";
import type { ProjectV2Summary } from "../../types-v2";
import { resolveV2ProjectCoverSummary } from "../../projects/v2ProjectCover";
import { StableMediaPreview } from "../../workflow/StableMediaPreview";
import { useRecentProjects } from "./useRecentProjects";

type Props = {
  onOpenProject: (projectId: string) => void;
  onCreateProject: () => void;
  loadingContent: ReactNode;
};

function RecentProjectCard({ project, index, onOpenProject }: {
  project: ProjectV2Summary;
  index: number;
  onOpenProject: Props["onOpenProject"];
}) {
  const cover = project.cover_state === "ready" ? resolveV2ProjectCoverSummary(project.cover) : null;
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const source = cover?.mediaPath;
  const failed = Boolean(source && source === failedUrl) || project.cover_state === "broken";
  return (
    <button
      type="button"
      className="recent-card recent-card--project"
      aria-label={`Open ${project.name}`}
      data-project-id={project.project_id}
      data-reveal-item
      style={{ "--home-reveal-delay": `${170 + index * 70}ms` } as CSSProperties}
      onClick={() => onOpenProject(project.project_id)}
    >
      {source && !failed ? (
        <StableMediaPreview
          className="recent-card__cover"
          src={source}
          alt=""
          loading="lazy"
          decoding="async"
          onError={() => setFailedUrl(source)}
        />
      ) : (
        <span className="recent-card__missing">{failed ? "Cover unavailable" : "No cover yet"}</span>
      )}
      <div className="recent-card__caption">
        <h3 data-home-typography-region="cardTitle">{project.name}</h3>
        <p data-home-typography-region="cardMeta">
          <time dateTime={project.updated_at}>{new Date(project.updated_at).toLocaleDateString()}</time>
        </p>
      </div>
    </button>
  );
}

export function HomeRecentProjects({ onOpenProject, onCreateProject, loadingContent }: Props) {
  const { projects, loading, error, refresh } = useRecentProjects();
  return (
    <>
      {projects === null && loading && !error ? loadingContent : (
      <div className="recent-strip" data-reveal-item style={{ "--home-reveal-delay": "100ms" } as CSSProperties}>
        {error && (
          <div className="home-recent-state" role="alert">
            <p>Recent projects could not be refreshed.</p>
            <button type="button" className="home-recent-action" disabled={loading} onClick={refresh}>Retry</button>
          </div>
        )}
        {projects?.map((project, index) => <RecentProjectCard key={project.project_id} project={project} index={index} onOpenProject={onOpenProject} />)}
        {projects?.length === 0 && !error && !loading && (
          <div className="home-recent-state">
            <p>No recent projects</p>
            <button type="button" className="home-recent-action" onClick={onCreateProject}>Create project</button>
          </div>
        )}
      </div>
      )}
    </>
  );
}
