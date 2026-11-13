import { useUiLocale } from "../../../i18n/locale.tsx";
import { useTranslation } from "../../../i18n/useTranslation.ts";
import type { MouseEventHandler } from "react";

export function ProposalOptionRow({
  index,
  marker,
  selectionRole = "button",
  optionId,
  title,
  summary,
  recommended = false,
  custom = false,
  badge,
  selected = false,
  disabled = false,
  readOnly = false,
  onSelect,
}: {
  index: number;
  marker?: string;
  selectionRole?: "button" | "radio";
  optionId: string;
  title: string;
  summary: string;
  recommended?: boolean;
  custom?: boolean;
  badge?: string;
  selected?: boolean;
  disabled?: boolean;
  readOnly?: boolean;
  onSelect?: MouseEventHandler<HTMLButtonElement>;
}) {
  const t = useTranslation("en-US");
  const locale = useUiLocale("en-US");
  const content = (
    <>
      <span className="agent-chat__proposal-option-index" aria-hidden="true">
        {custom ? "+" : marker ?? String(index + 1).padStart(2, "0")}
      </span>
      <span className="agent-chat__proposal-option-copy">
        <strong>
          {title}
          {recommended ? <em>{locale.startsWith("zh") ? t("Recommended direction") : "Recommended"}</em> : null}
          {badge ? <em>{badge}</em> : null}
        </strong>
        <span>{summary}</span>
      </span>
      {selectionRole === "radio" ? (
        <span className="agent-chat__proposal-option-check" aria-hidden="true">
          {selected ? "✓" : null}
        </span>
      ) : null}
    </>
  );

  if (readOnly) {
    return (
      <article
        className={`agent-chat__proposal-option${selected ? " is-selected" : ""}${custom ? " is-custom" : ""}`}
        aria-label={t(selected ? "Selected option: {title}" : "Option: {title}", { title })}
        data-option-id={optionId}
      >
        {content}
      </article>
    );
  }

  return (
    <button
      type="button"
      className={`agent-chat__proposal-option${selected ? " is-selected" : ""}${custom ? " is-custom" : ""}`}
      role={selectionRole === "radio" ? "radio" : undefined}
      aria-checked={selectionRole === "radio" ? selected : undefined}
      aria-pressed={selectionRole === "button" ? selected : undefined}
      data-option-id={optionId}
      disabled={disabled}
      onClick={onSelect}
    >
      {content}
    </button>
  );
}
