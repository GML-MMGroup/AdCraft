import { useCallback, useMemo, useRef, useState } from "react";

import { v2Api } from "../../../api/v2Client.ts";
import { createOperationKey } from "../../../api/operationKey.ts";
import { useApp } from "../../../AppContextValue.ts";
import type {
  AgentActionReceiptV2,
  AgentCanvasWorkflowV2,
  CanvasBindingCreateRequestV2,
  CanvasLayoutPatchResponseV2,
  CanvasLayoutPositionV2,
  CanvasNodeCreateRequestV2,
  CanvasNodePatchRequestV2,
  CanvasNodeV2,
  CanvasPositionV2,
  CanvasVariationDraftUpsertV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import { incrementalPlacementForNodes } from "../canvas/canvasGraphModel.ts";
import { AgentCanvasAuthoringQueue } from "./authoringQueue.ts";
import { persistAgentCanvasLayout } from "./layoutPersistence.ts";
import { AgentCanvasLayoutQueue } from "./layoutQueue.ts";
import {
  mergeAgentCanvasLayout,
  mergeAgentCanvasNode,
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
          ...(patch.model_id !== undefined ? { model_id: patch.model_id } : {}),
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
  const materializationKeysRef = useRef(new Map<string, string>());
  if (!queueRef.current) {
    queueRef.current = new AgentCanvasAuthoringQueue({
      onError(error) {
        setAuthoringError(error instanceof Error ? error.message : "Canvas update failed.");
      },
    });
  }
  const applyWorkflow = useCallback((next: AgentCanvasWorkflowV2) => {
    setAgentCanvasWorkflow((current) => {
      const merged = mergeAgentCanvasWorkflow(current, next);
      const pending = Array.from(
        pendingLayoutPositionsRef.current.get(merged.workflow_id)?.values() ?? [],
      );
      const withPending = overlayAgentCanvasPositions(merged, pending);
      workflowRef.current = withPending;
      return withPending;
    });
  }, [setAgentCanvasWorkflow]);

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
    setAgentCanvasWorkflow((current) => {
      if (!current || current.workflow_id !== response.workflow_id) return current;
      const merged = mergeAgentCanvasLayout(current, response);
      const next = overlayAgentCanvasPositions(
        merged,
        remainingPending,
      );
      workflowRef.current = next;
      return next;
    });
  }, [setAgentCanvasWorkflow]);

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
        return (await v2Api.agentCanvasWorkflowWithEtag(workflowId)).value;
      },
      patchLayout: (request) => {
        assertActiveWorkflow();
        return v2Api.patchAgentCanvasLayout(workflowId, request);
      },
      applyWorkflow,
      applyLayout: (response) => applyLayout(response, positions),
    });
    setAuthoringError(null);
  };

  const patchNode = useCallback((
    nodeId: string,
    patch: CanvasNodePatchRequestV2,
    options: { coalesce?: boolean; optimistic?: boolean } = {},
  ) => {
    if (!agentCanvasWorkflow) return Promise.reject(new Error("No active Agent Canvas workflow."));
    if (options.optimistic) {
      setAgentCanvasWorkflow((current) => current
        ? withNodePatch(current, nodeId, patch)
        : current);
    }
    const workflowId = agentCanvasWorkflow.workflow_id;
    return queueRef.current!.enqueue(
      options.coalesce ? `patch:${nodeId}` : createOperationKey(`patch:${nodeId}`),
      async () => {
        const response = await v2Api.patchAgentCanvasNode(workflowId, nodeId, patch);
        applyWorkflow(response.value.workflow);
        setAuthoringError(null);
      },
      { coalesce: options.coalesce },
    );
  }, [agentCanvasWorkflow, applyWorkflow, setAgentCanvasWorkflow]);

  const updateNodePositions = useCallback((positions: CanvasLayoutPositionV2[]) => {
    if (!positions.length) return Promise.resolve();
    const active = workflowRef.current;
    if (!active) return Promise.reject(new Error("No active Agent Canvas workflow."));
    const workflowId = active.workflow_id;
    const pendingByNode = pendingLayoutPositionsRef.current.get(workflowId)
      ?? new Map<string, CanvasLayoutPositionV2>();
    positions.forEach((position) => pendingByNode.set(position.node_id, position));
    pendingLayoutPositionsRef.current.set(workflowId, pendingByNode);
    setAgentCanvasWorkflow((current) => {
      if (!current || current.workflow_id !== workflowId) return current;
      const next = overlayAgentCanvasPositions(current, positions);
      workflowRef.current = next;
      return next;
    });
    let layoutQueue = layoutQueuesRef.current.get(workflowId);
    if (!layoutQueue) {
      layoutQueue = new AgentCanvasLayoutQueue(
        (batch) => flushLayoutRef.current(workflowId, batch),
      );
      layoutQueuesRef.current.set(workflowId, layoutQueue);
    }
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
  }, [setAgentCanvasWorkflow]);

  const updateNodePosition = useCallback((nodeId: string, position: CanvasPositionV2) => (
    updateNodePositions([{ node_id: nodeId, ...position }])
  ), [updateNodePositions]);

  const createNode = useCallback(async (request: CanvasNodeCreateRequestV2) => {
    if (!agentCanvasWorkflow) throw new Error("No active Agent Canvas workflow.");
    return queueRef.current!.enqueue(createOperationKey("create-node"), async () => {
      const response = await v2Api.createAgentCanvasNode(agentCanvasWorkflow.workflow_id, request);
      applyWorkflow(response.value.workflow);
      if (response.value.node) setSelectedNodeId(response.value.node.node_id);
      setAuthoringError(null);
      return response.value.node;
    });
  }, [agentCanvasWorkflow, applyWorkflow]);

  const saveVariationDraft = useCallback(async (
    nodeId: string,
    request: CanvasVariationDraftUpsertV2,
  ) => {
    if (!agentCanvasWorkflow) throw new Error("No active Agent Canvas workflow.");
    const workflowId = agentCanvasWorkflow.workflow_id;
    await queueRef.current!.enqueue(createOperationKey(`variation-save:${nodeId}`), async () => {
      const response = await v2Api.saveAgentCanvasVariationDraft(workflowId, nodeId, request);
      const keyPrefix = `${workflowId}:${nodeId}:`;
      Array.from(materializationKeysRef.current.keys()).forEach((key) => {
        if (key.startsWith(keyPrefix)) materializationKeysRef.current.delete(key);
      });
      setAgentCanvasWorkflow((current) => {
        if (!current || current.workflow_id !== response.workflow_id) return current;
        const next = {
          ...current,
          revision: Math.max(current.revision, response.workflow_revision),
          nodes: current.nodes.map((node) => node.node_id === nodeId
            ? { ...node, variation_draft: response.variation_draft }
            : node),
        };
        workflowRef.current = next;
        return next;
      });
      setAuthoringError(null);
    });
  }, [agentCanvasWorkflow, setAgentCanvasWorkflow]);

  const discardVariationDraft = useCallback(async (nodeId: string) => {
    if (!agentCanvasWorkflow) throw new Error("No active Agent Canvas workflow.");
    const workflowId = agentCanvasWorkflow.workflow_id;
    await queueRef.current!.enqueue(createOperationKey(`variation-discard:${nodeId}`), async () => {
      await v2Api.discardAgentCanvasVariationDraft(workflowId, nodeId);
      const keyPrefix = `${workflowId}:${nodeId}:`;
      Array.from(materializationKeysRef.current.keys()).forEach((key) => {
        if (key.startsWith(keyPrefix)) materializationKeysRef.current.delete(key);
      });
      const latest = await v2Api.agentCanvasWorkflowWithEtag(workflowId);
      applyWorkflow(latest.value);
      setAuthoringError(null);
    });
  }, [agentCanvasWorkflow, applyWorkflow]);

  const materializeVariationDraft = useCallback(async (
    source: CanvasNodeV2,
    action: "create_draft" | "generate",
  ) => {
    if (!agentCanvasWorkflow) throw new Error("No active Agent Canvas workflow.");
    if (!["image", "video", "audio"].includes(source.node_type) || source.status !== "ready") {
      throw new Error("Only Ready media nodes can create an editable sibling Draft.");
    }
    const workflowId = agentCanvasWorkflow.workflow_id;
    return queueRef.current!.enqueue(
      createOperationKey(`variation-materialize:${source.node_id}:${action}`),
      async () => {
        if (workflowRef.current?.workflow_id !== workflowId) return null;
        const canonicalSource = workflowRef.current?.workflow_id === workflowId
          ? workflowRef.current.nodes.find((node) => node.node_id === source.node_id)
          : null;
        const variationRevision = canonicalSource?.variation_draft?.variation_revision ?? 0;
        const materializationScope = `${workflowId}:${source.node_id}:${action}:${variationRevision}`;
        let idempotencyKey = materializationKeysRef.current.get(materializationScope);
        if (!idempotencyKey) {
          idempotencyKey = createOperationKey("variation-materialize");
          materializationKeysRef.current.set(materializationScope, idempotencyKey);
        }
        const response = await v2Api.materializeAgentCanvasVariationDraft(
          workflowId,
          source.node_id,
          { action },
          idempotencyKey,
        );
        if (workflowRef.current?.workflow_id !== workflowId) return null;
        const latest = await v2Api.agentCanvasWorkflowWithEtag(workflowId);
        if (workflowRef.current?.workflow_id !== workflowId) return null;
        applyWorkflow(latest.value);
        const positions = incrementalPlacementForNodes(
          latest.value.nodes,
          [response.sibling_node.node_id],
          [response.placement_hint],
          source.position,
        );
        if (positions.length) await updateNodePositions(positions);
        materializationKeysRef.current.delete(materializationScope);
        setSelectedNodeId(response.sibling_node.node_id);
        setAuthoringError(null);
        return latest.value.nodes.find((node) => node.node_id === response.sibling_node.node_id)
          ?? response.sibling_node;
      },
    );
  }, [agentCanvasWorkflow, applyWorkflow, updateNodePositions]);

  const placeActionReceiptNodes = useCallback(async (
    receipt: AgentActionReceiptV2,
    viewportAnchor: CanvasPositionV2,
  ) => {
    const current = workflowRef.current;
    if (!current || current.workflow_id !== receipt.workflow_id || !receipt.created_node_ids.length) return;
    const latest = await v2Api.agentCanvasWorkflowWithEtag(receipt.workflow_id);
    if (workflowRef.current?.workflow_id !== receipt.workflow_id) return;
    applyWorkflow(latest.value);
    const positions = incrementalPlacementForNodes(
      latest.value.nodes,
      receipt.created_node_ids,
      receipt.placement_hints,
      viewportAnchor,
    );
    if (workflowRef.current?.workflow_id !== receipt.workflow_id) return;
    if (positions.length) await updateNodePositions(positions);
  }, [applyWorkflow, updateNodePositions]);

  const deleteNode = useCallback(async (nodeId: string) => {
    if (!agentCanvasWorkflow) throw new Error("No active Agent Canvas workflow.");
    await queueRef.current!.enqueue(createOperationKey("delete-node"), async () => {
      const response = await v2Api.deleteAgentCanvasNode(agentCanvasWorkflow.workflow_id, nodeId);
      applyWorkflow(response.value.workflow);
      setSelectedNodeId((current) => current === nodeId ? null : current);
      setAuthoringError(null);
    });
  }, [agentCanvasWorkflow, applyWorkflow]);

  const createBinding = useCallback(async (request: CanvasBindingCreateRequestV2) => {
    if (!agentCanvasWorkflow) throw new Error("No active Agent Canvas workflow.");
    return queueRef.current!.enqueue(createOperationKey("create-binding"), async () => {
      const response = await v2Api.createAgentCanvasBinding(agentCanvasWorkflow.workflow_id, request);
      applyWorkflow(response.value.workflow);
      setAuthoringError(null);
      return response.value.binding;
    });
  }, [agentCanvasWorkflow, applyWorkflow]);

  const deleteBinding = useCallback(async (bindingId: string) => {
    if (!agentCanvasWorkflow) throw new Error("No active Agent Canvas workflow.");
    await queueRef.current!.enqueue(createOperationKey("delete-binding"), async () => {
      const response = await v2Api.deleteAgentCanvasBinding(agentCanvasWorkflow.workflow_id, bindingId);
      applyWorkflow(response.value.workflow);
      setAuthoringError(null);
    });
  }, [agentCanvasWorkflow, applyWorkflow]);

  const mergePublishedAsset = useCallback((asset: ProjectAssetSummaryV2, nodeId?: string | null) => {
    setAgentCanvasWorkflow((current) => {
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
                error: null,
              }
            : node)
          : current.nodes,
      };
    });
  }, [setAgentCanvasWorkflow]);

  const mergeNode = useCallback((nextNode: CanvasNodeV2) => {
    setAgentCanvasWorkflow((current) => {
      if (!current || current.workflow_id !== nextNode.workflow_id) return current;
      return {
        ...current,
        nodes: current.nodes.map((node) => node.node_id === nextNode.node_id
          ? mergeAgentCanvasNode(node, nextNode)
          : node),
      };
    });
  }, [setAgentCanvasWorkflow]);

  const selectedNode = useMemo(
    () => agentCanvasWorkflow?.nodes.find((node) => node.node_id === selectedNodeId) ?? null,
    [agentCanvasWorkflow?.nodes, selectedNodeId],
  );

  return {
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
      createNode,
      saveVariationDraft,
      discardVariationDraft,
      materializeVariationDraft,
      placeActionReceiptNodes,
      deleteNode,
      createBinding,
      deleteBinding,
      mergePublishedAsset,
      mergeNode,
    },
  };
}
