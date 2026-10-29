import { useCallback, useEffect, useLayoutEffect, useMemo, useReducer } from "react";
import { agentCanvasApi, isV2ApiError } from "../../../api/agentCanvasApi.ts";
import { createOperationKey } from "../../../api/operationKey.ts";
import { useTranslation } from "../../../i18n/useTranslation.ts";
import type { AgentCanvasWorkflowV2, CanvasBindingV2, CanvasLayoutPositionV2 } from "../../../types-v2.ts";
import type { AgentCanvasAuthoringQueue } from "../session/authoringQueue.ts";
import {
  bindingEndpointsLive, bindingRestoreRequest, canvasHistoryReducer, createCanvasHistory,
  isCanvasHistoryEntryValid, type CanvasHistoryAction, type CanvasHistoryDirection, type CanvasHistoryEntry,
} from "./canvasHistory.ts";

type Options = {
  workflowId: string | null;
  readWorkflow: () => AgentCanvasWorkflowV2 | null;
  applyWorkflow: (workflow: AgentCanvasWorkflowV2) => void;
  authoringQueue: AgentCanvasAuthoringQueue;
  updateNodePositions: (positions: CanvasLayoutPositionV2[]) => Promise<void>;
  rollbackNodePositions: (workflowId: string, positions: CanvasLayoutPositionV2[]) => void;
};
type DeletionBatch = { nodeIds: Set<string>; bindingIds: Set<string>; promise: Promise<void> };
type Replay = { entry: CanvasHistoryEntry; direction: CanvasHistoryDirection; completed: Set<string> };
class AgentPromptWritingError extends Error {}
class InactiveHistoryError extends Error {}
const caller = { conflictHandling: "caller" } as const;

