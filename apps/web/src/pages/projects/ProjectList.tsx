import { memo, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { agentCanvasApi } from "../../api/agentCanvasApi.ts";
import { createRequestQueue } from "../../collections/requestQueue.ts";
import { createSettledQueryResource, stableQueryKey } from "../../collections/settledQueryResource.ts";
import { ProjectCard } from "../../components/Cards";
import { loadProjectCoverCache, saveProjectCoverCache } from "../../projects/projectCoverCache.ts";
import { needsV2ProjectCoverNodeAuthority, resolveV2ProjectCover, type V2ProjectCover } from "../../projects/v2ProjectCover.ts";
import { prefetchProjectCover } from "../../projects/projectCoverPrefetch.ts";
import type { ProjectAssetSummaryV2, ProjectCoverStateV2 } from "../../types-v2.ts";
import {
  getProjectGridColumnCount,
  getVirtualProjectWindow,
  PROJECT_GRID_GAP,
  PROJECT_GRID_ROW_HEIGHT,
  PROJECT_VIRTUAL_OVERSCAN_ROWS,
} from "./projectListVirtualization.ts";

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
  coverState?: ProjectCoverStateV2;
  cover?: V2ProjectCover | null;
};

type ProjectListProps = {
  projects: ProjectListItem[];
  leading?: ReactNode;
  onOpenProject: (projectId: string, workflowId?: string) => void;
  onTrashProject: (project: ProjectListItem) => void;
  onToggleFavorite: (project: ProjectListItem) => void;
  onRenameProject: (project: ProjectListItem, trigger: HTMLButtonElement) => void;
  selectionMode?: boolean;
  selectedProjectIds?: ReadonlySet<string>;
  selectionDisabled?: boolean;
  onToggleSelect?: (projectId: string) => void;
};

type ViewportMetrics = {
  width: number;
  scrollTop: number;
  viewportHeight: number;
};

const PROJECT_DEFAULT_VIEWPORT_WIDTH = 1024;
const PROJECT_COVER_REQUEST_LIMIT = 4;
type ProjectCoverEntry = {
  cover: V2ProjectCover | null;
};

type ProjectCoverLookup = {
  cover: V2ProjectCover | null;
  assets: readonly ProjectAssetSummaryV2[];
  needsAuthority: boolean;
};

let projectCoverResource = createSettledQueryResource<ProjectCoverLookup>();
let projectCoverAuthorityResource = createSettledQueryResource<V2ProjectCover | null>();
let projectCoverQueue = createRequestQueue(PROJECT_COVER_REQUEST_LIMIT);

// eslint-disable-next-line react-refresh/only-export-components -- Tests reset the module-scoped cover scheduler between cases.
export function __resetProjectCoverResourceForTests() {
  projectCoverResource = createSettledQueryResource<ProjectCoverLookup>();
  projectCoverAuthorityResource = createSettledQueryResource<V2ProjectCover | null>();
  projectCoverQueue = createRequestQueue(PROJECT_COVER_REQUEST_LIMIT);
}

/** Stop background cover work before a project opens without discarding settled covers. */
export function cancelProjectCoverRequests() {
  projectCoverResource.cancelPending();
  projectCoverAuthorityResource.cancelPending();
}

