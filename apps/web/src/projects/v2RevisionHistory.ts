import type { WorkflowRevisionPage, WorkflowRevisionV2Summary } from "../types-v2.ts";

export interface WorkflowRevisionHistory {
  items: WorkflowRevisionV2Summary[];
  nextCursor: string | null;
  selectedRevisionNo: number | null;
}

export interface WorkflowRevisionDisplayState<TRevisionDetail> {
  open: boolean;
  history: WorkflowRevisionHistory;
  selectedRevision: TRevisionDetail | null;
  error: string | null;
  loadingHistory: boolean;
  loadingMore: boolean;
  loadingDetail: number | null;
  restoring: number | null;
}

export interface WorkflowRevisionScope {
  workflowId: string | null;
  generation: number;
}

export interface WorkflowRevisionRequestScope {
  workflowId: string;
  workflowGeneration: number;
  requestGeneration: number;
}

export interface WorkflowRevisionHistoryRefreshCheck {
  activeWorkflowId: string | null;
  stateWorkflowId: string | null;
  open: boolean;
  history: WorkflowRevisionHistory;
  semanticRevisionNo: number;
}

export function resetWorkflowRevisionBusyState() {
  return {
    loadingHistory: false,
    loadingMore: false,
    loadingDetail: null as number | null,
    restoring: null as number | null,
  };
}

export function advanceWorkflowRevisionScope(
  currentScope: WorkflowRevisionScope,
  workflowId: string | null,
): WorkflowRevisionScope {
  if (currentScope.workflowId === workflowId) return currentScope;
  return { workflowId, generation: currentScope.generation + 1 };
}

export function getWorkflowRevisionDisplayState<TRevisionDetail>(
  activeWorkflowId: string | null,
  stateWorkflowId: string | null,
  state: WorkflowRevisionDisplayState<TRevisionDetail>,
): WorkflowRevisionDisplayState<TRevisionDetail> {
  if (activeWorkflowId === stateWorkflowId) return state;
  return {
    open: false,
    history: { items: [], nextCursor: null, selectedRevisionNo: null },
    selectedRevision: null,
    error: null,
    loadingHistory: false,
    loadingMore: false,
    loadingDetail: null,
    restoring: null,
  };
}

export function canStartWorkflowRevisionHistoryMutation(
  activeScope: WorkflowRevisionScope,
  activeMutationScope: WorkflowRevisionScope | null,
): boolean {
  return activeMutationScope === null
    || activeMutationScope.workflowId !== activeScope.workflowId
    || activeMutationScope.generation !== activeScope.generation;
}

export function isWorkflowRevisionRequestCurrent(
  activeScope: WorkflowRevisionScope,
  latestRequestGeneration: number,
  requestScope: WorkflowRevisionRequestScope,
): boolean {
  return activeScope.workflowId === requestScope.workflowId
    && activeScope.generation === requestScope.workflowGeneration
    && latestRequestGeneration === requestScope.requestGeneration;
}

export function revisionCanBeRestored(revision: WorkflowRevisionV2Summary, currentRevisionNo: number): boolean {
  return revision.revision_no !== currentRevisionNo;
}

export function revisionActionLabel(revision: WorkflowRevisionV2Summary): string {
  const source = revision.change_source.replaceAll("_", " ");
  return `Revision ${revision.revision_no} · ${source.charAt(0).toUpperCase()}${source.slice(1)}`;
}

export function mergeRevisionHistoryPage(
  history: WorkflowRevisionHistory,
  page: WorkflowRevisionPage,
): WorkflowRevisionHistory {
  const revisionsById = new Map<string, WorkflowRevisionV2Summary>();
  for (const revision of [...page.items, ...history.items]) {
    if (!revisionsById.has(revision.revision_id)) revisionsById.set(revision.revision_id, revision);
  }
  return {
    ...history,
    items: [...revisionsById.values()].sort((left, right) => right.revision_no - left.revision_no),
    nextCursor: page.next_cursor,
  };
}

export function shouldRefreshWorkflowRevisionHistory({
  activeWorkflowId,
  stateWorkflowId,
  open,
  history,
  semanticRevisionNo,
}: WorkflowRevisionHistoryRefreshCheck): boolean {
  return activeWorkflowId !== null
    && activeWorkflowId === stateWorkflowId
    && open
    && history.items.length > 0
    && !history.items.some((revision) => revision.revision_no === semanticRevisionNo);
}

export function reconcileRefreshedRevisionHistory(
  history: WorkflowRevisionHistory,
  refreshedPage: WorkflowRevisionPage,
): WorkflowRevisionHistory {
  const mergedHistory = mergeRevisionHistoryPage(history, refreshedPage);
  const oldestRefreshedRevisionNo = Math.min(...refreshedPage.items.map((revision) => revision.revision_no));
  const historyExtendsPastRefreshedPage = history.items.some(
    (revision) => revision.revision_no < oldestRefreshedRevisionNo,
  );

  return {
    ...mergedHistory,
    nextCursor: historyExtendsPastRefreshedPage ? history.nextCursor : mergedHistory.nextCursor,
  };
}

export function selectWorkflowRevision(
  history: WorkflowRevisionHistory,
  revisionNo: number,
): WorkflowRevisionHistory {
  return { ...history, selectedRevisionNo: revisionNo };
}

export function reconcileRestoredRevisionHistory(
  history: WorkflowRevisionHistory,
  refreshedPage: WorkflowRevisionPage,
  restoredRevision: WorkflowRevisionV2Summary,
  selectRestoredRevision: boolean,
): WorkflowRevisionHistory {
  const refreshItems = [restoredRevision, ...refreshedPage.items];
  const mergedHistory = reconcileRefreshedRevisionHistory(history, {
    ...refreshedPage,
    items: refreshItems,
  });

  return {
    ...mergedHistory,
    selectedRevisionNo: selectRestoredRevision
      ? restoredRevision.revision_no
      : history.selectedRevisionNo,
  };
}