export function useAgentCanvasHistory({ workflowId, readWorkflow, applyWorkflow, authoringQueue, updateNodePositions, rollbackNodePositions }: Options) {
  const t = useTranslation();
  const [, render] = useReducer((value: number) => value + 1, 0);
  const scope = useMemo(() => ({
    state: createCanvasHistory(workflowId), active: true, busy: false,
    deletion: null as DeletionBatch | null, replay: null as Replay | null,
    notice: null as string | null, noticeSequence: 0,
  }), [workflowId]);
  const isCurrent = useCallback(() => scope.active && workflowId !== null && readWorkflow()?.workflow_id === workflowId, [readWorkflow, scope, workflowId]);
  const dispatch = useCallback((action: CanvasHistoryAction) => {
    if (!isCurrent()) return;
    scope.state = canvasHistoryReducer(scope.state, action);
    render();
  }, [isCurrent, scope]);
  const record = useCallback((entry: CanvasHistoryEntry) => {
    dispatch({ type: "record", entry: structuredClone(entry) });
  }, [dispatch]);
  const clearNotice = useCallback(() => {
    scope.notice = null;
    if (scope.active) render();
  }, [scope]);
  useLayoutEffect(() => {
    scope.active = true;
    return () => {
      scope.active = false;
      scope.state = createCanvasHistory(workflowId);
      scope.replay = null;
    };
  }, [scope, workflowId]);
  const noticeSequence = scope.noticeSequence;
  useEffect(() => {
    if (!scope.notice) return;
    const timer = window.setTimeout(clearNotice, 5000);
    return () => window.clearTimeout(timer);
  }, [clearNotice, scope, noticeSequence]);

  const replay = useCallback(async (direction: CanvasHistoryDirection) => {
    if (!isCurrent() || scope.busy || !scope.state[direction].length) return;
    scope.busy = true;
    render();
    try {
      await authoringQueue.enqueue(createOperationKey(`history-${direction}`), async () => {
        if (!isCurrent()) return;
        const entry = scope.state[direction].at(-1);
        if (!entry) return;
        let current = readWorkflow()!;
        const progress = scope.replay?.entry === entry && scope.replay.direction === direction
          ? scope.replay : { entry, direction, completed: new Set<string>() };
        if (!isCanvasHistoryEntryValid(entry, direction, current, progress.completed)) {
          dispatch({ type: "drop", direction });
          scope.replay = null;
          scope.notice = t("The canvas changed since this step, so it can't be undone.");
          scope.noticeSequence += 1;
          return;
        }
        scope.replay = progress;
        const assertCurrent = () => { if (!isCurrent()) throw new InactiveHistoryError(); };
        const apply = (workflow: AgentCanvasWorkflowV2) => {
          assertCurrent();
          current = workflow;
          applyWorkflow(workflow);
        };
        const retry = async <T,>(operation: () => Promise<T>): Promise<T> => {
          assertCurrent();
          try { return await operation(); } catch (error) {
            if (!isV2ApiError(error) || (error.status !== 412 && error.status !== 428)) throw error;
            assertCurrent();
            apply((await agentCanvasApi.agentCanvasWorkflowWithEtag(workflowId!)).value);
            return operation();
          }
        };
        const removeNode = async (id: string) => {
          apply((await retry(() => agentCanvasApi.deleteAgentCanvasNode(workflowId!, id, caller))).value.workflow);
          if (current.nodes.some((node) => node.node_id === id)) throw new Error("Node deletion was skipped.");
        };
        const restoreNode = async (id: string) => {
          const key = createOperationKey("history-restore-node");
          apply((await retry(() => agentCanvasApi.restoreAgentCanvasNode(workflowId!, id, key, caller))).value.workflow);
        };
        const removeBinding = async (id: string) => {
          apply((await retry(() => agentCanvasApi.deleteAgentCanvasBinding(workflowId!, id, caller))).value.workflow);
          if (current.bindings.some((binding) => binding.binding_id === id)) throw new AgentPromptWritingError();
        };
        const restoreBinding = async (binding: CanvasBindingV2) => {
          const request = bindingRestoreRequest(binding);
          if (!request || current.bindings.some((item) => item.binding_id === binding.binding_id) || !bindingEndpointsLive(binding, current)) return;
          const key = createOperationKey("history-restore-binding");
          apply((await retry(() => agentCanvasApi.restoreAgentCanvasBinding(workflowId!, request, key, caller))).value.workflow);
        };
        try {
          switch (entry.kind) {
            case "create":
              if (direction === "undo") await removeNode(entry.node_id);
              else await restoreNode(entry.node_id);
              break;
            case "delete":
              for (const id of entry.node_ids) {
                if (progress.completed.has(`node:${id}`)) continue;
                if (direction === "undo") await restoreNode(id);
                else await removeNode(id);
                progress.completed.add(`node:${id}`);
              }
              for (const binding of entry.bindings) {
                if (progress.completed.has(`binding:${binding.binding_id}`)) continue;
                if (direction === "undo") await restoreBinding(binding);
                else if (current.bindings.some((item) => item.binding_id === binding.binding_id)) await removeBinding(binding.binding_id);
                progress.completed.add(`binding:${binding.binding_id}`);
              }
              break;
            case "move":
              await retry(() => updateNodePositions(direction === "undo" ? entry.before : entry.after));
              break;
            case "connect":
            case "disconnect":
              if ((entry.kind === "connect") === (direction === "undo")) await removeBinding(entry.binding.binding_id);
              else await restoreBinding(entry.binding);
              break;
          }
          assertCurrent();
          dispatch({ type: direction });
          scope.replay = null;
          scope.notice = null;
        } catch (error) {
          if (!isCurrent()) return;
          if (entry.kind === "move") {
            const movedIds = new Set(entry.before.map((position) => position.node_id));
            rollbackNodePositions(workflowId!, current.nodes
              .filter((node) => movedIds.has(node.node_id))
              .map((node) => ({ node_id: node.node_id, ...node.position })));
          }
          scope.notice = error instanceof AgentPromptWritingError
            ? t("The Agent is writing this node's prompt; try again shortly.")
            : t("Undo failed. Please try again.");
          scope.noticeSequence += 1;
        }
      });
    } finally {
      scope.busy = false;
      if (scope.active) render();
    }
  }, [applyWorkflow, authoringQueue, dispatch, isCurrent, readWorkflow, rollbackNodePositions, scope, t, updateNodePositions, workflowId]);

  // Xyflow invokes onEdgesDelete before onNodesDelete in the same tick. Reserve
  // the authoring queue immediately, then collect the entire gesture before any
  // DELETE is sent so its server snapshots cannot be lost between callbacks.
  const deleteEntities = useCallback((nodeIds: string[], bindingIds: string[]): Promise<void> => {
    if (!isCurrent()) return Promise.resolve();
    if (!scope.deletion) {
      let release!: () => void;
      const ready = new Promise<void>((resolve) => { release = resolve; });
      const batch: DeletionBatch = { nodeIds: new Set(), bindingIds: new Set(), promise: Promise.resolve() };
      scope.deletion = batch;
      batch.promise = authoringQueue.enqueue(createOperationKey("delete-canvas-gesture"), async () => {
        await ready;
        if (!isCurrent()) return;
        const before = readWorkflow()!;
        let current = before;
        const removedNodeIds: string[] = [];
        const apply = (workflow: AgentCanvasWorkflowV2) => {
          current = workflow;
          if (isCurrent()) applyWorkflow(workflow);
        };
        try {
          for (const id of batch.bindingIds) {
            if (!isCurrent()) return;
            if (!current.bindings.some((binding) => binding.binding_id === id)) continue;
            apply((await agentCanvasApi.deleteAgentCanvasBinding(workflowId!, id)).value.workflow);
          }
          for (const id of batch.nodeIds) {
            if (!isCurrent()) return;
            if (!current.nodes.some((node) => node.node_id === id)) continue;
            apply((await agentCanvasApi.deleteAgentCanvasNode(workflowId!, id)).value.workflow);
            if (!current.nodes.some((node) => node.node_id === id)) removedNodeIds.push(id);
          }
        } finally {
          const removedBindings = before.bindings.filter((binding) => (
            batch.bindingIds.has(binding.binding_id) || removedNodeIds.includes(binding.target_node_id)
            || (binding.source.kind === "node_output" && removedNodeIds.includes(binding.source.source_node_id))
          ) && !current.bindings.some((item) => item.binding_id === binding.binding_id));
          if (removedNodeIds.length) record({ kind: "delete", node_ids: removedNodeIds, bindings: removedBindings });
          else {
            const restorable = removedBindings.filter((binding) => bindingRestoreRequest(binding) !== null);
            if (restorable.length === 1) record({ kind: "disconnect", binding: restorable[0] });
            else if (restorable.length) record({ kind: "delete", node_ids: [], bindings: restorable });
          }
        }
      });
      queueMicrotask(() => {
        if (scope.deletion === batch) scope.deletion = null;
        release();
      });
    }
    nodeIds.forEach((id) => scope.deletion!.nodeIds.add(id));
    bindingIds.forEach((id) => scope.deletion!.bindingIds.add(id));
    return scope.deletion.promise;
  }, [applyWorkflow, authoringQueue, isCurrent, readWorkflow, record, scope, workflowId]);

  const moveNodes = useCallback((before: CanvasLayoutPositionV2[], after: CanvasLayoutPositionV2[]) => {
    const changed = after.filter((position) => before.some((previous) => previous.node_id === position.node_id && (previous.x !== position.x || previous.y !== position.y)));
    if (!changed.length || !isCurrent()) return Promise.resolve();
    return authoringQueue.enqueue(createOperationKey("move-canvas-nodes"), async () => {
      if (!isCurrent()) return;
      await updateNodePositions(changed);
      if (!isCurrent()) return;
      const committed = readWorkflow()!.nodes
        .filter((node) => changed.some((position) => position.node_id === node.node_id))
        .map((node) => ({ node_id: node.node_id, ...node.position }));
      if (committed.length !== changed.length) return;
      record({ kind: "move", before: before.filter((position) => changed.some((item) => item.node_id === position.node_id)), after: committed });
    });
  }, [authoringQueue, isCurrent, readWorkflow, record, updateNodePositions]);
  const undo = useCallback(() => replay("undo"), [replay]);
  const redo = useCallback(() => replay("redo"), [replay]);
  return { state: scope.state, get busy() { return scope.busy; }, notice: scope.notice, clearNotice, record, deleteEntities, moveNodes, undo, redo };
}
