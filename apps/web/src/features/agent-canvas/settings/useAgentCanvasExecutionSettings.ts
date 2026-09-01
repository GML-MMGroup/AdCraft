import { useCallback, useEffect, useRef, useState } from "react";

import { agentCanvasApi, isV2ApiError } from "../../../api/agentCanvasApi.ts";
import type {
  AgentExecutionSettingsV2,
  AgentMediaExecutionModeV2,
} from "../../../types-v2.ts";

type SettingsConflict = {
  desiredMode: AgentMediaExecutionModeV2;
  message: string;
};

type SettingsRead = ReturnType<typeof agentCanvasApi.agentCanvasExecutionSettings>;

const executionSettingsReads = new Map<string, {
  promise: SettingsRead;
  expiresAt: number;
}>();

function readExecutionSettings(workflowId: string, force = false): SettingsRead {
  const existing = executionSettingsReads.get(workflowId);
  if (!force && existing && (existing.expiresAt === 0 || existing.expiresAt > Date.now())) {
    return existing.promise;
  }
  if (force) executionSettingsReads.delete(workflowId);
  const promise = agentCanvasApi.agentCanvasExecutionSettings(workflowId);
  executionSettingsReads.set(workflowId, { promise, expiresAt: 0 });
  void promise.then(() => {
    const current = executionSettingsReads.get(workflowId);
    if (current?.promise === promise) current.expiresAt = Date.now() + 1000;
  }).catch(() => {
    if (executionSettingsReads.get(workflowId)?.promise === promise) {
      executionSettingsReads.delete(workflowId);
    }
  });
  return promise;
}

export function __resetExecutionSettingsReadsForTests() {
  executionSettingsReads.clear();
}

function errorMessage(error: unknown): string {
  if (isV2ApiError(error)) {
    if (error.code === "agent_settings_precondition_required") {
      return "The current execution setting must be reloaded before it can be changed.";
    }
    if (error.code === "agent_execution_mode_invalid") {
      return "The selected execution mode is not supported.";
    }
    if (error.code === "workflow_not_found") return "This workflow no longer exists.";
    if (error.code === "workflow_not_agent_canvas") return "Execution mode is unavailable for this workflow.";
  }
  return error instanceof Error && error.message.trim()
    ? error.message
    : "Execution mode could not be updated.";
}

export function useAgentCanvasExecutionSettings(
  workflowId: string,
  eventRevision: number,
) {
  const [settings, setSettings] = useState<AgentExecutionSettingsV2 | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<SettingsConflict | null>(null);
  const activeWorkflowIdRef = useRef(workflowId);
  activeWorkflowIdRef.current = workflowId;

  const load = useCallback(async ({ force = false }: { force?: boolean } = {}) => {
    setLoading(true);
    try {
      const response = await readExecutionSettings(workflowId, force);
      if (activeWorkflowIdRef.current !== workflowId) return null;
      setSettings(response.value);
      setError(null);
      return response.value;
    } catch (loadError) {
      if (activeWorkflowIdRef.current === workflowId) setError(errorMessage(loadError));
      return null;
    } finally {
      if (activeWorkflowIdRef.current === workflowId) setLoading(false);
    }
  }, [workflowId]);

  useEffect(() => {
    setSettings(null);
    setConflict(null);
    setError(null);
    void load({ force: eventRevision > 0 });
  }, [eventRevision, load]);

  const commitMode = useCallback(async (
    desiredMode: AgentMediaExecutionModeV2,
    current: AgentExecutionSettingsV2,
  ) => {
    if (saving) return;
    setSaving(true);
    setError(null);
    setConflict(null);
    setSettings({ ...current, media_execution_mode: desiredMode });
    try {
      const response = await agentCanvasApi.patchAgentCanvasExecutionSettings(
        workflowId,
        { media_execution_mode: desiredMode },
        current.revision,
      );
      if (activeWorkflowIdRef.current === workflowId) setSettings(response.value);
    } catch (updateError) {
      if (activeWorkflowIdRef.current !== workflowId) return;
      if (
        isV2ApiError(updateError)
        && (updateError.status === 412 || updateError.status === 428)
      ) {
        const latest = await load({ force: true });
        setConflict({
          desiredMode,
          message: updateError.status === 412
            ? "Execution mode changed in another session. Review the current value, then retry."
            : "Execution mode was reloaded because its revision was missing. Retry the change explicitly.",
        });
        if (!latest) setSettings(current);
      } else {
        setSettings(current);
        setError(errorMessage(updateError));
      }
    } finally {
      if (activeWorkflowIdRef.current === workflowId) setSaving(false);
    }
  }, [load, saving, workflowId]);

  const setMode = useCallback(async (mode: AgentMediaExecutionModeV2) => {
    if (!settings || settings.media_execution_mode === mode) return;
    await commitMode(mode, settings);
  }, [commitMode, settings]);

  const retryConflict = useCallback(async () => {
    if (!conflict || !settings) return;
    await commitMode(conflict.desiredMode, settings);
  }, [commitMode, conflict, settings]);

  return {
    settings,
    loading,
    saving,
    error,
    conflict,
    setMode,
    retryConflict,
    dismissConflict: () => setConflict(null),
  };
}
