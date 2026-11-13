import { useState } from "react";
import { useUiLocale } from "../../../i18n/locale.tsx";
import { useTranslation } from "../../../i18n/useTranslation.ts";
import type { UiMessageKey } from "../../../i18n/uiMessages.ts";

import type {
  AgentCanvasChatTurnV2,
  ChatCapabilityActivityV2,
} from "../../../types-v2.ts";
import { AgentCapabilityIdentity } from "./AgentCapabilityIdentity.tsx";
import {
  activityActionableFailure,
  canRetryFailureInScope,
  failureUserAction,
} from "./actionableFailure.ts";
import { resolveAgentRoleMotionState } from "./agent-role-animation/resolveAgentRoleMotionState.ts";
import { capabilityDisplayName } from "./capabilityDisplayName.ts";

const SCRIPT_COMPLETION_MESSAGES: Record<string, UiMessageKey> = {
  narrative_direction: "Narrative design completed",
  style_lock: "Style setting completed",
  storyboard_plan: "Storyboard planning completed",
};

function recoveryStageLabel(stage: string | null | undefined): UiMessageKey | null {
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
): UiMessageKey {
  if (retrying) return "Retrying";
  if (activity.status === "completed") return "Completed";
  if (activity.status === "failed") return "Failed";
  if (activity.status === "superseded") return "Superseded";
  return recoveryStageLabel(turn?.operation_stage)
    ?? "Working";
}

function activityAriaLabel(capabilityName: string, stage: string): string {
  return stage === "Working"
    ? `${capabilityName} is working`
    : `${capabilityName} ${stage.toLowerCase()}`;
}

function normalizedStatusText(value: string): string {
  return value
    .trim()
    .replace(/[.!?。！？]+$/g, "")
    .replace(/\s+/g, " ")
    .toLocaleLowerCase();
}

function isRedundantActivityText(
  activity: ChatCapabilityActivityV2,
  body: string | null,
  displayName: string,
): boolean {
  if (!body?.trim() || !["working", "completed"].includes(activity.status)) return false;
  const normalizedBody = normalizedStatusText(body);
  const names = [activity.capability_display_name.trim(), displayName.trim()].flatMap(name => [
    name,
    capabilityDisplayName(activity.capability_id, name, "en-US"),
    capabilityDisplayName(activity.capability_id, name, "zh-CN"),
  ]);
  const aliases = new Set(names.flatMap(name => [name, name.replace(/\s+(designer|artist|director|writer|author)$/i, "").trim()])
    .map(normalizedStatusText));
  const suffixes = activity.status === "completed"
    ? ["已完成", "finished", "completed", "is complete", "complete"]
    : ["正在工作", "正在工作中", "工作中", "处理中", "is working", "working"];
  return (activity.status === "working" && normalizedBody === "preparing the next response")
    || [...aliases].some(name => suffixes.some(suffix => (
      normalizedBody === `${name} ${suffix}` || normalizedBody === `${name}${suffix}`
    )));
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
  displayName = activity.capability_display_name,
  turn,
  retrying = false,
  compact = false,
  onRetry,
  onReviseRequest,
}: {
  activity: ChatCapabilityActivityV2;
  displayName?: string;
  turn?: AgentCanvasChatTurnV2 | null;
  retrying?: boolean;
  compact?: boolean;
  onRetry?: () => void;
  onReviseRequest?: () => void;
}) {
  const t = useTranslation();
  const locale = useUiLocale();
  const completionMessage = activity.capability_id === "script_authoring" && activity.status === "completed" && !retrying
    ? SCRIPT_COMPLETION_MESSAGES[activity.journey_stage ?? ""] : undefined;
  const name = completionMessage
    ? t(completionMessage)
    : capabilityDisplayName(activity.capability_id, displayName, locale);
  const [technicalDetailsOpen, setTechnicalDetailsOpen] = useState(false);
  const actionableFailure = activityActionableFailure(activity, turn);
  const retryable = canRetryFailureInScope(actionableFailure, "turn");
  const canRevise = failureUserAction(actionableFailure) === "revise";
  const errorCode = turn?.operation_failure?.code ?? activity.error_code;
  const errorMessage = turn?.operation_failure?.message ?? activity.message;
  const stage = activityStageLabel(activity, turn, retrying);
  const stageLabel = completionMessage ? null : t(stage);
  const duration = formatActivityDuration(activity.elapsed_ms);
  const rawBody = activity.presentation_text
    ?? (activity.status === "superseded"
      ? `${activity.capability_display_name} was superseded by later progress`
      : activity.status === "completed" ? activity.message : null);
  const body = isRedundantActivityText(activity, rawBody, displayName) ? null : rawBody;
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
    || activity.status === "failed"
    || fallbackWarning;

  return (
    <section
      className={`agent-chat__activity is-${activity.status}${compact ? " is-compact" : ""}`}
      role="status"
      aria-label={completionMessage ? name : locale.startsWith("zh") ? `${name} ${stageLabel}` : activityAriaLabel(name, stage)}
    >
      <header className="agent-chat__activity-header">
        {compact ? (
          <div className="agent-chat__compact-capability-heading">
            <strong>{name}</strong>
            {stageLabel ? <> <span>{stageLabel}</span></> : null}
          </div>
        ) : (
          <AgentCapabilityIdentity
            capabilityId={activity.capability_id}
            displayName={displayName}
            label={name}
            detail={stageLabel}
            motionState={resolveAgentRoleMotionState({
              status: activity.status,
              turnId: activity.turn_id,
              turn,
            })}
          />
        )}
        {duration ? <time>{duration}</time> : null}
      </header>
      {hasActivityContent ? (
        <div className="agent-chat__activity-content">
          {body ? <p>{body}</p> : null}
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
                    aria-label={`Retry ${displayName} activity`}
                    onClick={onRetry}
                    disabled={retrying}
                  >
                    {retrying ? "Retrying" : "Retry"}
                  </button>
                ) : null}
                {canRevise && onReviseRequest ? (
                  <button
                    type="button"
                    aria-label={`Revise ${displayName} request`}
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
