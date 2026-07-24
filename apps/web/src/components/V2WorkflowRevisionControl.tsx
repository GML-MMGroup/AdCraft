import { useCallback, useEffect, useRef, useState } from "react";
import { v2Api } from "../api/v2Client";
import { useApp } from "../AppContextValue";
import {
  advanceWorkflowRevisionScope,
  canStartWorkflowRevisionHistoryMutation,
  getWorkflowRevisionDisplayState,
  isWorkflowRevisionRequestCurrent,
  mergeRevisionHistoryPage,
  reconcileRefreshedRevisionHistory,
  reconcileRestoredRevisionHistory,
  resetWorkflowRevisionBusyState,
  revisionActionLabel,
  revisionCanBeRestored,
  selectWorkflowRevision,
  shouldRefreshWorkflowRevisionHistory,
  type WorkflowRevisionHistory,
  type WorkflowRevisionRequestScope,
  type WorkflowRevisionScope,
} from "../projects/v2RevisionHistory";
import type { WorkflowRevisionV2Detail } from "../types-v2";
import { workflowV2ToWorkflowGraph } from "../workflow-v2/pageAdapter";

const emptyRevisionHistory: WorkflowRevisionHistory = {
  items: [],
  nextCursor: null,
  selectedRevisionNo: null,
};

const initialWorkflowRevisionScope: WorkflowRevisionScope = {
  workflowId: null,
  generation: 0,
};

