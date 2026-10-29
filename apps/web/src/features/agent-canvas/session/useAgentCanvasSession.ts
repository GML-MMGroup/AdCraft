import { useCallback, useMemo, useRef, useState } from "react";

import { agentCanvasApi } from "../../../api/agentCanvasApi.ts";
import { createOperationKey } from "../../../api/operationKey.ts";
import { useApp } from "../../../AppContextValue.ts";
import type {
  AgentActionReceiptV2,
  AgentCanvasWorkflowV2,
  CanvasBindingCreateRequestV2,
  CanvasBindingPatchRequestV2,
  CanvasConnectedNodeCreateRequestV2,
  CanvasEditingExportImportRequestV2,
  CanvasLayoutPatchResponseV2,
  CanvasLayoutPositionV2,
  CanvasNodeCreateRequestV2,
  CanvasNodePatchRequestV2,
  CanvasNodeV2,
  CanvasPositionV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import { buildAgentCanvasPreRevealLayout } from "../canvas/agentCanvasPreRevealLayout.ts";
import { useAgentCanvasHistory } from "../history/useAgentCanvasHistory.ts";
import { AgentCanvasAuthoringQueue } from "./authoringQueue.ts";
import { assertValidCanvasBindingWrite } from "./bindingWriteValidation.ts";
import { persistAgentCanvasLayout } from "./layoutPersistence.ts";
import { persistAgentCanvasLayoutPreview } from "./layoutPreviewPersistence.ts";
import { AgentCanvasLayoutQueue } from "./layoutQueue.ts";
import {
  mergeAgentCanvasLayout,
  mergeAgentCanvasBindingMutation,
  mergeAgentCanvasConnectedNode,
  mergeAgentCanvasEditingExportImport,
  mergeExistingAgentCanvasNode,
  mergeAgentCanvasWorkflow,
  overlayAgentCanvasPositions,
} from "./workflowMerge.ts";

function withNodePatch(
  workflow: AgentCanvasWorkflowV2,
  nodeId: string,
  patch: CanvasNodePatchRequestV2,
): AgentCanvasWorkflowV2 {
  return {
    ...workflow,
    nodes: workflow.nodes.map((node) => node.node_id === nodeId
      ? {
          ...node,
          ...(patch.title !== undefined && patch.title !== null ? { title: patch.title } : {}),
          ...(patch.summary_prompt !== undefined ? { summary_prompt: patch.summary_prompt } : {}),
          ...(patch.generation_prompt !== undefined ? { generation_prompt: patch.generation_prompt } : {}),
          ...(patch.structured_content !== undefined && patch.structured_content !== null
            ? { structured_content: patch.structured_content }
            : {}),
          ...(patch.model_selection_mode !== undefined
            ? { model_selection_mode: patch.model_selection_mode }
            : {}),
          ...(patch.model_ref !== undefined ? { model_ref: patch.model_ref } : {}),
          ...(patch.parameters !== undefined && patch.parameters !== null
            ? { parameters: patch.parameters }
            : {}),
          ...(patch.position ? { position: patch.position } : {}),
        }
      : node),
  };
}

export function useAgentCanvasSession() {
  const {
    agentCanvasWorkflow,
    setAgentCanvasWorkflow,
    workspaceHydrated,
    workspaceRestoreError,
  } = useApp();
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [authoringError, setAuthoringError] = useState<string | null>(null);
  const workflowRef = useRef(agentCanvasWorkflow);
  workflowRef.current = agentCanvasWorkflow;
  const queueRef = useRef<AgentCanvasAuthoringQueue | null>(null);
  const flushLayoutRef = useRef<(
    workflowId: string,
    positions: CanvasLayoutPositionV2[],
  ) => Promise<void>>(
    async () => {},
  );
  const layoutQueuesRef = useRef(new Map<string, AgentCanvasLayoutQueue>());
  const pendingLayoutPositionsRef = useRef(
    new Map<string, Map<string, CanvasLayoutPositionV2>>(),
  );
  const editingExportImportKeysRef = useRef(new Map<string, string>());
  // Queue tasks can finish before React commits a render. Keep the session read
  // reference current immediately, while retaining functional state merges for
  // runtime updates that React may already have queued.
  const updateWorkflow = useCallback((
    update: (current: AgentCanvasWorkflowV2 | null) => AgentCanvasWorkflowV2 | null,
  ) => {
    workflowRef.current = update(workflowRef.current);
    setAgentCanvasWorkflow((current) => {
      const next = update(current);
      workflowRef.current = next;
      return next;
    });
  }, [setAgentCanvasWorkflow]);
  const layoutQueueForWorkflow = useCallback((workflowId: string) => {
    let layoutQueue = layoutQueuesRef.current.get(workflowId);
    if (!layoutQueue) {
      layoutQueue = new AgentCanvasLayoutQueue(
        (batch) => flushLayoutRef.current(workflowId, batch),
      );
      layoutQueuesRef.current.set(workflowId, layoutQueue);
    }
    return layoutQueue;
  }, []);
  if (!queueRef.current) {
    queueRef.current = new AgentCanvasAuthoringQueue({
      onError(error) {
        setAuthoringError(error instanceof Error ? error.message : "Canvas update failed.");
      },
    });
  }
  const applyWorkflow = useCallback((next: AgentCanvasWorkflowV2) => {
    updateWorkflow((current) => {
      const merged = mergeAgentCanvasWorkflow(current, next);
      const pending = Array.from(
        pendingLayoutPositionsRef.current.get(merged.workflow_id)?.values() ?? [],
      );
      const withPending = overlayAgentCanvasPositions(merged, pending);
      return withPending;
    });
  }, [updateWorkflow]);

  const applyLayout = useCallback((
    response: CanvasLayoutPatchResponseV2,
    committedPositions: CanvasLayoutPositionV2[],
  ) => {
    const pendingByNode = pendingLayoutPositionsRef.current.get(response.workflow_id);
    committedPositions.forEach((committed) => {
      const pending = pendingByNode?.get(committed.node_id);
      if (pending && pending.x === committed.x && pending.y === committed.y) {
        pendingByNode?.delete(committed.node_id);
      }
    });
    if (pendingByNode && !pendingByNode.size) {
      pendingLayoutPositionsRef.current.delete(response.workflow_id);
    }
    const remainingPending = Array.from(pendingByNode?.values() ?? []);
    updateWorkflow((current) => {
      if (!current || current.workflow_id !== response.workflow_id) return current;
      const merged = mergeAgentCanvasLayout(current, response);
      const next = overlayAgentCanvasPositions(
        merged,
        remainingPending,
      );
      return next;
    });
  }, [updateWorkflow]);

  flushLayoutRef.current = async (workflowId, positions) => {
    const assertActiveWorkflow = () => {
      const current = workflowRef.current;
      if (!current || current.workflow_id !== workflowId) {
        throw new Error("The active Agent Canvas workflow changed before its layout was saved.");
      }
      return current;
    };
    await persistAgentCanvasLayout({
      workflowId,
      positions,
      readWorkflow: assertActiveWorkflow,
      loadWorkflow: async () => {
        assertActiveWorkflow();
        return (await agentCanvasApi.agentCanvasWorkflowWithEtag(workflowId)).value;
      },
      patchLayout: (request) => {
        assertActiveWorkflow();
        return agentCanvasApi.patchAgentCanvasLayout(workflowId, request, { conflictHandling: "caller" });
      },
      applyWorkflow,
      applyLayout: (response) => applyLayout(response, positions),
    });
    if (workflowRef.current?.workflow_id === workflowId) {
      setAuthoringError(null);
    }
  };

  const readWorkflow = useCallback(() => workflowRef.current, []);

  const patchNode = useCallback((
    nodeId: string,
    patch: CanvasNodePatchRequestV2,
    options: { coalesce?: boolean; optimistic?: boolean; expectedNodeRevision?: number; onSaved?: (node: CanvasNodeV2) => void } = {},
  ) => {
    if (!agentCanvasWorkflow) return Promise.reject(new Error("No active Agent Canvas workflow."));
    if (options.optimistic) {
      updateWorkflow((current) => current
        ? withNodePatch(current, nodeId, patch)
        : current);
    }
    const workflowId = agentCanvasWorkflow.workflow_id;
    return queueRef.current!.enqueue(
      options.coalesce ? `patch:${nodeId}` : createOperationKey(`patch:${nodeId}`),
      async () => {
        const current = workflowRef.current;
        if (!current || current.workflow_id !== workflowId) {
          throw new Error("The active Agent Canvas workflow changed before its node was saved.");
        }
        const node = current.nodes.find((item) => item.node_id === nodeId);
        const response = await agentCanvasApi.patchAgentCanvasNode(workflowId, nodeId, patch, {
          expectedNodeRevision: options.expectedNodeRevision ?? node?.revision,
        });
        applyWorkflow(response.value.workflow);
        if (response.value.node) options.onSaved?.(response.value.node);
        setAuthoringError(null);
      },
      { coalesce: options.coalesce },
    );
  }, [agentCanvasWorkflow, applyWorkflow, updateWorkflow]);

  const updateNodePositions = useCallback((positions: CanvasLayoutPositionV2[]) => {
    if (!positions.length) return Promise.resolve();
    const active = workflowRef.current;
    if (!active) return Promise.reject(new Error("No active Agent Canvas workflow."));
    const workflowId = active.workflow_id;
    const pendingByNode = pendingLayoutPositionsRef.current.get(workflowId)
      ?? new Map<string, CanvasLayoutPositionV2>();
    positions.forEach((position) => pendingByNode.set(position.node_id, position));
    pendingLayoutPositionsRef.current.set(workflowId, pendingByNode);
    updateWorkflow((current) => {
      if (!current || current.workflow_id !== workflowId) return current;
      const next = overlayAgentCanvasPositions(current, positions);
      return next;
    });
    const layoutQueue = layoutQueueForWorkflow(workflowId);
    return layoutQueue.enqueue(positions).catch((error) => {
      const currentPending = pendingLayoutPositionsRef.current.get(workflowId);
      positions.forEach((position) => {
        const pending = currentPending?.get(position.node_id);
        if (pending && pending.x === position.x && pending.y === position.y) {
          currentPending?.delete(position.node_id);
        }
      });
      if (currentPending && !currentPending.size) {
        pendingLayoutPositionsRef.current.delete(workflowId);
      }
      setAuthoringError(error instanceof Error ? error.message : "Canvas layout could not be saved.");
      throw error;
    });
  }, [layoutQueueForWorkflow, updateWorkflow]);

  const updateNodePosition = useCallback((nodeId: string, position: CanvasPositionV2) => (
    updateNodePositions([{ node_id: nodeId, ...position }])
  ), [updateNodePositions]);

  const persistLayoutPreviewPositions = useCallback((
    workflow: AgentCanvasWorkflowV2,
    targetPositions: CanvasLayoutPositionV2[],
    originalPositions: CanvasLayoutPositionV2[],
  ) => {
    const workflowId = workflow.workflow_id;
    return layoutQueueForWorkflow(workflowId).runExclusive(() => (
      persistAgentCanvasLayoutPreview({
        workflow,
        targetPositions,
        originalPositions,
        loadWorkflow: async (scopedWorkflowId) => (
          await agentCanvasApi.agentCanvasWorkflowWithEtag(scopedWorkflowId)
        ).value,
        patchLayout: (scopedWorkflowId, request) => (
          agentCanvasApi.patchAgentCanvasLayout(scopedWorkflowId, request)
        ),
        applyWorkflow: (next) => {
          updateWorkflow((current) => {
            if (!current || current.workflow_id !== next.workflow_id) return current;
            const merged = mergeAgentCanvasWorkflow(current, next);
            return merged;
          });
        },
        applyLayout: (response) => applyLayout(response, response.positions),
      })
    )).then(() => {
      if (workflowRef.current?.workflow_id === workflowId) {
        setAuthoringError(null);
      }
    });
  }, [applyLayout, layoutQueueForWorkflow, updateWorkflow]);

  const rollbackNodePositions = useCallback((
    workflowId: string,
    positions: CanvasLayoutPositionV2[],
  ) => {
    const pending = pendingLayoutPositionsRef.current.get(workflowId);
    positions.forEach((position) => pending?.delete(position.node_id));
    if (pending && !pending.size) pendingLayoutPositionsRef.current.delete(workflowId);
    updateWorkflow((current) => {
      if (!current || current.workflow_id !== workflowId) return current;
      const next = overlayAgentCanvasPositions(current, positions);
      return next;
    });
  }, [updateWorkflow]);

  const history = useAgentCanvasHistory({
    workflowId: agentCanvasWorkflow?.workflow_id ?? null,
    readWorkflow,
    applyWorkflow,
    authoringQueue: queueRef.current,
    updateNodePositions,
    rollbackNodePositions,
  });
  const { record: recordHistory, deleteEntities } = history;

  const createNode = useCallback(async (request: CanvasNodeCreateRequestV2) => {
    if (!agentCanvasWorkflow) throw new Error("No active Agent Canvas workflow.");
    return queueRef.current!.enqueue(createOperationKey("create-node"), async () => {
      const response = await agentCanvasApi.createAgentCanvasNode(agentCanvasWorkflow.workflow_id, request);
      applyWorkflow(response.value.workflow);
      if (response.value.node) {
        setSelectedNodeId(response.value.node.node_id);
        recordHistory({ kind: "create", node_id: response.value.node.node_id });
      }
      setAuthoringError(null);
      return response.value.node;
    });
  }, [agentCanvasWorkflow, applyWorkflow, recordHistory]);

  const placeActionReceiptNodes = useCallback(async (
    receipt: AgentActionReceiptV2,
  ) => {
    const current = workflowRef.current;
    if (!current || current.workflow_id !== receipt.workflow_id) return null;
    const latest = await agentCanvasApi.agentCanvasWorkflowWithEtag(receipt.workflow_id);
    if (workflowRef.current?.workflow_id !== receipt.workflow_id) return null;
    if (!receipt.created_node_ids.length) {
      applyWorkflow(latest.value);
      return null;
    }

    const preRevealLayout = buildAgentCanvasPreRevealLayout({
      nodes: latest.value.nodes,
      bindings: latest.value.bindings,
      affectedNodeIds: receipt.created_node_ids,
      assets: latest.value.assets,
    });
    applyWorkflow(latest.value);
    if (workflowRef.current?.workflow_id !== receipt.workflow_id) return null;
    if (!preRevealLayout.positions.length || !preRevealLayout.revealPlan.orderedNodeIds.length) return null;
    await updateNodePositions(preRevealLayout.positions);
    if (workflowRef.current?.workflow_id !== receipt.workflow_id) return null;
    return preRevealLayout.revealPlan;
  }, [applyWorkflow, updateNodePositions]);

  const deleteNode = useCallback(async (nodeId: string) => {
    await deleteEntities([nodeId], []);
    setSelectedNodeId((current) => current === nodeId ? null : current);
    setAuthoringError(null);
  }, [deleteEntities]);

  const createBinding = useCallback(async (
    request: CanvasBindingCreateRequestV2,
    options?: { isCurrent?: () => boolean },
  ) => {
    if (!agentCanvasWorkflow) throw new Error("No active Agent Canvas workflow.");
    assertValidCanvasBindingWrite(request);
    const workflowId = agentCanvasWorkflow.workflow_id;
    const isCurrent = () => workflowRef.current?.workflow_id === workflowId && (options?.isCurrent?.() ?? true);
    return queueRef.current!.enqueue(createOperationKey("create-binding"), async () => {
      if (!isCurrent()) return null;
      try {
        // Optimistic connections own rollback; a global transport retry would outlive that owner.
        const response = await agentCanvasApi.createAgentCanvasBinding(workflowId, request,
          options?.isCurrent ? { conflictHandling: "caller" } : undefined);
        if (!isCurrent()) return null;
        applyWorkflow(response.value.workflow);
        if (response.value.binding) recordHistory({ kind: "connect", binding: response.value.binding });
        setAuthoringError(null);
        return response.value.binding;
      } catch (error) {
        if (!isCurrent()) return null;
        throw error;
      }
    });
  }, [agentCanvasWorkflow, applyWorkflow, recordHistory]);

  const createConnectedNode = useCallback(async (
    request: CanvasConnectedNodeCreateRequestV2,
  ) => {
    if (!agentCanvasWorkflow) throw new Error("No active Agent Canvas workflow.");
    const workflowId = agentCanvasWorkflow.workflow_id;
    return queueRef.current!.enqueue(createOperationKey("create-connected-node"), async () => {
      const response = await agentCanvasApi.createAgentCanvasConnectedNode(
        workflowId,
        request,
        createOperationKey("create-connected-node-request"),
      );
      updateWorkflow((current) => {
        if (!current || current.workflow_id !== workflowId) return current;
        const next = mergeAgentCanvasConnectedNode(current, response.value);
        return next;
      });
      recordHistory({ kind: "create", node_id: response.value.node.node_id });
      setSelectedNodeId(response.value.node.node_id);
      setAuthoringError(null);
      return response.value.node;
    });
  }, [agentCanvasWorkflow, recordHistory, updateWorkflow]);

  const importEditingExport = useCallback(async (
    editingNodeId: string,
    request: CanvasEditingExportImportRequestV2,
  ) => {
    if (!agentCanvasWorkflow) throw new Error("No active Agent Canvas workflow.");
    const workflowId = agentCanvasWorkflow.workflow_id;
    const importScope = `${workflowId}:${editingNodeId}:${JSON.stringify(request)}`;
    let idempotencyKey = editingExportImportKeysRef.current.get(importScope);
    if (!idempotencyKey) {
      idempotencyKey = createOperationKey("editing-export-import-request");
      editingExportImportKeysRef.current.set(importScope, idempotencyKey);
      if (editingExportImportKeysRef.current.size > 64) {
        const oldest = editingExportImportKeysRef.current.keys().next().value;
        if (oldest) editingExportImportKeysRef.current.delete(oldest);
      }
    }
    return queueRef.current!.enqueue(
      createOperationKey(`editing-export-import:${editingNodeId}`),
      async () => {
        const response = await agentCanvasApi.importAgentCanvasEditingExport(
          workflowId,
          editingNodeId,
          request,
          idempotencyKey,
        );
        updateWorkflow((current) => {
          if (!current || current.workflow_id !== workflowId) return current;
          const next = mergeAgentCanvasEditingExportImport(current, response.value);
          return next;
        });
        recordHistory({ kind: "create", node_id: response.value.node.node_id });
        setSelectedNodeId(response.value.node.node_id);
        setAuthoringError(null);
        return response.value;
      },
    );
  }, [agentCanvasWorkflow, recordHistory, updateWorkflow]);

  const patchBinding = useCallback(async (
    bindingId: string,
    request: CanvasBindingPatchRequestV2,
  ) => {
    if (!agentCanvasWorkflow) throw new Error("No active Agent Canvas workflow.");
    const workflowId = agentCanvasWorkflow.workflow_id;
    return queueRef.current!.enqueue(
      createOperationKey(`patch-binding:${bindingId}`),
      async () => {
        const response = await agentCanvasApi.patchAgentCanvasBinding(
          workflowId,
          bindingId,
          request,
          createOperationKey("patch-binding-request"),
        );
        updateWorkflow((current) => {
          if (!current || current.workflow_id !== workflowId) return current;
          const next = mergeAgentCanvasBindingMutation(current, response.value);
          return next;
        });
        setAuthoringError(null);
        return response.value.binding;
      },
    );
  }, [agentCanvasWorkflow, updateWorkflow]);

  const deleteBinding = useCallback(async (bindingId: string) => {
    await deleteEntities([], [bindingId]);
    setAuthoringError(null);
  }, [deleteEntities]);

  const mergePublishedAsset = useCallback((asset: ProjectAssetSummaryV2, nodeId?: string | null) => {
    updateWorkflow((current) => {
      if (!current) return current;
      return {
        ...current,
        assets: [asset, ...current.assets.filter((item) => item.asset_id !== asset.asset_id)],
        nodes: nodeId
          ? current.nodes.map((node) => node.node_id === nodeId
            ? {
                ...node,
                status: "ready",
                output_asset_id: asset.asset_id,
                output_asset_version_id: asset.version_id,
                error: null,
              }
            : node)
          : current.nodes,
      };
    });
  }, [updateWorkflow]);

  const mergeNode = useCallback((nextNode: CanvasNodeV2) => {
    updateWorkflow((current) => {
      if (!current || current.workflow_id !== nextNode.workflow_id) return current;
      return mergeExistingAgentCanvasNode(current, nextNode);
    });
  }, [updateWorkflow]);

  const selectedNode = useMemo(
    () => agentCanvasWorkflow?.nodes.find((node) => node.node_id === selectedNodeId) ?? null,
    [agentCanvasWorkflow?.nodes, selectedNodeId],
  );

  return {
    history,
    state: {
      workflow: agentCanvasWorkflow,
      selectedNode,
      selectedNodeId,
      workspaceHydrated,
      workspaceRestoreError,
      authoringError,
    },
    actions: {
      applyWorkflow,
      setSelectedNodeId,
      clearAuthoringError: () => setAuthoringError(null),
      patchNode,
      updateNodePosition,
      updateNodePositions,
      moveNodes: history.moveNodes,
      persistLayoutPreviewPositions,
      rollbackNodePositions,
      createNode,
      createConnectedNode,
      importEditingExport,
      placeActionReceiptNodes,
      deleteNode,
      createBinding,
      patchBinding,
      deleteBinding,
      mergePublishedAsset,
      mergeNode,
    },
  };
}
