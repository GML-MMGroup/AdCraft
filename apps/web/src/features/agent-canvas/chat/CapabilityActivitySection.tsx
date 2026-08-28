import { useState } from "react";
import { TextLoader } from "generative-loaders";

import type {
  AgentCanvasChatTurnV2,
  ChatCapabilityActivityV2,
} from "../../../types-v2.ts";
import { AgentCapabilityIdentity } from "./AgentCapabilityIdentity.tsx";

function recoveryStageLabel(stage: string | null | undefined): string | null {
  if (stage === "waiting" || stage === "waiting_provider_response" || stage === "provider_waiting") {
    return "Waiting";
  }
  if (stage === "retrying") return "Retrying";
  if (stage === "validating") return "Validating";
  if (stage === "publishing") return "Publishing";
  if (stage === "queued") return "Queued";
  if (stage === "running") return "Working";
  return null;
}

function activityStageLabel(
  activity: ChatCapabilityActivityV2,
  turn: AgentCanvasChatTurnV2 | null | undefined,
  retrying: boolean,
): string {
  if (retrying) return "Retrying";
  return recoveryStageLabel(turn?.operation_stage)
    ?? activity.status.replaceAll("_", " ").replace(/^./, (character) => character.toUpperCase());
}

function activityAriaLabel(capabilityName: string, stage: string): string {
  return stage === "Working"
    ? `${capabilityName} is working`
    : `${capabilityName} ${stage.toLowerCase()}`;
}

export function formatActivityDuration(elapsedMs: number | null): string | null {
  if (elapsedMs === null) return null;
  const totalSeconds = Math.max(1, Math.round(elapsedMs / 1_000));
  const hours = Math.floor(totalSeconds / 3_600);
  const minutes = Math.floor((totalSeconds % 3_600) / 60);
  const seconds = totalSeconds % 60;
  const parts = [
    hours ? `${hours}h` : null,
    minutes ? `${minutes}m` : null,
    seconds || (!hours && !minutes) ? `${seconds}s` : null,
  ].filter(Boolean);
  return `for ${parts.join(" ")}`;
}

export function CapabilityActivityRow({
  activity,
  turn,
  retrying = false,
  compact = false,
  onRetry,
  onReviseRequest,
}: {
  activity: ChatCapabilityActivityV2;
  turn?: AgentCanvasChatTurnV2 | null;
  retrying?: boolean;
  compact?: boolean;
  onRetry?: () => void;
  onReviseRequest?: () => void;
}) {
  const [technicalDetailsOpen, setTechnicalDetailsOpen] = useState(false);
  const retryable = turn?.retryable ?? activity.retryable;
  const errorCode = turn?.operation_failure?.code ?? activity.error_code;
  const errorMessage = turn?.operation_failure?.message ?? activity.message;
  const terminalActivity = activity.status === "completed"
    || activity.status === "failed"
    || activity.status === "superseded";
  const waitingForModel = turn?.operation_stage === "waiting"
    || turn?.operation_stage === "waiting_provider_response"
    || turn?.operation_stage === "provider_waiting";
  const showTextLoader = !terminalActivity
    && (activity.status === "working" || waitingForModel);
  const stage = activityStageLabel(activity, turn, retrying);
  const duration = formatActivityDuration(activity.elapsed_ms);
  const body = activity.presentation_text
    ?? (activity.status === "superseded"
      ? `${activity.capability_display_name} was superseded by later progress`
      : activity.status === "completed" ? activity.message : null);
  const technicalFailure = activity.status === "failed" && (errorCode || errorMessage)
    ? JSON.stringify({
        code: errorCode ?? null,
        message: errorMessage ?? null,
        validation_paths: turn?.operation_failure?.validation_paths ?? activity.validation_paths,
      }, null, 2)
    : null;
  const fallbackWarning = activity.completion_mode === "deterministic_fallback"
    && activity.warning_code === "specialist_materialization_fallback";
  const hasActivityContent = Boolean(body)
    || showTextLoader
    || activity.status === "failed"
    || fallbackWarning;

  return (
    <section
      className={`agent-chat__activity is-${activity.status}${compact ? " is-compact" : ""}`}
      role="status"
      aria-label={activityAriaLabel(activity.capability_display_name, stage)}
    >
      <header className="agent-chat__activity-header">
        {compact ? (
          <div className="agent-chat__compact-capability-heading">
            <strong>{activity.capability_display_name}</strong>
            <span>{stage}</span>
          </div>
        ) : (
          <AgentCapabilityIdentity
            capabilityId={activity.capability_id}
            displayName={activity.capability_display_name}
            detail={stage}
          />
        )}
        {duration ? <time>{duration}</time> : null}
      </header>
      {hasActivityContent ? (
        <div className="agent-chat__activity-content">
          {body ? <p>{body}</p> : null}
          {showTextLoader ? (
            <TextLoader
              text="Preparing the next response..."
              variant="skeleton"
              className="agent-chat__activity-loader"
              aria-label={`${activity.capability_display_name} is preparing the next response`}
            />
          ) : null}
          {activity.status === "failed" ? (
            <>
              <small>This step could not be completed.</small>
              {technicalFailure ? (
                <details open={technicalDetailsOpen}>
                  <summary
                    onClick={(event) => {
                      event.preventDefault();
                      setTechnicalDetailsOpen((current) => !current);
                    }}
                  >
                    Technical details
                  </summary>
                  {technicalDetailsOpen ? <code>{technicalFailure}</code> : null}
                </details>
              ) : null}
              <div className="agent-chat__activity-actions">
                {retryable && onRetry ? (
                  <button
                    type="button"
                    aria-label={`Retry ${activity.capability_display_name} activity`}
                    onClick={onRetry}
                    disabled={retrying}
                  >
                    {retrying ? "Retrying" : "Retry"}
                  </button>
                ) : null}
                {activity.suggested_actions.includes("revise_request") && onReviseRequest ? (
                  <button
                    type="button"
                    aria-label={`Revise ${activity.capability_display_name} request`}
                    onClick={onReviseRequest}
                  >
                    Revise request
                  </button>
                ) : null}
              </div>
            </>
          ) : null}
          {fallbackWarning ? (
            <small className="agent-chat__activity-warning">
              Draft created with a simplified fallback.
            </small>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
