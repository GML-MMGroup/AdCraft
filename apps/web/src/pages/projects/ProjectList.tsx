import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { ProjectCard } from "../../components/Cards";

export type ProjectListItem = {
  key: string;
  source: "saved";
  projectId: string;
  name: string;
  time: string;
  updatedAt: string;
  favorite: boolean;
  img?: string | null;
};

const PROJECT_PAGE_SIZE = 36;

type ProjectListProps = {
  projects: ProjectListItem[];
  onOpenProject: (projectId: string) => void;
  onTrashProject: (project: ProjectListItem) => void;
  onToggleFavorite: (project: ProjectListItem) => void;
  onRenameProject: (project: ProjectListItem) => void;
};

export function ProjectList({ projects, onOpenProject, onTrashProject, onToggleFavorite, onRenameProject }: ProjectListProps) {
  const [visibleCount, setVisibleCount] = useState(PROJECT_PAGE_SIZE);
  const visibleProjects = useMemo(() => projects.slice(0, visibleCount), [projects, visibleCount]);
  const hasMore = visibleCount < projects.length;

  useEffect(() => {
    setVisibleCount(PROJECT_PAGE_SIZE);
  }, [projects]);

  const loadMore = useCallback(() => {
    setVisibleCount((count) => Math.min(count + PROJECT_PAGE_SIZE, projects.length));
  }, [projects.length]);

  return (
    <>
      {visibleProjects.map((project) => (
        <ProjectListCard
          key={project.key}
          project={project}
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

const ProjectListCard = memo(function ProjectListCard({
  project,
  onOpenProject,
  onTrashProject,
  onToggleFavorite,
  onRenameProject,
}: {
  project: ProjectListItem;
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
      img={project.img}
      onOpen={onOpenProject}
      onTrash={trashProject}
      onToggleFavorite={toggleFavorite}
      onRename={renameProject}
    />
  );
});
