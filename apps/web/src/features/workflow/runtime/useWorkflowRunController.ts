import { useEffect, useRef } from "react";
import { api } from "../../../api/client.ts";
import { v2Api } from "../../../api/v2Client.ts";
import type {
  AdRequest,
  AssetLibraryEntitySummary,
  AssetLibraryReference,
  FrontDeskMessage,
  MediaStatus,
  NodeRunResult,
  ResolvedNodeInputs,
  UploadedAsset,
  WorkflowExecutionState,
  WorkflowGraph,
  WorkflowNode,
  WorkflowRunRequest,
  WorkflowRunResponse,
  WorkflowVariable,
} from "../../../types.ts";
import type { V2PlanFromPromptRequest, WorkflowV2, WorkflowV2RunResponse } from "../../../types-v2.ts";
import type { CanvasEdge, CanvasNode } from "../types.ts";
import { resolveWorkflowAdRequest } from "../../../workflow/adRequest.ts";
import { dedupeAssets } from "../../../workflow/assets.ts";
import { validateCanvas as validateStoredCanvas } from "../../../workflow/connectionValidation.ts";
import {
  executionRuntimeFromRunResponse,
  isExecutionRuntimeTerminal,
  type ExecutionPollingState,
} from "../../../workflow/executionRuntime.ts";
import { isFinalCompositionNode } from "../../../workflow/finalVideo.ts";
import {
  type StoryboardVideoReadiness,
  isStoryboardVideoNode,
  shouldPollStoryboardVideoMedia,
} from "../../../workflow/mediaSegments.ts";
import {
  buildFinalCompositionInputContext,
  buildNodeRunInputContext,
} from "../../../workflow/nodeRunContext.ts";
import { buildMainWorkflowRunRequest, formatWorkflowRunStatus } from "../../../workflow/runControls.ts";
import { shouldApplyWorkflowScopedResult } from "../../../workflow/sessionGuards.ts";
import { isV2WorkflowId } from "../../../workflow-v2/pageAdapter.ts";
import { buildV2PlanFromChatRequest } from "../copilot/copilotRequestBuilders.ts";
import { libraryEntitiesToReferences } from "../assets/assetLibraryReferenceModel.ts";
import {
  flowNodeToWorkflowNode,
  formatRunWorkflowValidationMessage,
} from "../canvas/workflowCanvasModel.ts";
import {
  canRunNodeStandalone,
} from "../canvas/workflowNodeModel.ts";
import {
  firstIssueMessage,
} from "../graph/workflowGraphValidationModel.ts";
import {
  getNodePrompt,
  toWorkflowEdges,
} from "../graph/workflowGraphPayloadModel.ts";
import {
  resolvedInputsFromNodeRun,
} from "./resolvedInputsViewModel.ts";
import {
  appendReferencePolicyStatus,
} from "./workflowRunOutputViewModel.ts";
import {
  finalCompositionErrorMessage,
  formatWorkflowExecutionError,
  getFailedRunNodeIds,
  getMediaStatusFromRunResult,
  getWorkflowRunNodeIds,
  hasPendingStoryboardVideoRun,
  isWorkflowRunTerminalStatus,
  shouldStopWorkflowPolling,
  workflowExecutionIdFromMessage,
  workflowRunFailedNodeIds,
  workflowRunResponseFromExecutionState,
  workflowRunResultFromExecution,
} from "./workflowExecutionViewModel.ts";
import { workflowIsFullyCompleted } from "../quality/qualityReviewViewModel.ts";
import { sleep } from "../page/workflowPageFormatters.ts";
import type { WorkflowRunControllerArgs, WorkflowRunMessages } from "./workflowRunControllerState.ts";

