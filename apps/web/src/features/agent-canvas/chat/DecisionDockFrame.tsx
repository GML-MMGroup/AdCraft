import { useEffect, useRef, type ReactNode } from "react";

import { ChevronDownIcon, ChevronRightIcon } from "../../../icons.tsx";
import type { DecisionDockIssue } from "./decisionDockIssue.ts";

export interface DecisionDockFrameProps {
  title: string;
  context: string;
  pending: boolean;
  issue: DecisionDockIssue | null;
  footerSummary: string;
  submitLabel: string;
  submitDisabled: boolean;
  onSubmit: () => void;
  children: ReactNode;
}

export function DecisionDockFrame({
  title,
  context,
  pending,
  issue,
  footerSummary,
  submitLabel,
  submitDisabled,
  onSubmit,
  children,
}: DecisionDockFrameProps) {
  const issueRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (issue && !issue.fieldId) issueRef.current?.focus();
  }, [issue]);

  return (
    <article className="agent-chat__decision-dock" aria-label={title} aria-busy={pending}>
      <header className="agent-chat__decision-dock-header">
        <strong>{title}</strong>
        <p>{context}</p>
      </header>
      <div className="agent-chat__decision-dock-body">{children}</div>
      {issue && !issue.fieldId ? (
        <div
          ref={issueRef}
          tabIndex={-1}
          className="agent-chat__decision-dock-issue"
          role="alert"
        >
          <strong>{issue.summary}</strong>
          {issue.detail ? (
            <details>
              <summary>Technical details</summary>
              <code>{issue.detail}</code>
            </details>
          ) : null}
        </div>
      ) : null}
      <footer className="agent-chat__decision-dock-footer">
        <span>{footerSummary}</span>
        <button
          type="button"
          disabled={pending || submitDisabled}
          onClick={onSubmit}
        >
          {pending ? "Submitting" : submitLabel}
        </button>
      </footer>
    </article>
  );
}

export interface DecisionDockDisclosureProps {
  id: string;
  label: string;
  count: number | null;
  expanded: boolean;
  disabled: boolean;
  onExpandedChange: (expanded: boolean) => void;
  children: ReactNode;
}

export function DecisionDockDisclosure({
  id,
  label,
  count,
  expanded,
  disabled,
  onExpandedChange,
  children,
}: DecisionDockDisclosureProps) {
  const buttonLabel = count === null ? label : `${label} · ${count}`;

  return (
    <div className="agent-chat__decision-dock-disclosure">
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={id}
        disabled={disabled}
        onClick={() => onExpandedChange(!expanded)}
      >
        <span>{buttonLabel}</span>
        <span aria-hidden="true">
          {expanded ? <ChevronDownIcon /> : <ChevronRightIcon />}
        </span>
      </button>
      {expanded ? (
        <div id={id} role="region" aria-label={label}>
          {children}
        </div>
      ) : null}
    </div>
  );
}
