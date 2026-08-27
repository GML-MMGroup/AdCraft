import { useEffect, useState, type ReactNode } from "react";

import { ChevronDownIcon, ChevronRightIcon } from "../../../icons.tsx";
import type { StageThreadUnit } from "./stageThreadProjection.ts";

function statusLabel(status: StageThreadUnit["status"]): string {
  switch (status) {
    case "working": return "Working";
    case "waiting_user": return "Waiting for you";
    case "completed": return "Completed";
    case "failed": return "Needs attention";
    case "superseded": return "Superseded";
  }
}

function elapsedLabel(unit: StageThreadUnit): string | null {
  const elapsedMs = unit.activities.reduce((total, activity) => total + (activity.elapsed_ms ?? 0), 0);
  if (!elapsedMs) return null;
  const seconds = Math.max(1, Math.round(elapsedMs / 1000));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function threadSummary(unit: StageThreadUnit): { title: string; detail: string | null } {
  const latestPlanning = unit.planning[unit.planning.length - 1];
  if (unit.status === "working") {
    return { title: latestPlanning?.text ?? "Working on this task.", detail: null };
  }
  const latestProposal = unit.proposals[unit.proposals.length - 1];
  if (unit.status === "waiting_user") {
    return {
      title: latestProposal
        ? `Review ${latestProposal.proposal.options.length} options`
        : "Waiting for your input.",
      detail: null,
    };
  }
  const failedActivity = [...unit.activities].reverse().find((activity) => activity.status === "failed");
  const failedReceipt = [...unit.receipts].reverse().find(({ action_receipt }) => (
    action_receipt.status === "failed"
    || action_receipt.status === "rejected"
    || action_receipt.status === "not_applied"
    || action_receipt.status === "applied_with_run_error"
  ));
  if (unit.status === "failed") {
    return {
      title: failedActivity?.message
        ?? failedReceipt?.action_receipt.error_message
        ?? "This task needs attention.",
      detail: failedActivity?.error_code ?? failedReceipt?.action_receipt.error_code ?? null,
    };
  }
  if (unit.selected_option) {
    return {
      title: unit.selected_option.title,
      detail: unit.selected_option.public_summary,
    };
  }
  if (unit.capability_id === "script_authoring" && unit.completed_activity_count > 0) {
    const noun = unit.completed_activity_count === 1 ? "revision" : "revisions";
    return { title: `Completed ${unit.completed_activity_count} ${noun}`, detail: null };
  }
  return { title: statusLabel(unit.status), detail: null };
}

export function StageThread({
  unit,
  children,
  result,
  revealToken = null,
}: {
  unit: StageThreadUnit;
  children?: ReactNode;
  result?: ReactNode;
  revealToken?: number | null;
}) {
  const shouldExpand = unit.status === "working" || unit.status === "failed";
  const [expanded, setExpanded] = useState(shouldExpand);
  const summary = threadSummary(unit);
  const elapsed = elapsedLabel(unit);

  useEffect(() => {
    setExpanded(unit.status === "working" || unit.status === "failed");
  }, [unit.status]);

  useEffect(() => {
    if (revealToken !== null) setExpanded(true);
  }, [revealToken]);

  return (
    <section className={`agent-chat__stage-thread is-${unit.status}`}>
      <header>
        <div>
          <strong>{unit.capability_display_name}</strong>
          <span>
            {statusLabel(unit.status)}
            {elapsed ? ` · ${elapsed}` : ""}
          </span>
        </div>
        {children ? (
          <button
            type="button"
            aria-label={`${expanded ? "Hide" : "Show"} ${unit.capability_display_name} history`}
            aria-expanded={expanded}
            onClick={() => setExpanded((current) => !current)}
          >
            {expanded ? <ChevronDownIcon /> : <ChevronRightIcon />}
            <span>{expanded ? "Hide history" : "Show history"}</span>
          </button>
        ) : null}
      </header>
      <div className="agent-chat__stage-thread-summary">
        <strong>{summary.title}</strong>
        {summary.detail ? <p>{summary.detail}</p> : null}
      </div>
      {result}
      {expanded && children ? (
        <div className="agent-chat__stage-thread-history">{children}</div>
      ) : null}
    </section>
  );
}
