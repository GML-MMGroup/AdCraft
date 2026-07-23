import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { v2Api } from "../../api/v2Client.ts";
import { ProjectCard } from "../../components/Cards";
import { resolveV2ProjectCover, type V2ProjectCover } from "../../projects/v2ProjectCover.ts";

export type ProjectListItem = {
  key: string;
  source: "saved";
  projectId: string;
  name: string;
  time: string;
  updatedAt: string;
  favorite: boolean;
  workflowId: string;
  coverAssetId: string | null;
};

const PROJECT_PAGE_SIZE = 36;

type ProjectCoverEntry = {
  requestKey: string;
  cover: V2ProjectCover | null;
};

type ProjectListProps = {
  projects: ProjectListItem[];
  onOpenProject: (projectId: string) => void;
  onTrashProject: (project: ProjectListItem) => void;
  onToggleFavorite: (project: ProjectListItem) => void;
  onRenameProject: (project: ProjectListItem) => void;
};

export function ProjectList({ projects, onOpenProject, onTrashProject, onToggleFavorite, onRenameProject }: ProjectListProps) {
  const [visibleCount, setVisibleCount] = useState(PROJECT_PAGE_SIZE);
  const [coversByProjectId, setCoversByProjectId] = useState<Record<string, ProjectCoverEntry>>({});
  const coverRequestsRef = useRef(new Map<string, Promise<V2ProjectCover | null>>());
  const activeCoverRequestKeysRef = useRef(new Map<string, string>());
  const visibleProjects = useMemo(() => projects.slice(0, visibleCount), [projects, visibleCount]);
  const hasMore = visibleCount < projects.length;

  useEffect(() => {
    setVisibleCount(PROJECT_PAGE_SIZE);
  }, [projects]);

  useEffect(() => {
    let cancelled = false;
    for (const project of visibleProjects) {
      const requestKey = projectCoverRequestKey(project);
      if (coversByProjectId[project.projectId]?.requestKey === requestKey) continue;
      activeCoverRequestKeysRef.current.set(project.projectId, requestKey);
      let request = coverRequestsRef.current.get(requestKey);
      if (!request) {
        request = v2Api.listWorkflowAssets(project.workflowId)
          .then((response) => resolveV2ProjectCover(project.coverAssetId, response.assets))
          .catch(() => null);
        coverRequestsRef.current.set(requestKey, request);
      }
      void request.then((cover) => {
        if (cancelled || activeCoverRequestKeysRef.current.get(project.projectId) !== requestKey) return;
        setCoversByProjectId((current) => current[project.projectId]?.requestKey === requestKey
          ? current
          : { ...current, [project.projectId]: { requestKey, cover } });
      });
    }
    return () => {
      cancelled = true;
    };
  }, [coversByProjectId, visibleProjects]);

  const loadMore = useCallback(() => {
    setVisibleCount((count) => Math.min(count + PROJECT_PAGE_SIZE, projects.length));
  }, [projects.length]);

  return (
    <>
      {visibleProjects.map((project) => (
        <ProjectListCard
          key={project.key}
          project={project}
          cover={coversByProjectId[project.projectId]?.requestKey === projectCoverRequestKey(project)
            ? coversByProjectId[project.projectId]?.cover
            : undefined}
          onOpenProject={onOpenProject}
          onTrashProject={onTrashProject}
          onToggleFavorite={onToggleFavorite}
          onRenameProject={onRenameProject}
        />
      ))}
      {hasMore ? (
        <button className="create-card project-load-more" type="button" onClick={loadMore}>
          <div>
            <span className="create-plus">+</span>
            <h3>Load more</h3>
          </div>
        </button>
      ) : null}
    </>
  );
}

function projectCoverRequestKey(project: ProjectListItem) {
  return `${project.workflowId}:${project.coverAssetId ?? "fallback"}:${project.updatedAt}`;
}

const ProjectListCard = memo(function ProjectListCard({
  project,
  cover,
  onOpenProject,
  onTrashProject,
  onToggleFavorite,
  onRenameProject,
}: {
  project: ProjectListItem;
  cover: V2ProjectCover | null | undefined;
  onOpenProject: (projectId: string) => void;
  onTrashProject: (project: ProjectListItem) => void;
  onToggleFavorite: (project: ProjectListItem) => void;
  onRenameProject: (project: ProjectListItem) => void;
}) {
  const trashProject = useCallback(() => onTrashProject(project), [onTrashProject, project]);
  const toggleFavorite = useCallback(() => onToggleFavorite(project), [onToggleFavorite, project]);
  const renameProject = useCallback(() => onRenameProject(project), [onRenameProject, project]);

  return (
    <ProjectCard
      projectId={project.projectId}
      name={project.name}
      time={project.time}
      favorite={project.favorite}
      cover={cover}
      workflowId={project.workflowId}
      onOpen={onOpenProject}
      onTrash={trashProject}
      onToggleFavorite={toggleFavorite}
      onRename={renameProject}
    />
  );
});