export default function V2WorkflowRevisionControl() {
  const { workflow, setWorkflow } = useApp();
  const [open, setOpen] = useState(false);
  const [history, setHistory] = useState<WorkflowRevisionHistory>(emptyRevisionHistory);
  const [selectedRevision, setSelectedRevision] = useState<WorkflowRevisionV2Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState<number | null>(null);
  const [restoring, setRestoring] = useState<number | null>(null);
  const workflowId = workflow?.project_id ? workflow.workflow_id : null;
  const [stateWorkflowId, setStateWorkflowId] = useState<string | null>(null);
  const workflowScope = useRef<WorkflowRevisionScope>(initialWorkflowRevisionScope);
  const historyRequest = useRef(0);
  const detailRequest = useRef(0);
  const restoreRequest = useRef(0);
  const explicitSelectionRequest = useRef(0);
  const historyMutationScope = useRef<WorkflowRevisionScope | null>(null);
  const historyRefresh = useRef<{
    workflowId: string;
    workflowGeneration: number;
    semanticRevisionNo: number;
  } | null>(null);
  const historyRef = useRef(history);
  historyRef.current = history;

  workflowScope.current = advanceWorkflowRevisionScope(workflowScope.current, workflowId);

  const displayState = getWorkflowRevisionDisplayState(workflowId, stateWorkflowId, {
    open,
    history,
    selectedRevision,
    error,
    loadingHistory,
    loadingMore,
    loadingDetail,
    restoring,
  });
  const revisionStateIsCurrent = stateWorkflowId === workflowId;
  const currentRevisionNo = workflow?.semantic_revision_no ?? 0;
  const revisionActionsBusy = displayState.loadingHistory
    || displayState.loadingMore
    || displayState.loadingDetail !== null
    || displayState.restoring !== null;

  const refreshRevisionHistory = useCallback((semanticRevisionNo: number): boolean => {
    if (!workflowId || !revisionStateIsCurrent || revisionActionsBusy) return false;
    const currentRefresh = historyRefresh.current;
    if (
      currentRefresh?.workflowId === workflowId
      && currentRefresh.workflowGeneration === workflowScope.current.generation
      && currentRefresh.semanticRevisionNo === semanticRevisionNo
    ) {
      return false;
    }
    const activeMutationScope = historyMutationScope.current;
    const mutationScope = workflowScope.current;
    if (
      activeMutationScope?.workflowId === mutationScope.workflowId
      && activeMutationScope.generation === mutationScope.generation
    ) {
      return false;
    }
    historyMutationScope.current = { ...mutationScope };
    historyRefresh.current = {
      workflowId,
      workflowGeneration: mutationScope.generation,
      semanticRevisionNo,
    };
    historyRequest.current += 1;
    const requestScope: WorkflowRevisionRequestScope = {
      workflowId,
      workflowGeneration: workflowScope.current.generation,
      requestGeneration: historyRequest.current,
    };
    void (async () => {
      try {
        setError(null);
        setLoadingHistory(true);
        const page = await v2Api.workflowRevisions(requestScope.workflowId);
        if (!isWorkflowRevisionRequestCurrent(workflowScope.current, historyRequest.current, requestScope)) return;
        setHistory((previous) => reconcileRefreshedRevisionHistory(previous, page));
      } catch (reason) {
        if (!isWorkflowRevisionRequestCurrent(workflowScope.current, historyRequest.current, requestScope)) return;
        setError(reason instanceof Error ? reason.message : "Revision history could not be refreshed.");
      } finally {
        if (isWorkflowRevisionRequestCurrent(workflowScope.current, historyRequest.current, requestScope)) {
          setLoadingHistory(false);
        }
        const currentMutationScope = historyMutationScope.current;
        if (
          currentMutationScope?.workflowId === mutationScope.workflowId
          && currentMutationScope.generation === mutationScope.generation
        ) {
          historyMutationScope.current = null;
        }
      }
    })();
    return true;
  }, [revisionActionsBusy, revisionStateIsCurrent, workflowId]);

  useEffect(() => {
    historyRequest.current += 1;
    detailRequest.current += 1;
    restoreRequest.current += 1;
    explicitSelectionRequest.current += 1;
    historyMutationScope.current = null;
    historyRefresh.current = null;
    const resetBusyState = resetWorkflowRevisionBusyState();
    setOpen(false);
    setHistory(emptyRevisionHistory);
    setSelectedRevision(null);
    setError(null);
    setLoadingHistory(resetBusyState.loadingHistory);
    setLoadingMore(resetBusyState.loadingMore);
    setLoadingDetail(resetBusyState.loadingDetail);
    setRestoring(resetBusyState.restoring);
    setStateWorkflowId(workflowId);
  }, [workflowId]);

  useEffect(() => {
    if (!shouldRefreshWorkflowRevisionHistory({
      activeWorkflowId: workflowId,
      stateWorkflowId,
      open,
      history: historyRef.current,
      semanticRevisionNo: currentRevisionNo,
    }) || revisionActionsBusy) {
      return;
    }
    refreshRevisionHistory(currentRevisionNo);
  }, [currentRevisionNo, open, refreshRevisionHistory, revisionActionsBusy, stateWorkflowId, workflowId]);

  if (!workflowId) return null;
  const activeWorkflowId = workflowId;

  function startRequest(requestGeneration: React.MutableRefObject<number>): WorkflowRevisionRequestScope {
    requestGeneration.current += 1;
    return {
      workflowId: activeWorkflowId,
      workflowGeneration: workflowScope.current.generation,
      requestGeneration: requestGeneration.current,
    };
  }

  function requestIsCurrent(
    requestGeneration: React.MutableRefObject<number>,
    requestScope: WorkflowRevisionRequestScope,
  ): boolean {
    return isWorkflowRevisionRequestCurrent(workflowScope.current, requestGeneration.current, requestScope);
  }

  function startHistoryMutation(): WorkflowRevisionScope | null {
    const mutationScope = workflowScope.current;
    if (!canStartWorkflowRevisionHistoryMutation(mutationScope, historyMutationScope.current)) return null;
    historyMutationScope.current = { ...mutationScope };
    return historyMutationScope.current;
  }

  function finishHistoryMutation(mutationScope: WorkflowRevisionScope) {
    const activeMutationScope = historyMutationScope.current;
    if (
      activeMutationScope?.workflowId === mutationScope.workflowId
      && activeMutationScope.generation === mutationScope.generation
    ) {
      historyMutationScope.current = null;
    }
  }

  async function toggleHistory() {
    if (!revisionStateIsCurrent || revisionActionsBusy) return;
    const nextOpen = !displayState.open;
    setOpen(nextOpen);
    if (!nextOpen) {
      historyRefresh.current = null;
      return;
    }
    if (displayState.loadingHistory) return;
    if (displayState.history.items.length) {
      if (shouldRefreshWorkflowRevisionHistory({
        activeWorkflowId,
        stateWorkflowId,
        open: nextOpen,
        history: displayState.history,
        semanticRevisionNo: currentRevisionNo,
      })) {
        refreshRevisionHistory(currentRevisionNo);
      }
      return;
    }
    const requestScope = startRequest(historyRequest);
    try {
      setError(null);
      setLoadingHistory(true);
      const page = await v2Api.workflowRevisions(requestScope.workflowId);
      if (!requestIsCurrent(historyRequest, requestScope)) return;
      setHistory((previous) => mergeRevisionHistoryPage(previous, page));
    } catch (reason) {
      if (!requestIsCurrent(historyRequest, requestScope)) return;
      setError(reason instanceof Error ? reason.message : "Revision history could not be loaded.");
    } finally {
      if (requestIsCurrent(historyRequest, requestScope)) setLoadingHistory(false);
    }
  }

  async function loadMore() {
    const cursor = displayState.history.nextCursor;
    if (!revisionStateIsCurrent || !cursor || revisionActionsBusy) return;
    const mutationScope = startHistoryMutation();
    if (!mutationScope) return;
    const requestScope = startRequest(historyRequest);
    try {
      setError(null);
      setLoadingMore(true);
      const page = await v2Api.workflowRevisions(requestScope.workflowId, 100, cursor);
      if (!requestIsCurrent(historyRequest, requestScope)) return;
      setHistory((previous) => mergeRevisionHistoryPage(previous, page));
    } catch (reason) {
      if (!requestIsCurrent(historyRequest, requestScope)) return;
      setError(reason instanceof Error ? reason.message : "More revision history could not be loaded.");
    } finally {
      if (requestIsCurrent(historyRequest, requestScope)) setLoadingMore(false);
      finishHistoryMutation(mutationScope);
    }
  }

  async function selectRevision(revisionNo: number) {
    if (!revisionStateIsCurrent || revisionActionsBusy) return;
    explicitSelectionRequest.current += 1;
    const requestScope = startRequest(detailRequest);
    setHistory((previous) => selectWorkflowRevision(previous, revisionNo));
    setSelectedRevision(null);
    try {
      setError(null);
      setLoadingDetail(revisionNo);
      const detail = await v2Api.workflowRevision(requestScope.workflowId, revisionNo);
      if (requestIsCurrent(detailRequest, requestScope)) setSelectedRevision(detail);
    } catch (reason) {
      if (requestIsCurrent(detailRequest, requestScope)) {
        setError(reason instanceof Error ? reason.message : "Revision detail could not be loaded.");
      }
    } finally {
      if (requestIsCurrent(detailRequest, requestScope)) setLoadingDetail(null);
    }
  }

  async function restoreRevision(revisionNo: number) {
    if (!revisionStateIsCurrent || revisionActionsBusy) return;
    const mutationScope = startHistoryMutation();
    if (!mutationScope) return;
    const requestScope = startRequest(restoreRequest);
    const selectionRequestAtStart = explicitSelectionRequest.current;
    setRestoring(revisionNo);
    try {
      setError(null);
      const response = await v2Api.restoreWorkflowRevision(requestScope.workflowId, revisionNo);
      if (!requestIsCurrent(restoreRequest, requestScope) || response.value.workflow.workflow_id !== requestScope.workflowId) return;
      setWorkflow((current) => {
        if (!requestIsCurrent(restoreRequest, requestScope) || current?.workflow_id !== requestScope.workflowId) {
          return current;
        }
        return workflowV2ToWorkflowGraph(response.value.workflow);
      });
      const restoredRevision = response.value.revision;
      const selectRestoredRevision = () => explicitSelectionRequest.current === selectionRequestAtStart;
      let detailRequestScope: WorkflowRevisionRequestScope | null = null;
      if (selectRestoredRevision()) {
        detailRequestScope = startRequest(detailRequest);
        setHistory((previous) => selectWorkflowRevision(previous, restoredRevision.revision_no));
        setSelectedRevision(null);
        setLoadingDetail(restoredRevision.revision_no);
      }
      const historyRequestScope = startRequest(historyRequest);
      try {
        const [page, detail] = await Promise.all([
          v2Api.workflowRevisions(historyRequestScope.workflowId),
          detailRequestScope
            ? v2Api.workflowRevision(detailRequestScope.workflowId, restoredRevision.revision_no)
            : Promise.resolve(null),
        ]);
        if (!requestIsCurrent(restoreRequest, requestScope) || !requestIsCurrent(historyRequest, historyRequestScope)) return;
        const shouldSelectRestoredRevision = selectRestoredRevision();
        setHistory((previous) => reconcileRestoredRevisionHistory(
          previous,
          page,
          restoredRevision,
          shouldSelectRestoredRevision,
        ));
        if (detail && detailRequestScope && shouldSelectRestoredRevision && requestIsCurrent(detailRequest, detailRequestScope)) {
          setSelectedRevision(detail);
        }
      } catch (reason) {
        if (requestIsCurrent(restoreRequest, requestScope) && requestIsCurrent(historyRequest, historyRequestScope)) {
          setError(reason instanceof Error ? reason.message : "Revision was restored, but its history could not be refreshed.");
        }
      } finally {
        if (detailRequestScope && requestIsCurrent(detailRequest, detailRequestScope)) setLoadingDetail(null);
      }
    } catch (reason) {
      if (requestIsCurrent(restoreRequest, requestScope)) {
        setError(reason instanceof Error ? reason.message : "Revision could not be restored.");
      }
    } finally {
      if (requestIsCurrent(restoreRequest, requestScope)) setRestoring(null);
      finishHistoryMutation(mutationScope);
    }
  }

  return (
    <div className="workflow-revision-control">
      <button
        className="ghost-btn"
        type="button"
        aria-expanded={displayState.open}
        disabled={revisionActionsBusy}
        onClick={() => void toggleHistory()}
      >
        History
      </button>
      {displayState.open ? (
        <section className="workflow-revision-menu" aria-label="Workflow revision history">
          <h2>Revision history</h2>
          {displayState.error ? <p role="alert">{displayState.error}</p> : null}
          {displayState.loadingHistory ? <p>Loading revision history...</p> : null}
          {displayState.history.items.map((revision) => (
            <div key={revision.revision_id} className="workflow-revision-row">
              <div className="workflow-revision-actions">
                <button
                  className="workflow-revision-select"
                  type="button"
                  aria-current={displayState.history.selectedRevisionNo === revision.revision_no ? "true" : undefined}
                  aria-pressed={displayState.history.selectedRevisionNo === revision.revision_no}
                  disabled={revisionActionsBusy}
                  onClick={() => void selectRevision(revision.revision_no)}
                >
                  {revisionActionLabel(revision)}
                </button>
                <button
                  className="workflow-revision-restore"
                  type="button"
                  disabled={!revisionCanBeRestored(revision, currentRevisionNo) || revisionActionsBusy}
                  onClick={() => void restoreRevision(revision.revision_no)}
                >
                  {revision.revision_no === currentRevisionNo ? "Current" : "Restore"}
                </button>
              </div>
              <time dateTime={revision.created_at}>{new Date(revision.created_at).toLocaleString()}</time>
            </div>
          ))}
          {displayState.history.nextCursor ? (
            <button type="button" disabled={revisionActionsBusy} onClick={() => void loadMore()}>
              {loadingMore ? "Loading..." : "Load more"}
            </button>
          ) : null}
          {displayState.loadingDetail === displayState.history.selectedRevisionNo ? <p>Loading revision detail...</p> : null}
          {displayState.selectedRevision && displayState.selectedRevision.revision_no === displayState.history.selectedRevisionNo ? (
            <section aria-label={`Revision ${displayState.selectedRevision.revision_no} detail`}>
              <h3>{revisionActionLabel(displayState.selectedRevision)}</h3>
              <pre>{JSON.stringify(displayState.selectedRevision.document, null, 2)}</pre>
            </section>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
