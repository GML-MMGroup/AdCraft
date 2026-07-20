import { useCallback, useEffect, useState } from "react";
import { v2Api } from "../../../../api/v2Client.ts";
import type { ProviderTaskV2 } from "../../../../types-v2.ts";

type V2ProviderTaskPanelProps = {
  workflowId: string;
  slotId?: string | null;
  taskId?: string | null;
  isWaiting: boolean;
  refreshSignal?: number;
  onTerminalRefresh: () => Promise<void> | void;
};

export function V2ProviderTaskPanel({ workflowId, slotId, taskId, isWaiting, refreshSignal = 0, onTerminalRefresh }: V2ProviderTaskPanelProps) {
  const [tasks, setTasks] = useState<ProviderTaskV2[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const listedTasks = await v2Api.listProviderTasks(workflowId, { slot_id: slotId ?? null });
      const explicitTask = taskId && !listedTasks.some((task) => task.task_id === taskId)
        ? await v2Api.providerTask(workflowId, taskId)
        : null;
      setTasks(explicitTask ? [...listedTasks, explicitTask] : listedTasks);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Provider task refresh failed");
    }
  }, [slotId, taskId, workflowId]);

  const poll = useCallback(async (task: ProviderTaskV2) => {
    setError(null);
    try {
      const nextTask = await v2Api.pollProviderTask(workflowId, task.task_id);
      setTasks((current) => upsertTask(current, nextTask));
      if (nextTask.status === "completed" || nextTask.status === "failed" || nextTask.status === "cancelled") {
        await onTerminalRefresh();
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Provider task poll failed");
    }
  }, [onTerminalRefresh, workflowId]);

  useEffect(() => {
    if (isWaiting || taskId) void refresh();
  }, [isWaiting, refresh, refreshSignal, taskId]);

  if (!isWaiting && !tasks.length && !taskId) return null;

  return (
    <details className="v2-provider-task-panel">
      <summary>{isWaiting ? "Waiting for provider" : "Provider tasks"}</summary>
      <button type="button" onClick={() => void refresh()}>
        Refresh provider status
      </button>
      {tasks.map((task) => (
        <article key={task.task_id} className="v2-provider-task">
          <p>Provider task id: {task.task_id}</p>
          {task.remote_task_id ? <p>Remote task id: {task.remote_task_id}</p> : null}
          {task.provider ? <p>Provider: {task.provider}</p> : null}
          {task.provider_model ? <p>Provider model: {task.provider_model}</p> : null}
          <p>Provider status: {task.status}</p>
          {task.last_error_code ? <p>{task.last_error_code}</p> : null}
          {task.last_error_message ? <p>{task.last_error_message}</p> : null}
          {task.provider_payload_snapshot ? <pre>{JSON.stringify(task.provider_payload_snapshot, null, 2)}</pre> : null}
          <button type="button" onClick={() => void poll(task)}>
            Poll provider task
          </button>
        </article>
      ))}
      {error ? <p className="v2-provider-task-error">{error}</p> : null}
    </details>
  );
}

function upsertTask(tasks: ProviderTaskV2[], nextTask: ProviderTaskV2) {
  const found = tasks.some((task) => task.task_id === nextTask.task_id);
  return found ? tasks.map((task) => task.task_id === nextTask.task_id ? nextTask : task) : [...tasks, nextTask];
}
