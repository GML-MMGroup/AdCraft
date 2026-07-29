import { useCallback, useMemo, useRef, useState } from "react";

import { v2Api } from "../../../api/v2Client.ts";
import { createOperationKey } from "../../../api/operationKey.ts";
import { useApp } from "../../../AppContextValue.ts";
import type {
  AgentCanvasWorkflowV2,
  CanvasBindingCreateRequestV2,
  CanvasNodeCreateRequestV2,
  CanvasNodePatchRequestV2,
  CanvasNodeV2,
  CanvasPositionV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import { AgentCanvasAuthoringQueue } from "./authoringQueue.ts";
import {
  mergeAgentCanvasNode,
  mergeAgentCanvasWorkflow,
} from "./workflowMerge.ts";
import {
  readyMediaSiblingRequest,
  type ReadyMediaVariationDraft,
} from "./readyMediaVariation.ts";

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
  const queueRef = useRef<AgentCanvasAuthoringQueue | null>(null);
  if (!queueRef.current) {
    queueRef.current = new AgentCanvasAuthoringQueue({
      onError(error) {
        setAuthoringError(error instanceof Error ? error.message : "Canvas update failed.");
      },
    });
  }

  const applyWorkflow = useCallback((next: AgentCanvasWorkflowV2) => {
    setAgentCanvasWorkflow((current) => mergeAgentCanvasWorkflow(current, next));
  }, [setAgentCanvasWorkflow]);

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

  const updateNodePosition = useCallback((nodeId: string, position: CanvasPositionV2) => {
    void patchNode(nodeId, { position }, { coalesce: true, optimistic: true }).catch(() => {});
  }, [patchNode]);

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

  const createSiblingDraft = useCallback(async (
    source: CanvasNodeV2,
    draft: ReadyMediaVariationDraft,
  ) => {
    return createNode(readyMediaSiblingRequest(source, draft));
  }, [createNode]);

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
      createNode,
      createSiblingDraft,
      deleteNode,
      createBinding,
      deleteBinding,
      mergePublishedAsset,
      mergeNode,
    },
  };
}
