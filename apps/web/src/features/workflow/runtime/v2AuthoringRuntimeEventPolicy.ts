import type { WorkflowRuntimeEventV2 } from "../../../types-v2.ts";
import { isV2SynchronizationEvent } from "../../../workflow-v2/runtime.ts";
import { v2EventRefreshHints } from "./v2RuntimeEventModel.ts";

export const V2_WORKFLOW_REVISION_CREATED_EVENT = "workflow_revision_created";
export const V2_EXECUTION_RESULT_REVISION_DEFERRED_EVENT = "execution_result_revision_deferred";

const DEFERRED_CANDIDATE_STATUS = "New candidate results are available.";

export type V2AuthoringRuntimeEventPolicy = {
  shouldRefreshAuthoringWorkflow: boolean;
  shouldRefreshSynchronizationWorkflow: boolean;
  shouldRefreshRuntimeWorkflow: boolean;
  shouldRefreshDeferredCandidates: boolean;
  deferredCandidateSlotIds: string[];
  candidateStatus: string | null;
  ordinaryRuntimeEvents: WorkflowRuntimeEventV2[];
};

export function createWorkflowRevisionRefreshCoalescer(
  refresh: (workflowId: string) => Promise<void>,
) {
  const refreshesByWorkflowId = new Map<string, {
    requestedGeneration: number;
    promise: Promise<void>;
  }>();

  return {
    request(workflowId: string): Promise<void> {
      const current = refreshesByWorkflowId.get(workflowId);
      if (current) {
        current.requestedGeneration += 1;
        return current.promise;
      }

      const entry = {
        requestedGeneration: 1,
        promise: Promise.resolve(),
      };
      refreshesByWorkflowId.set(workflowId, entry);
      const promise = (async () => {
        let completedGeneration = 0;
        while (completedGeneration < entry.requestedGeneration) {
          const requestedGeneration = entry.requestedGeneration;
          await refresh(workflowId);
          completedGeneration = requestedGeneration;
        }
      })().finally(() => {
        if (refreshesByWorkflowId.get(workflowId) === entry) {
          refreshesByWorkflowId.delete(workflowId);
        }
      });
      entry.promise = promise;
      return promise;
    },
  };
}

export function createV2AuthoringRuntimeEventPolicy(
  events: WorkflowRuntimeEventV2[],
): V2AuthoringRuntimeEventPolicy {
  const deferredCandidateSlotIds = new Set<string>();
  const ordinaryRuntimeEvents: WorkflowRuntimeEventV2[] = [];
  let shouldRefreshAuthoringWorkflow = false;
  let shouldRefreshDeferredCandidates = false;

  for (const event of events) {
    if (event.event_type === V2_WORKFLOW_REVISION_CREATED_EVENT) {
      shouldRefreshAuthoringWorkflow = true;
      continue;
    }
    if (event.event_type === V2_EXECUTION_RESULT_REVISION_DEFERRED_EVENT) {
      shouldRefreshDeferredCandidates = true;
      addSlotId(deferredCandidateSlotIds, event.slot_id);
      addSlotId(deferredCandidateSlotIds, event.payload?.slot_id);
      addSlotIds(deferredCandidateSlotIds, event.payload?.slot_ids);
      continue;
    }
    ordinaryRuntimeEvents.push(event);
  }

  const shouldRefreshSynchronizationWorkflow = ordinaryRuntimeEvents.some((event) =>
    isV2SynchronizationEvent(event.event_type));
  const shouldRefreshRuntimeWorkflow = shouldRefreshSynchronizationWorkflow
    || ordinaryRuntimeEvents.some((event) =>
      event.event_type === "graph_updated"
      || event.event_type === "workflow_updated"
      || event.event_type === "final_composition_render_completed"
      || v2EventRefreshHints(event).some((hint) =>
        hint === "workflow" || hint === "workflow_graph" || hint === "graph"));

  return {
    shouldRefreshAuthoringWorkflow,
    shouldRefreshSynchronizationWorkflow,
    shouldRefreshRuntimeWorkflow,
    shouldRefreshDeferredCandidates,
    deferredCandidateSlotIds: Array.from(deferredCandidateSlotIds),
    candidateStatus: shouldRefreshDeferredCandidates ? DEFERRED_CANDIDATE_STATUS : null,
    ordinaryRuntimeEvents,
  };
}

type RuntimeWorkflowRevision = {
  workflow_id: string;
  state_version?: number;
  semantic_revision_no?: number;
};

export function shouldApplyRuntimeWorkflowRead(
  candidate: RuntimeWorkflowRevision,
  current: RuntimeWorkflowRevision | null | undefined,
): boolean {
  if (!current || candidate.workflow_id !== current.workflow_id) return false;
  return versionIsCurrent(candidate.state_version, current.state_version)
    && versionIsCurrent(candidate.semantic_revision_no, current.semantic_revision_no);
}

export function shouldApplyWorkflowRevisionRead(
  candidate: RuntimeWorkflowRevision,
  current: RuntimeWorkflowRevision | null | undefined,
  {
    requestedWorkflowId,
    activeWorkflowId,
    baselineEtag,
    currentEtag,
  }: {
    requestedWorkflowId: string;
    activeWorkflowId: string | null;
    baselineEtag: string | null;
    currentEtag: string | null;
  },
): boolean {
  return candidate.workflow_id === requestedWorkflowId
    && requestedWorkflowId === activeWorkflowId
    && baselineEtag === currentEtag
    && shouldApplyRuntimeWorkflowRead(candidate, current);
}

function versionIsCurrent(candidate: number | undefined, current: number | undefined): boolean {
  return current === undefined || (candidate !== undefined && candidate >= current);
}

function addSlotId(target: Set<string>, value: unknown) {
  if (typeof value === "string" && value.trim()) target.add(value.trim());
}

function addSlotIds(target: Set<string>, value: unknown) {
  if (!Array.isArray(value)) return;
  value.forEach((item) => addSlotId(target, item));
}