export function ProjectList({
  projects,
  leading,
  onOpenProject,
  onTrashProject,
  onToggleFavorite,
  onRenameProject,
  selectionMode = false,
  selectedProjectIds,
  selectionDisabled = false,
  onToggleSelect,
}: ProjectListProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState<ViewportMetrics>(() => ({
    width: getWindowWidth(),
    scrollTop: 0,
    viewportHeight: getWindowHeight(),
  }));
  const hasLeading = leading !== undefined && leading !== null;
  const itemCount = projects.length + (hasLeading ? 1 : 0);
  const columnCount = useMemo(
    () => getProjectGridColumnCount(viewport.width || PROJECT_DEFAULT_VIEWPORT_WIDTH),
    [viewport.width],
  );
  const virtualWindow = useMemo(() => getVirtualProjectWindow({
    itemCount,
    columnCount,
    scrollTop: viewport.scrollTop,
    viewportHeight: viewport.viewportHeight,
    rowHeight: PROJECT_GRID_ROW_HEIGHT,
    overscanRows: PROJECT_VIRTUAL_OVERSCAN_ROWS,
  }), [columnCount, itemCount, viewport.scrollTop, viewport.viewportHeight]);
  const firstVisibleRow = Math.floor(Math.max(0, viewport.scrollTop) / PROJECT_GRID_ROW_HEIGHT);
  const lastVisibleRow = Math.max(
    firstVisibleRow + 1,
    Math.ceil((Math.max(0, viewport.scrollTop) + viewport.viewportHeight) / PROJECT_GRID_ROW_HEIGHT),
  );

  useEffect(() => {
    const element = listRef.current;
    if (!element) return undefined;
    let frame = 0;

    const measure = () => {
      frame = 0;
      const rect = element.getBoundingClientRect();
      const pageScrollTop = window.scrollY || document.documentElement.scrollTop || 0;
      const listTop = rect.top + pageScrollTop;
      const next = {
        width: rect.width || element.clientWidth || getWindowWidth(),
        scrollTop: Math.max(0, pageScrollTop - listTop),
        viewportHeight: getWindowHeight(),
      };
      setViewport((current) => (
        current.width === next.width
          && current.scrollTop === next.scrollTop
          && current.viewportHeight === next.viewportHeight
          ? current
          : next
      ));
    };

    const scheduleMeasure = () => {
      if (frame) return;
      if (typeof window.requestAnimationFrame !== "function") {
        measure();
        return;
      }
      frame = window.requestAnimationFrame(measure);
    };

    measure();
    window.addEventListener("scroll", scheduleMeasure, { passive: true });
    window.addEventListener("resize", scheduleMeasure, { passive: true });
    const resizeObserver = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(scheduleMeasure);
    resizeObserver?.observe(element);

    return () => {
      window.removeEventListener("scroll", scheduleMeasure);
      window.removeEventListener("resize", scheduleMeasure);
      resizeObserver?.disconnect();
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, []);

  const renderItem = useCallback((index: number) => {
    if (hasLeading && index === 0) return leading;
    const projectIndex = index - (hasLeading ? 1 : 0);
    const project = projects[projectIndex];
    if (!project) return null;
    const row = Math.floor(index / columnCount);
    return (
      <ProjectListCard
        key={project.key}
        project={project}
        coverPriority={row === firstVisibleRow ? 3 : row < lastVisibleRow ? 2 : 1}
        onOpenProject={onOpenProject}
        onTrashProject={onTrashProject}
        onToggleFavorite={onToggleFavorite}
        onRenameProject={onRenameProject}
        selectionMode={selectionMode}
        selected={selectedProjectIds?.has(project.projectId) ?? false}
        selectionDisabled={selectionDisabled}
        onToggleSelect={onToggleSelect ? () => onToggleSelect(project.projectId) : undefined}
      />
    );
  }, [columnCount, firstVisibleRow, hasLeading, lastVisibleRow, leading, onOpenProject, onRenameProject, onToggleFavorite, onToggleSelect, onTrashProject, projects, selectedProjectIds, selectionDisabled, selectionMode]);

  return (
    <div
      ref={listRef}
      className="project-list-virtual"
      data-project-list-virtualized="true"
      data-project-list-mounted-count={Math.max(0, virtualWindow.endIndex - virtualWindow.startIndex)}
      style={{ height: `${virtualWindow.totalHeight}px` }}
    >
      <div
        className="project-list-virtual__window"
        style={{
          gridTemplateColumns: `repeat(${columnCount}, minmax(0, 1fr))`,
          gap: `${PROJECT_GRID_GAP}px`,
          transform: `translateY(${virtualWindow.startRow * PROJECT_GRID_ROW_HEIGHT}px)`,
        }}
      >
        {Array.from({ length: virtualWindow.endIndex - virtualWindow.startIndex }, (_, offset) => (
          <div className="project-list-virtual__item" key={virtualWindow.startIndex + offset}>
            {renderItem(virtualWindow.startIndex + offset)}
          </div>
        ))}
      </div>
    </div>
  );
}

const ProjectListCard = memo(function ProjectListCard({
  project,
  coverPriority,
  onOpenProject,
  onTrashProject,
  onToggleFavorite,
  onRenameProject,
  selectionMode,
  selected,
  selectionDisabled,
  onToggleSelect,
}: {
  project: ProjectListItem;
  coverPriority: number;
  onOpenProject: (projectId: string, workflowId?: string) => void;
  onTrashProject: (project: ProjectListItem) => void;
  onToggleFavorite: (project: ProjectListItem) => void;
  onRenameProject: (project: ProjectListItem, trigger: HTMLButtonElement) => void;
  selectionMode: boolean;
  selected: boolean;
  selectionDisabled: boolean;
  onToggleSelect?: () => void;
}) {
  const trashProject = useCallback(() => onTrashProject(project), [onTrashProject, project]);
  const toggleFavorite = useCallback(() => onToggleFavorite(project), [onToggleFavorite, project]);
  const renameProject = useCallback((trigger: HTMLButtonElement) => onRenameProject(project, trigger), [onRenameProject, project]);
  const openProject = useCallback(() => {
    cancelProjectCoverRequests();
    onOpenProject(project.projectId, project.workflowId);
  }, [onOpenProject, project.projectId, project.workflowId]);
  const cover = useProjectCover(project, coverPriority);

  useEffect(() => {
    prefetchProjectCover(cover, coverPriority);
  }, [cover, coverPriority]);

  return (
    <ProjectCard
      projectId={project.projectId}
      name={project.name}
      time={project.time}
      favorite={project.favorite}
      cover={cover}
      coverPriority={coverPriority}
      workflowId={project.workflowId}
      onOpen={openProject}
      onTrash={trashProject}
      onToggleFavorite={toggleFavorite}
      onRename={renameProject}
      selectionMode={selectionMode}
      selected={selected}
      selectionDisabled={selectionDisabled}
      onSelect={onToggleSelect}
    />
  );
});

function useProjectCover(project: ProjectListItem, coverPriority: number): V2ProjectCover | null | undefined {
  const { workflowId, coverAssetId, coverState, updatedAt, cover: summaryCover } = project;
  const requestKey = projectCoverRequestKey({ workflowId, coverAssetId, updatedAt });
  const cacheKey = projectCoverCacheKey(project.projectId);
  const [entry, setEntry] = useState<ProjectCoverEntry | null>(null);

  useEffect(() => {
    if (summaryCover) {
      setEntry({ cover: summaryCover });
      return undefined;
    }
    if (coverState !== undefined && coverState !== "unresolved") {
      setEntry({ cover: null });
      return undefined;
    }
    const cachedCover = loadProjectCoverCache(cacheKey, undefined, { allowStale: true });
    setEntry(cachedCover ? { cover: cachedCover } : null);
    let active = true;
    let authoritySubscription: ReturnType<typeof projectCoverAuthorityResource.subscribe> | undefined;
    const subscription = projectCoverResource.subscribe(projectCoverIdentity({ workflowId, coverAssetId, updatedAt }), (signal) => (
      projectCoverQueue.schedule(
        () => agentCanvasApi.listAgentCanvasProjectAssets(workflowId, { signal })
          .then((response) => {
            const preliminary = resolveV2ProjectCover(coverAssetId, response.assets);
            return {
              cover: preliminary,
              assets: response.assets,
              needsAuthority: needsV2ProjectCoverNodeAuthority(response.assets),
            };
          }),
        { signal, priority: coverPriority },
      )
    ));
    void subscription.promise.then((lookup) => {
      if (!active) return;
      if (lookup.cover) saveProjectCoverCache(cacheKey, lookup.cover);
      setEntry({ cover: lookup.cover });
      if (!lookup.needsAuthority) return;

      authoritySubscription = projectCoverAuthorityResource.subscribe(projectCoverIdentity({ workflowId, coverAssetId, updatedAt }), (authoritySignal) => (
        projectCoverQueue.schedule(
          () => agentCanvasApi.agentCanvasWorkflowWithEtag(workflowId, { signal: authoritySignal })
            .then((workflow) => resolveV2ProjectCover(coverAssetId, lookup.assets, workflow.value.nodes)),
          { signal: authoritySignal, priority: coverPriority },
        )
      ));
      void authoritySubscription.promise.then((authoritativeCover) => {
        const nextCover = authoritativeCover ?? lookup.cover;
        if (nextCover) saveProjectCoverCache(cacheKey, nextCover);
        if (active) setEntry({ cover: nextCover });
      }).catch(() => {
        // The preliminary cover remains usable when optional authority lookup fails.
      });
    }).catch(() => {
      if (active) setEntry({ cover: null });
    });

    return () => {
      active = false;
      subscription.release();
      authoritySubscription?.release();
    };
  }, [cacheKey, coverAssetId, coverPriority, coverState, requestKey, summaryCover, updatedAt, workflowId]);

  return entry?.cover;
}

function projectCoverRequestKey(project: Pick<ProjectListItem, "workflowId" | "coverAssetId" | "updatedAt">) {
  return stableQueryKey(projectCoverIdentity(project));
}

function projectCoverCacheKey(projectId: string) {
  return `project:${projectId}`;
}

function projectCoverIdentity(project: Pick<ProjectListItem, "workflowId" | "coverAssetId" | "updatedAt">) {
  return {
    workflowId: project.workflowId,
    coverAssetId: project.coverAssetId ?? "fallback",
    updatedAt: project.updatedAt,
  };
}

function getWindowWidth() {
  if (typeof window === "undefined") return PROJECT_DEFAULT_VIEWPORT_WIDTH;
  return window.innerWidth || PROJECT_DEFAULT_VIEWPORT_WIDTH;
}

function getWindowHeight() {
  if (typeof window === "undefined") return 768;
  return window.innerHeight || 768;
}
