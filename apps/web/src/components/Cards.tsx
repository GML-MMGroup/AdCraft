import { imageUrl } from "../data";
import { ChevronDownIcon, StarIcon, TrashIcon } from "../icons";
import { memo, useState, type FocusEvent as ReactFocusEvent, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent } from "react";

export const ProjectCard = memo(function ProjectCard({
  projectId,
  name,
  time,
  favorite,
  img,
  onOpen,
  onTrash,
  onToggleFavorite,
}: {
  projectId: string;
  name: string;
  time: string;
  favorite: boolean;
  img: string;
  onOpen: (projectId: string) => void;
  onTrash?: () => void;
  onToggleFavorite?: () => void;
}) {
  const [actionsOpen, setActionsOpen] = useState(false);

  function handleActionTriggerClick(event: ReactMouseEvent<HTMLButtonElement>) {
    event.stopPropagation();
    setActionsOpen((open) => !open);
  }

  function handleActionMenuEnter() {
    setActionsOpen(true);
  }

  function handleActionMenuLeave(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.currentTarget.contains(document.activeElement)) (document.activeElement as HTMLElement).blur();
    setActionsOpen(false);
  }

  function handleActionMenuBlur(event: ReactFocusEvent<HTMLDivElement>) {
    if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) return;
    setActionsOpen(false);
  }

  function handleTrash(event: ReactMouseEvent<HTMLButtonElement>) {
    event.stopPropagation();
    setActionsOpen(false);
    onTrash?.();
  }

  function handleToggleFavorite(event: ReactMouseEvent<HTMLButtonElement>) {
    event.stopPropagation();
    onToggleFavorite?.();
  }

  return (
    <article className="project-card" data-project-card={name.toLowerCase()}>
      <button className="project-card-open" type="button" onClick={() => onOpen(projectId)}>
        <ProjectPreviewImage img={img} name={name} />
        <div className="card-body">
          <h3>{name}</h3>
          <p>{time}</p>
          <div className="card-meta">
            <span>{favorite ? "Favorite" : "Draft"}</span>
            <span>Open</span>
          </div>
        </div>
      </button>
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- Menu container only tracks hover/focus state; all actions are native buttons. */}
      <div className={`project-action-menu ${actionsOpen ? "is-open" : ""}`} onPointerEnter={handleActionMenuEnter} onPointerLeave={handleActionMenuLeave} onBlur={handleActionMenuBlur}>
        <button
          className="project-action-trigger"
          type="button"
          aria-label={`Open actions for ${name}`}
          aria-haspopup="menu"
          aria-expanded={actionsOpen}
          title="Project actions"
          onClick={handleActionTriggerClick}
        >
          <ChevronDownIcon />
        </button>
        <div className="project-action-list" role="menu" aria-label={`${name} actions`}>
          <button className="project-menu-btn project-trash-btn" type="button" role="menuitem" aria-label={`Move ${name} to trash`} title="Move to trash" onClick={handleTrash}>
            <TrashIcon />
          </button>
          <button
            className={`project-menu-btn project-favorite-btn ${favorite ? "is-favorite" : ""}`}
            type="button"
            role="menuitem"
            aria-label={favorite ? `Remove ${name} from favorites` : `Add ${name} to favorites`}
            aria-pressed={favorite}
            title={favorite ? "Remove favorite" : "Add favorite"}
            onClick={handleToggleFavorite}
          >
            <StarIcon />
          </button>
        </div>
      </div>
    </article>
  );
});

function ProjectPreviewImage({ img, name }: { img: string; name: string }) {
  return (
    <span className="preview project-preview-image">
      <img src={imageUrl(img)} alt="" loading="lazy" decoding="async" />
      <span className="sr-only">{name}</span>
    </span>
  );
}

export function CreateCard({ title, onClick }: { title: string; onClick: () => void }) {
  return (
    <button className="create-card" onClick={onClick}>
      <div>
        <span className="create-plus">+</span>
        <h3>{title}</h3>
      </div>
    </button>
  );
}

export function SectionTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="section-title">
      <h2>{title}</h2>
      <p>{subtitle}</p>
    </div>
  );
}
