import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { v2Api } from "../../api/v2Client.ts";
import { createRequestQueue } from "../../collections/requestQueue.ts";
import { createSettledQueryResource, stableQueryKey } from "../../collections/settledQueryResource.ts";
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
const PROJECT_COVER_REQUEST_LIMIT = 4;

type ProjectCoverEntry = {
  requestKey: string;
  cover: V2ProjectCover | null;
};

let projectCoverResource = createSettledQueryResource<V2ProjectCover | null>();
let projectCoverQueue = createRequestQueue(PROJECT_COVER_REQUEST_LIMIT);

// eslint-disable-next-line react-refresh/only-export-components -- Tests reset the module-scoped cover scheduler between cases.
export function __resetProjectCoverResourceForTests() {
  projectCoverResource = createSettledQueryResource<V2ProjectCover | null>();
  projectCoverQueue = createRequestQueue(PROJECT_COVER_REQUEST_LIMIT);
}

type ProjectListProps = {
  projects: ProjectListItem[];
  onOpenProject: (projectId: string) => void;
  onTrashProject: (project: ProjectListItem) => void;
  onToggleFavorite: (project: ProjectListItem) => void;
  onRenameProject: (project: ProjectListItem, trigger: HTMLButtonElement) => void;
};

export function ProjectList({ projects, onOpenProject, onTrashProject, onToggleFavorite, onRenameProject }: ProjectListProps) {
  const [visibleCount, setVisibleCount] = useState(PROJECT_PAGE_SIZE);
  const [coversByProjectId, setCoversByProjectId] = useState<Record<string, ProjectCoverEntry>>({});
  const activeCoverRequestKeysRef = useRef(new Map<string, string>());
  const cardElementsRef = useRef(new Map<string, HTMLElement>());
  const [visibleProjectIds, setVisibleProjectIds] = useState<Set<string>>(new Set());
  const visibleProjects = useMemo(() => projects.slice(0, visibleCount), [projects, visibleCount]);
  const hasMore = visibleCount < projects.length;

  useEffect(() => {
    setVisibleCount(PROJECT_PAGE_SIZE);
  }, [projects]);

  useEffect(() => {
    const projectIds = new Set(visibleProjects.map((project) => project.projectId));
    if (typeof IntersectionObserver === "undefined") {
      setVisibleProjectIds(projectIds);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      setVisibleProjectIds((current) => {
        const next = new Set([...current].filter((projectId) => projectIds.has(projectId)));
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const projectId = entry.target.getAttribute("data-project-id");
          if (projectId) next.add(projectId);
        }
        if (next.size === current.size && [...next].every((projectId) => current.has(projectId))) return current;
        return next;
      });
    }, { rootMargin: "240px" });
    for (const project of visibleProjects) {
      const element = cardElementsRef.current.get(project.projectId);
      if (element) observer.observe(element);
    }
    return () => observer.disconnect();
  }, [visibleProjects]);

  useEffect(() => {
    let cancelled = false;
    const activeRequestKeys = new Map<string, string>();
    const subscriptions: Array<{ release(): void }> = [];
    for (const project of visibleProjects) {
      if (!visibleProjectIds.has(project.projectId)) continue;
      const requestKey = projectCoverRequestKey(project);
      activeRequestKeys.set(project.projectId, requestKey);
      if (coversByProjectId[project.projectId]?.requestKey === requestKey) continue;
      const subscription = projectCoverResource.subscribe(projectCoverIdentity(project), (signal) => (
        projectCoverQueue.schedule(
          () => v2Api.listWorkflowAssets(project.workflowId, {}, { signal })
            .then((response) => resolveV2ProjectCover(project.coverAssetId, response.assets)),
          { signal },
        )
      ));
      subscriptions.push(subscription);
      void subscription.promise.then((cover) => {
        if (cancelled || activeCoverRequestKeysRef.current.get(project.projectId) !== requestKey) return;
        setCoversByProjectId((current) => current[project.projectId]?.requestKey === requestKey
          ? current
          : { ...current, [project.projectId]: { requestKey, cover } });
      }).catch(() => {
        if (cancelled || activeCoverRequestKeysRef.current.get(project.projectId) !== requestKey) return;
        setCoversByProjectId((current) => current[project.projectId]?.requestKey === requestKey
          ? current
          : { ...current, [project.projectId]: { requestKey, cover: null } });
      });
    }
    activeCoverRequestKeysRef.current = activeRequestKeys;
    return () => {
      cancelled = true;
      for (const subscription of subscriptions) subscription.release();
    };
  }, [coversByProjectId, visibleProjectIds, visibleProjects]);

  const registerProjectCard = useCallback((projectId: string, element: HTMLElement | null) => {
    if (element) cardElementsRef.current.set(projectId, element);
    else cardElementsRef.current.delete(projectId);
  }, []);

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
          onCardElement={registerProjectCard}
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
  return stableQueryKey(projectCoverIdentity(project));
}

function projectCoverIdentity(project: ProjectListItem) {
  return {
    workflowId: project.workflowId,
    coverAssetId: project.coverAssetId ?? "fallback",
    updatedAt: project.updatedAt,
  };
}

const ProjectListCard = memo(function ProjectListCard({
  project,
  cover,
  onOpenProject,
  onTrashProject,
  onToggleFavorite,
  onRenameProject,
  onCardElement,
}: {
  project: ProjectListItem;
  cover: V2ProjectCover | null | undefined;
  onOpenProject: (projectId: string) => void;
  onTrashProject: (project: ProjectListItem) => void;
  onToggleFavorite: (project: ProjectListItem) => void;
  onRenameProject: (project: ProjectListItem, trigger: HTMLButtonElement) => void;
  onCardElement: (projectId: string, element: HTMLElement | null) => void;
}) {
  const trashProject = useCallback(() => onTrashProject(project), [onTrashProject, project]);
  const toggleFavorite = useCallback(() => onToggleFavorite(project), [onToggleFavorite, project]);
  const renameProject = useCallback((trigger: HTMLButtonElement) => onRenameProject(project, trigger), [onRenameProject, project]);
  const cardRef = useCallback((element: HTMLElement | null) => onCardElement(project.projectId, element), [onCardElement, project.projectId]);

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
      cardRef={cardRef}
    />
  );
});
