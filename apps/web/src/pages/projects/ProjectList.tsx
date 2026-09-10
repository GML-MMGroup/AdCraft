import { memo, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ProjectCard } from "../../components/Cards";
import type { V2ProjectCover } from "../../projects/v2ProjectCover.ts";
import { prefetchProjectCover } from "../../projects/projectCoverPrefetch.ts";
import type { ProjectCoverStateV2 } from "../../types-v2.ts";
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
  coverVersionId?: string | null;
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
  onChangeCoverProject?: (project: ProjectListItem) => void;
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

export function ProjectList({
  projects,
  leading,
  onOpenProject,
  onTrashProject,
  onToggleFavorite,
  onRenameProject,
  onChangeCoverProject,
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
        onChangeCoverProject={onChangeCoverProject}
        selectionMode={selectionMode}
        selected={selectedProjectIds?.has(project.projectId) ?? false}
        selectionDisabled={selectionDisabled}
        onToggleSelect={onToggleSelect ? () => onToggleSelect(project.projectId) : undefined}
      />
    );
  }, [columnCount, firstVisibleRow, hasLeading, lastVisibleRow, leading, onChangeCoverProject, onOpenProject, onRenameProject, onToggleFavorite, onToggleSelect, onTrashProject, projects, selectedProjectIds, selectionDisabled, selectionMode]);

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
  onChangeCoverProject,
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
  onChangeCoverProject?: (project: ProjectListItem) => void;
  selectionMode: boolean;
  selected: boolean;
  selectionDisabled: boolean;
  onToggleSelect?: () => void;
}) {
  const trashProject = useCallback(() => onTrashProject(project), [onTrashProject, project]);
  const toggleFavorite = useCallback(() => onToggleFavorite(project), [onToggleFavorite, project]);
  const renameProject = useCallback((trigger: HTMLButtonElement) => onRenameProject(project, trigger), [onRenameProject, project]);
  const openProject = useCallback(() => {
    onOpenProject(project.projectId, project.workflowId);
  }, [onOpenProject, project.projectId, project.workflowId]);
  const cover = project.coverState === "ready" ? project.cover ?? null : null;

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
      onChangeCover={onChangeCoverProject ? () => onChangeCoverProject(project) : undefined}
      selectionMode={selectionMode}
      selected={selected}
      selectionDisabled={selectionDisabled}
      onSelect={onToggleSelect}
    />
  );
});

function getWindowWidth() {
  if (typeof window === "undefined") return PROJECT_DEFAULT_VIEWPORT_WIDTH;
  return window.innerWidth || PROJECT_DEFAULT_VIEWPORT_WIDTH;
}

function getWindowHeight() {
  if (typeof window === "undefined") return 768;
  return window.innerHeight || 768;
}
