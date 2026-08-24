import type { MouseEventHandler } from "react";

export function ProposalOptionRow({
  index,
  optionId,
  title,
  summary,
  recommended = false,
  selected = false,
  disabled = false,
  readOnly = false,
  onSelect,
}: {
  index: number;
  optionId: string;
  title: string;
  summary: string;
  recommended?: boolean;
  selected?: boolean;
  disabled?: boolean;
  readOnly?: boolean;
  onSelect?: MouseEventHandler<HTMLButtonElement>;
}) {
  const content = (
    <>
      <span className="agent-chat__proposal-option-index" aria-hidden="true">
        {String(index + 1).padStart(2, "0")}
      </span>
      <span className="agent-chat__proposal-option-copy">
        <strong>
          {title}
          {recommended ? <em>Recommended</em> : null}
        </strong>
        <span>{summary}</span>
      </span>
    </>
  );

  if (readOnly) {
    return (
      <article
        className={`agent-chat__proposal-option${selected ? " is-selected" : ""}`}
        aria-label={`${selected ? "Selected option" : "Option"}: ${title}`}
        data-option-id={optionId}
      >
        {content}
      </article>
    );
  }

  return (
    <button
      type="button"
      className={`agent-chat__proposal-option${selected ? " is-selected" : ""}`}
      aria-pressed={selected}
      data-option-id={optionId}
      disabled={disabled}
      onClick={onSelect}
    >
      {content}
    </button>
  );
}