export function useWorkflowRunController(args: WorkflowRunControllerArgs) {
  const argsRef = useRef(args);

  useEffect(() => {
    argsRef.current = args;
  }, [args]);

  function getCurrentRunAdRequest(): AdRequest {
    const current = argsRef.current;
    return resolveWorkflowAdRequest({
      frontendAdRequest: current.adRequest,
      defaultAdRequest: current.defaultAdRequest,
      selectedAssets: current.selectedAssets,
      workflow: current.workflow,
      nodes: current.canvasNodes,
    });
  }

  function buildWorkflowRunRequest(overrides: Partial<WorkflowRunRequest> = {}): WorkflowRunRequest {
    const current = argsRef.current;
    const currentAdRequest = getCurrentRunAdRequest();
    return {
      ...current.runSettings,
      ...currentAdRequest,
      ad_request: currentAdRequest,
      ...overrides,
    };
  }

  function clearExecutionRuntime(nextState: ExecutionPollingState = "idle") {
    const current = argsRef.current;
    current.setActiveExecutionId(null);
    current.setExecutionNodeStatusById({});
    current.setRunningNodeIds([]);
    current.setExecutionPollingState(nextState);
  }

  function applyExecutionRuntimeState(state?: WorkflowRunResponse | WorkflowExecutionState | null) {
    const current = argsRef.current;
    const runtime = executionRuntimeFromRunResponse(state);
    current.setActiveExecutionId(runtime.activeExecutionId);
    current.setExecutionNodeStatusById(runtime.nodeStatusById);
    current.setRunningNodeIds(runtime.runningNodeIds);
    current.setExecutionPollingState(runtime.pollingState);
    return runtime;
  }

  async function refreshExecutionRuntime(workflowId: string, executionId?: string | null) {
    const current = argsRef.current;
    if (!executionId) return null;
    if (isV2WorkflowId(workflowId) || current.currentWorkflowIsV2()) return null;
    try {
      const execution = await api.workflowExecution(workflowId, executionId);
      if (!execution || !shouldApplyWorkflowScopedResult(workflowId, current.activeWorkflowIdRef.current)) return null;
      applyExecutionRuntimeState(execution);
      return execution;
    } catch {
      return null;
    }
  }

  async function executeWorkflowRun(request: WorkflowRunRequest, messages: WorkflowRunMessages) {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id) return null;
    const requestWorkflowId = current.workflow.workflow_id;
    const expectedNodeIds = getWorkflowRunNodeIds(current.flowNodes, current.flowEdges, request.start_node_id ?? null, request.run_downstream !== false);
    let submitted = false;
    let keepExecutionRuntime = false;
    clearExecutionRuntime("starting");
    current.setWorkflowRunning(true);
    current.setStatus(messages.running);

    try {
      current.assertNotV2WorkflowForV1Api(requestWorkflowId, "run");
      const result = await api.runWorkflow(requestWorkflowId, request);
      if (!shouldApplyWorkflowScopedResult(requestWorkflowId, current.activeWorkflowIdRef.current)) return null;
      submitted = true;
      current.setWorkflowRun(result);
      const runtime = applyExecutionRuntimeState(result);
      if (!runtime.activeExecutionId && !isWorkflowRunTerminalStatus(result.status)) current.setExecutionPollingState("polling");
      const immediateMediaStatus = getMediaStatusFromRunResult(result);
      if (immediateMediaStatus) current.setMediaStatus(immediateMediaStatus);
      applyWorkflowRunSummary(result);
      current.setStatus(appendReferencePolicyStatus(formatWorkflowRunStatus(result, messages.running), result.reference_policy));
      if (result.status === "no_op") {
        current.setStatus(appendReferencePolicyStatus(formatWorkflowRunStatus(result, "Workflow is already completed and has no stale nodes."), result.reference_policy));
        return result;
      }
      const pollResult = await pollWorkflowResults(requestWorkflowId, expectedNodeIds, result);
      if (!shouldApplyWorkflowScopedResult(requestWorkflowId, current.activeWorkflowIdRef.current)) return null;
      keepExecutionRuntime = Boolean(pollResult.execution && !isExecutionRuntimeTerminal(pollResult.execution.status));
      const effectiveResult = pollResult.finalResult ?? pollResult.executionResult ?? result;
      current.setWorkflowRun(effectiveResult);
      const effectiveMediaStatus = getMediaStatusFromRunResult(effectiveResult);
      if (effectiveMediaStatus) current.setMediaStatus(effectiveMediaStatus);
      applyWorkflowRunSummary(effectiveResult);
      const failedNodes = getFailedRunNodeIds(pollResult.nodes);
      const resultFailedNodes = workflowRunFailedNodeIds(effectiveResult);
      if (effectiveResult.status === "waiting") {
        current.setStatus(appendReferencePolicyStatus(formatWorkflowRunStatus(effectiveResult, "Workflow waiting"), effectiveResult.reference_policy));
      } else if (resultFailedNodes.length || failedNodes.length) {
        current.setStatus(appendReferencePolicyStatus(formatWorkflowRunStatus({ ...effectiveResult, status: "failed", failed_node_ids: resultFailedNodes.length ? resultFailedNodes : failedNodes }, messages.failed), effectiveResult.reference_policy));
      } else {
        current.setStatus(appendReferencePolicyStatus(formatWorkflowRunStatus(effectiveResult, messages.complete), effectiveResult.reference_policy));
      }
      return effectiveResult;
    } catch (error) {
      if (!shouldApplyWorkflowScopedResult(requestWorkflowId, current.activeWorkflowIdRef.current)) return null;
      const executionError = formatWorkflowExecutionError(error);
      const message = executionError.message || (error instanceof Error ? error.message : messages.failed);
      if (executionError.code) {
        keepExecutionRuntime = executionError.code === "workflow_execution_already_running";
        current.setStatus(message);
        const existingExecutionId = workflowExecutionIdFromMessage(message);
        if (existingExecutionId) {
          current.setActiveExecutionId(existingExecutionId);
          current.setExecutionPollingState("polling");
        }
        return null;
      }
      if (!submitted) {
        markNodesFailed(expectedNodeIds, message);
        current.setStatus(message);
      } else {
        current.setStatus(`Workflow sync failed: ${message}`);
      }
      return null;
    } finally {
      const latest = argsRef.current;
      if (shouldApplyWorkflowScopedResult(requestWorkflowId, latest.activeWorkflowIdRef.current)) {
        latest.setWorkflowRunning(false);
        if (keepExecutionRuntime) {
          latest.setExecutionPollingState("polling");
        } else {
          clearExecutionRuntime();
        }
      }
    }
  }

  function markNodesFailed(nodeIds: Set<string>, reason: string) {
    const current = argsRef.current;
    current.setCanvasNodes((nodes) =>
      nodes.map((node) => (nodeIds.has(node.id) ? { ...node, status: "failed", stale_reason: reason } : node)),
    );
    current.setFlowNodes((nodes) =>
      nodes.map((node) => (nodeIds.has(node.id) ? { ...node, data: { ...node.data, status: "failed", staleReason: reason } } : node)),
    );
  }

  function applyWorkflowRunSummary(result: WorkflowRunResponse) {
    const current = argsRef.current;
    const skipped = new Set(result.skipped_node_ids ?? []);
    const failed = new Set(workflowRunFailedNodeIds(result));
    const waiting = new Set(result.waiting_node_ids ?? []);
    const queued = new Set(result.queued_node_ids ?? []);
    const completed = new Set(result.completed_node_ids ?? []);
    current.setCanvasNodes((nodes) =>
      nodes.map((node) => {
        if (failed.has(node.id)) return { ...node, status: "failed", stale_reason: "Workflow run failed at this node" };
        if (waiting.has(node.id)) return { ...node, status: "waiting" };
        if (queued.has(node.id)) return { ...node, status: "queued" };
        if (skipped.has(node.id)) return { ...node, status: "skipped" };
        if (completed.has(node.id) && isWorkflowRunTerminalStatus(result.status)) return { ...node, status: "completed", stale: false, stale_reason: null };
        return node;
      }),
    );
    current.setFlowNodes((nodes) =>
      nodes.map((node) => {
        let status = node.data.status;
        let staleReason = node.data.staleReason;
        if (failed.has(node.id)) {
          status = "failed";
          staleReason = "Workflow run failed at this node";
        } else if (waiting.has(node.id)) {
          status = "waiting";
        } else if (queued.has(node.id)) {
          status = "queued";
        } else if (skipped.has(node.id)) {
          status = "skipped";
        } else if (completed.has(node.id) && isWorkflowRunTerminalStatus(result.status)) {
          status = "completed";
          staleReason = null;
        }
        return { ...node, data: { ...node.data, status, staleReason } };
      }),
    );
  }

  async function pollWorkflowResults(workflowId: string, expectedNodeIds: Set<string>, runResult?: WorkflowRunResponse) {
    let latestNodes: NodeRunResult[] = [];
    let latestMediaStatus: MediaStatus | null = null;
    let latestExecution: WorkflowExecutionState | null = null;
    let finalResult: WorkflowRunResponse | null = workflowRunResultFromExecution(runResult?.execution);
    let executionResult: WorkflowRunResponse | null = runResult?.execution ? workflowRunResponseFromExecutionState(runResult.execution, runResult) : null;
    const maxAttempts = isWorkflowRunTerminalStatus(runResult?.status) ? 8 : 40;
    const executionId = runResult?.execution_id;

    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      if (attempt > 0) await sleep(1600);
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) break;
      const execution = await refreshExecutionRuntime(workflowId, executionId);
      if (execution) {
        latestExecution = execution;
        finalResult = workflowRunResultFromExecution(execution) ?? finalResult;
        executionResult = workflowRunResponseFromExecutionState(execution, runResult);
      }
      try {
        const response = await api.workflowNodes(workflowId);
        if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) break;
        latestNodes = response.nodes ?? [];
        argsRef.current.applyNodeRunsToCanvas(latestNodes);
      } catch {
        // Node run records can lag behind the run submission; keep polling.
      }
      try {
        latestMediaStatus = await api.mediaStatus(workflowId);
        if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) break;
        if (shouldPollStoryboardVideoMedia(latestMediaStatus) || hasPendingStoryboardVideoRun(latestNodes)) {
          latestMediaStatus = await api.pollMedia(workflowId, {
            download_media: true,
            compose_when_ready: false,
            wait_until_ready: false,
            interval_seconds: 0,
            max_attempts: 1,
          });
          if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) break;
        }
        argsRef.current.setMediaStatus(latestMediaStatus);
        argsRef.current.applyMediaStatusToCanvas(latestMediaStatus);
      } catch {
        latestMediaStatus = null;
      }

      if (execution) {
        if (isExecutionRuntimeTerminal(execution.status) && attempt >= 1) break;
        if (!isExecutionRuntimeTerminal(execution.status)) continue;
      }
      if (shouldStopWorkflowPolling(latestNodes, expectedNodeIds, latestMediaStatus, runResult, attempt)) break;
    }

    if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) {
      return { nodes: [], mediaStatus: null, execution: null, finalResult: null, executionResult: null };
    }
    await argsRef.current.refreshWorkflowNodes(workflowId);
    await argsRef.current.refreshWorkflowGraph(workflowId, latestNodes);
    await argsRef.current.refreshMediaStatus(workflowId);
    const selectedNodeId = argsRef.current.selectedPlanNode?.id;
    if (selectedNodeId) await argsRef.current.refreshSelectedResolvedInputs(selectedNodeId, { force: true });
    return { nodes: latestNodes, mediaStatus: latestMediaStatus, execution: latestExecution, finalResult, executionResult };
  }

  async function runFrontDeskChatOnly() {
    const current = argsRef.current;
    const prompt = current.workflowPrompt.trim();
    if (!prompt) {
      current.setStatus("Enter a workflow prompt first.");
      return;
    }
    const requestScope = current.beginWorkflowMutationScope();
    const nextMessages = [...current.messages, { role: "user" as const, content: prompt }];
    current.setMessages(nextMessages);
    current.setStatus("Asking front desk...");
    try {
      const response = await api.chat(prompt, current.messages, current.selectedAssets, current.workflowPromptAssetReferences());
      if (!argsRef.current.shouldApplyWorkflowMutationScope(requestScope)) return;
      argsRef.current.setMessages([...nextMessages, { role: "assistant", content: response.reply }]);
      if (response.ad_request) {
        argsRef.current.setAdRequest((adRequest) => ({
          ...adRequest,
          ...response.ad_request,
          selected_assets: argsRef.current.selectedAssets,
        }));
      }
      argsRef.current.setStatus(response.should_start_workflow ? "Front desk says workflow is ready" : "Front desk needs more details");
    } catch (error) {
      if (!argsRef.current.shouldApplyWorkflowMutationScope(requestScope)) return;
      argsRef.current.setStatus(error instanceof Error ? error.message : "Front desk chat failed");
    }
  }

  async function planWorkflowFromPanelChat() {
    const current = argsRef.current;
    const prompt = current.workflowPrompt.trim();
    if (!prompt) {
      current.setStatus("Enter a workflow prompt first.");
      return;
    }
    const requestScope = current.beginWorkflowMutationScope();
    const nextMessages = [...current.messages, { role: "user" as const, content: prompt }];
    current.setMessages(nextMessages);
    current.setStatus("Planning workflow from chat...");
    try {
      const response = await v2Api.planFromChat(buildV2PlanFromChatRequest({
        message: prompt,
        history: current.messages,
        selectedAssets: current.selectedAssets,
        assetReferences: current.workflowPromptAssetReferences(),
        audioMode: current.adRequest.audio_mode ?? "bgm_only",
        libraryEntityIds: current.promptLibraryEntities.map((entity) => entity.entity_id),
        referenceMode: "strict",
      }));
      if (!argsRef.current.shouldApplyWorkflowMutationScope(requestScope)) return;
      argsRef.current.setMessages([...nextMessages, { role: "assistant", content: response.front_desk.reply }]);
      argsRef.current.syncFrontDeskAdRequest(response.front_desk.ad_request);
      if (response.workflow) {
        await argsRef.current.applyWorkflowV2(response.workflow);
        argsRef.current.setStatus(`Workflow ${response.workflow.workflow_id} planned from chat`);
      } else {
        argsRef.current.setStatus("Front desk needs more details before planning");
      }
    } catch (error) {
      if (!argsRef.current.shouldApplyWorkflowMutationScope(requestScope)) return;
      argsRef.current.setStatus(error instanceof Error ? error.message : "Plan from chat failed");
    }
  }

  async function generateWorkflowFromPanelChat() {
    const current = argsRef.current;
    const prompt = current.workflowPrompt.trim();
    if (!prompt) {
      current.setStatus("Enter a workflow prompt first.");
      return;
    }
    const requestScope = current.beginWorkflowMutationScope();
    const nextMessages = [...current.messages, { role: "user" as const, content: prompt }];
    current.setMessages(nextMessages);
    current.setStatus("Generating workflow from chat...");
    try {
      const response = await v2Api.planFromChat(buildV2PlanFromChatRequest({
        message: prompt,
        history: current.messages,
        selectedAssets: current.selectedAssets,
        assetReferences: current.workflowPromptAssetReferences(),
        audioMode: current.adRequest.audio_mode ?? "bgm_only",
        libraryEntityIds: current.promptLibraryEntities.map((entity) => entity.entity_id),
        referenceMode: "strict",
      }));
      if (!argsRef.current.shouldApplyWorkflowMutationScope(requestScope)) return;
      argsRef.current.setMessages([...nextMessages, { role: "assistant", content: response.front_desk.reply }]);
      argsRef.current.syncFrontDeskAdRequest(response.front_desk.ad_request);
      if (response.workflow) {
        await argsRef.current.applyWorkflowV2(response.workflow);
        argsRef.current.setStatus(`Workflow ${response.workflow.workflow_id} generated from chat`);
      } else {
        argsRef.current.setStatus("Front desk needs more details before generation");
      }
    } catch (error) {
      if (!argsRef.current.shouldApplyWorkflowMutationScope(requestScope)) return;
      argsRef.current.setStatus(error instanceof Error ? error.message : "Generate from chat failed");
    }
  }

  async function planStructuredWorkflow() {
    const current = argsRef.current;
    const requestScope = current.beginWorkflowMutationScope();
    current.setStatus("Planning structured workflow...");
    try {
      const nextWorkflow = await v2Api.planFromPrompt(current.v2PlanFromPromptRequest());
      if (!argsRef.current.shouldApplyWorkflowMutationScope(requestScope)) return;
      await argsRef.current.applyWorkflowV2(nextWorkflow);
      argsRef.current.setStatus(`Workflow ${nextWorkflow.workflow_id} planned`);
    } catch (error) {
      if (!argsRef.current.shouldApplyWorkflowMutationScope(requestScope)) return;
      argsRef.current.setStatus(error instanceof Error ? error.message : "Structured plan failed");
    }
  }

  async function generateStructuredWorkflow() {
    const current = argsRef.current;
    const requestScope = current.beginWorkflowMutationScope();
    current.setStatus("Generating structured workflow...");
    try {
      const nextWorkflow = await v2Api.planFromPrompt(current.v2PlanFromPromptRequest());
      if (!argsRef.current.shouldApplyWorkflowMutationScope(requestScope)) return;
      await argsRef.current.applyWorkflowV2(nextWorkflow);
      argsRef.current.setStatus(`Workflow ${nextWorkflow.workflow_id} generated`);
    } catch (error) {
      if (!argsRef.current.shouldApplyWorkflowMutationScope(requestScope)) return;
      argsRef.current.setStatus(error instanceof Error ? error.message : "Structured generate failed");
    }
  }

  async function runV2WorkflowFromExistingPage(messages: WorkflowRunMessages, runV2Workflow = argsRef.current.runV2Workflow) {
    const current = argsRef.current;
    const requestWorkflowId = current.workflow?.workflow_id;
    if (!requestWorkflowId) {
      current.setStatus("Generate a workflow before running it.");
      return;
    }
    current.setWorkflowRunning(true);
    current.setExecutionPollingState("polling");
    await current.syncV2Events(requestWorkflowId);
    current.setStatus(messages.running);
    try {
      await current.flushV2SlotDrafts();
      current.setStatus(messages.running);
      const response = await runV2Workflow({ mode: "fill_missing_required_slots" });
      if (!shouldApplyWorkflowScopedResult(requestWorkflowId, argsRef.current.activeWorkflowIdRef.current)) return;
      if (response.execution_id) {
        argsRef.current.setActiveExecutionId(response.execution_id);
      }
      if (response.workflow) {
        await argsRef.current.applyWorkflowV2(response.workflow, { refreshAssetsReason: false });
      }
      await argsRef.current.syncV2Snapshot(requestWorkflowId);
      await argsRef.current.syncV2Events(requestWorkflowId);
      await argsRef.current.refreshV2AssetsAndRetryMissing(requestWorkflowId, response.workflow ? "run-completed" : "run-started", response.workflow ?? null);
      argsRef.current.setExecutionPollingState("polling");
      argsRef.current.setStatus(response.execution_id ? `${messages.running} · ${response.execution_id}` : messages.running);
    } catch (error) {
      argsRef.current.setStatus(error instanceof Error ? error.message : messages.failed);
      argsRef.current.setWorkflowRunning(false);
    }
  }

  async function runWorkflow() {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id) {
      current.setStatus("Generate a workflow before running it.");
      return;
    }
    if (current.currentWorkflowIsV2()) {
      await runV2WorkflowFromExistingPage({
        running: "Workflow V2 running...",
        complete: "Workflow V2 run complete",
        failed: "Workflow V2 run failed",
      }, current.runV2Workflow);
      return;
    }
    await runV1WorkflowFromFacade();
  }

  async function runV1WorkflowFromFacade() {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id) {
      current.setStatus("Generate a workflow before running it.");
      return;
    }
    const validation = validateStoredCanvas(current.flowNodes, current.flowEdges);
    if (!validation.ok) {
      current.setStatus(formatRunWorkflowValidationMessage(validation.message, current.flowNodes, current.flowEdges));
      return;
    }
    current.setStatus("Running workflow...");
    try {
      const saved = await current.saveCanvas({ quiet: true, requireBackend: true });
      if (!saved) return;
      const backendValidation = await current.validateBackendGraph({ quiet: true });
      if (!backendValidation.valid) {
        current.setStatus(firstIssueMessage(backendValidation.errors) ?? "Graph validation failed. Run cancelled.");
        return;
      }
      const forceRerunAll = workflowIsFullyCompleted(current.visibleCanvasNodes);
      if (forceRerunAll && !window.confirm("当前工作流已全部完成，是否从头重新生成？旧资产会保留在历史资产中。")) {
        current.setStatus("Workflow run cancelled.");
        return;
      }
      await executeWorkflowRun(buildMainWorkflowRunRequest({
        ...current.runSettings,
        mode: forceRerunAll ? "force_rerun_all" : "run_from_frontier",
        library_entity_ids: current.promptLibraryEntities.map((entity) => entity.entity_id),
        asset_references: libraryEntitiesToReferences(current.promptLibraryEntities, {}, { primaryReferenceIds: new Set(current.promptPrimaryReferenceIds) }),
      }, getCurrentRunAdRequest()), {
        running: "Workflow running...",
        complete: "Workflow run complete",
        failed: "Workflow run failed",
      });
    } catch (error) {
      current.setStatus(error instanceof Error ? error.message : "Workflow run failed");
    }
  }

  async function runFromSelected() {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id) {
      current.setStatus("Generate a workflow before running from a node.");
      return;
    }
    if (!current.selectedPlanNode) {
      current.setStatus("Select a node first.");
      return;
    }
    if (current.currentWorkflowIsV2()) {
      await runV2WorkflowFromExistingPage({
        running: `Running V2 workflow from ${current.selectedPlanNode.title}...`,
        complete: `V2 workflow run from ${current.selectedPlanNode.title} complete`,
        failed: "V2 workflow run failed",
      }, current.runV2Workflow);
      return;
    }
    current.setStatus(`Running downstream from ${current.selectedPlanNode.title}...`);
    try {
      const saved = await current.saveCanvas({ quiet: true, requireBackend: true });
      if (!saved) return;
      const backendValidation = await current.validateBackendGraph({ quiet: true });
      if (!backendValidation.valid) {
        current.setStatus(firstIssueMessage(backendValidation.errors) ?? "Graph validation failed. Downstream run cancelled.");
        return;
      }
      await executeWorkflowRun(buildWorkflowRunRequest({
        start_node_id: current.selectedPlanNode.id,
        only_missing: false,
        run_downstream: true,
      }), {
        running: `Running downstream from ${current.selectedPlanNode.title}...`,
        complete: `Downstream run from ${current.selectedPlanNode.title} complete`,
        failed: "Downstream run failed",
      });
    } catch (error) {
      current.setStatus(error instanceof Error ? error.message : "Downstream run failed");
    }
  }

  async function runNode(options: { useRunPanelOverride?: boolean } = {}) {
    const current = argsRef.current;
    if (!current.selectedPlanNode) {
      current.setStatus("Select a node first.");
      return;
    }
    if (current.currentNodeRunningRef.current || current.currentNodeRunning) {
      current.setStatus("Current node is already running.");
      return;
    }
    if (current.currentWorkflowIsV2()) {
      await current.runSelectedV2Slot();
      return;
    }
    const requestWorkflowId = current.workflow?.workflow_id ?? null;
    const requestNodeId = current.selectedPlanNode.id;
    const requestNodeRunId = current.currentNodeRunRequestRef.current + 1;
    current.currentNodeRunRequestRef.current = requestNodeRunId;
    current.currentNodeRunningRef.current = true;
    current.setCurrentNodeRunning(true);
    let finalCompositionReadiness: StoryboardVideoReadiness | null = null;
    const isFinalCompositionRun = isFinalCompositionNode(current.selectedPlanNode, current.selectedRunType);
    try {
      if (requestWorkflowId) {
        const saved = await current.saveCanvas({ quiet: true, requireBackend: true });
        if (!saved || !current.shouldApplyCurrentNodeRun(requestWorkflowId, requestNodeId, requestNodeRunId)) return;
      }
      if (requestWorkflowId && !canRunNodeStandalone(current.selectedRunType)) {
        current.setStatus(`Running current node only: ${current.selectedRunType}...`);
        await executeWorkflowRun(buildWorkflowRunRequest({
          start_node_id: current.selectedPlanNode.id,
          target_node_id: current.selectedPlanNode.id,
          target_node_type: current.selectedRunType,
          run_downstream: false,
          only_missing: false,
          force_rerun: true,
          library_entity_ids: current.nodeRunLibraryEntities.map((entity) => entity.entity_id),
          asset_references: current.nodeScopedAssetReferences(),
        }), {
          running: `Running ${current.selectedRunType}...`,
          complete: `${current.selectedRunType} current node run complete`,
          failed: "Current node run failed",
        });
        return;
      }
      if (!canRunNodeStandalone(current.selectedRunType)) {
        current.setStatus(`${current.selectedRunType} is not supported by standalone node run. Generate a workflow first.`);
        return;
      }
      if (requestWorkflowId && isFinalCompositionRun) {
        finalCompositionReadiness = await current.prepareFinalCompositionRun(current.selectedPlanNode);
        if (!current.shouldApplyCurrentNodeRun(requestWorkflowId, requestNodeId, requestNodeRunId)) return;
        if (!finalCompositionReadiness?.ready) return;
      }
      current.setStatus(`Running current node only: ${current.selectedRunType}...`);
      current.patchWorkflowNodeState([requestNodeId], { status: "running", stale_reason: null });
      const cachedResolvedInputs = current.selectedResolvedInputs?.node_id === current.selectedPlanNode.id ? current.selectedResolvedInputs : null;
      const resolvedInputs = requestWorkflowId
        ? (await current.refreshSelectedResolvedInputs(current.selectedPlanNode.id, { force: true })) ?? cachedResolvedInputs
        : null;
      if (!current.shouldApplyCurrentNodeRun(requestWorkflowId, requestNodeId, requestNodeRunId)) return;
      const result = await api.runNode({
        workflow_id: requestWorkflowId,
        node_id: current.selectedPlanNode.id,
        node_type: current.selectedRunType,
        input_context: finalCompositionReadiness?.ready
          ? buildFinalCompositionInputContext(current.selectedPlanNode, current.workflowVariables, resolvedInputs, finalCompositionReadiness)
          : buildNodeRunInputContext(current.selectedPlanNode, current.workflowVariables, resolvedInputs),
        input_assets: finalCompositionReadiness?.ready
          ? dedupeAssets([...finalCompositionReadiness.assets, ...(current.selectedPlanNode.input_assets ?? [])])
          : requestWorkflowId ? current.selectedPlanNode.input_assets : [...current.selectedAssets, ...(current.selectedPlanNode.input_assets ?? [])],
        library_entity_ids: current.nodeRunLibraryEntities.map((entity) => entity.entity_id),
        asset_references: current.nodeScopedAssetReferences(),
        override_prompt: options.useRunPanelOverride && current.overridePrompt ? current.overridePrompt : getNodePrompt(current.selectedPlanNode) || current.overridePrompt || null,
        mode: "real",
        media_mode: "real",
        save_outputs: true,
        auto_resolve: Boolean(requestWorkflowId),
        run_downstream: false,
        force_rerun: true,
      });
      if (!current.shouldApplyCurrentNodeRun(requestWorkflowId, requestNodeId, requestNodeRunId)) return;
      const selectedResult = { ...result, node_id: result.node_id || current.selectedPlanNode.id };
      const shouldPollStoryboardRun = isStoryboardVideoNode({ id: current.selectedPlanNode.id, node_type: current.selectedRunType }) && shouldPollStoryboardVideoMedia(selectedResult);
      current.setSelectedNodeRun(selectedResult);
      current.applyNodeRunsToCanvas([selectedResult]);
      if (shouldPollStoryboardRun) current.patchWorkflowNodeState([requestNodeId], { status: "running", stale_reason: null });
      current.setSelectedResolvedInputs(resolvedInputsFromNodeRun(selectedResult));
      current.setWorkflow((workflow) => workflow ?? { workflow_id: result.workflow_id, nodes: current.canvasNodes, edges: toWorkflowEdges(current.flowEdges) });
      await current.refreshWorkflowNodes(result.workflow_id);
      if (!current.shouldApplyCurrentNodeRun(requestWorkflowId, requestNodeId, requestNodeRunId)) return;
      await current.refreshWorkflowGraph(result.workflow_id, [...current.nodeRuns, selectedResult]);
      if (!current.shouldApplyCurrentNodeRun(requestWorkflowId, requestNodeId, requestNodeRunId)) return;
      await current.refreshMediaStatus(result.workflow_id);
      if (!current.shouldApplyCurrentNodeRun(requestWorkflowId, requestNodeId, requestNodeRunId)) return;
      if (requestWorkflowId) await current.refreshSelectedResolvedInputs(current.selectedPlanNode.id, { force: true });
      current.setStatus(appendReferencePolicyStatus(`${current.selectedRunType} ${result.status} · downstream not run`, selectedResult.reference_policy));
      if (shouldPollStoryboardRun) {
        current.setStatus(`${current.selectedRunType} submitted · waiting for video segments`);
        await current.pollStoryboardVideoMedia(result.workflow_id);
      }
    } catch (error) {
      const latest = argsRef.current;
      if (!latest.shouldApplyCurrentNodeRun(requestWorkflowId, requestNodeId, requestNodeRunId)) return;
      latest.patchWorkflowNodeState([requestNodeId], { status: "failed", stale_reason: error instanceof Error ? error.message : finalCompositionErrorMessage(error) });
      latest.setStatus(error instanceof Error ? error.message : "Node run failed");
    } finally {
      const latest = argsRef.current;
      if (requestNodeRunId === latest.currentNodeRunRequestRef.current) {
        latest.currentNodeRunningRef.current = false;
        latest.setCurrentNodeRunning(false);
      }
    }
  }

  const actionsRef = useRef<{
    getCurrentRunAdRequest: typeof getCurrentRunAdRequest;
    buildWorkflowRunRequest: typeof buildWorkflowRunRequest;
    clearExecutionRuntime: typeof clearExecutionRuntime;
    refreshExecutionRuntime: typeof refreshExecutionRuntime;
    executeWorkflowRun: typeof executeWorkflowRun;
    applyWorkflowRunSummary: typeof applyWorkflowRunSummary;
    pollWorkflowResults: typeof pollWorkflowResults;
    runFrontDeskChatOnly: typeof runFrontDeskChatOnly;
    planWorkflowFromPanelChat: typeof planWorkflowFromPanelChat;
    generateWorkflowFromPanelChat: typeof generateWorkflowFromPanelChat;
    planStructuredWorkflow: typeof planStructuredWorkflow;
    generateStructuredWorkflow: typeof generateStructuredWorkflow;
    runV2WorkflowFromExistingPage: typeof runV2WorkflowFromExistingPage;
    runV1WorkflowFromFacade: typeof runV1WorkflowFromFacade;
    runWorkflow: typeof runWorkflow;
    runFromSelected: typeof runFromSelected;
    runNode: typeof runNode;
  } | null>(null);

  if (!actionsRef.current) {
    actionsRef.current = {
      getCurrentRunAdRequest,
      buildWorkflowRunRequest,
      clearExecutionRuntime,
      refreshExecutionRuntime,
      executeWorkflowRun,
      applyWorkflowRunSummary,
      pollWorkflowResults,
      runFrontDeskChatOnly,
      planWorkflowFromPanelChat,
      generateWorkflowFromPanelChat,
      planStructuredWorkflow,
      generateStructuredWorkflow,
      runV2WorkflowFromExistingPage,
      runV1WorkflowFromFacade,
      runWorkflow,
      runFromSelected,
      runNode,
    };
  }

  return {
    actions: actionsRef.current,
  };
}
