import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import { V2ApiError, v2Api } from "../../../api/v2Client.ts";
import type {
  AssetVersionV2,
  V2FinalCompositionTimeline,
  V2FinalTimelineRenderStartResponse,
  V2FinalTimelineRenderStateResponse,
  WorkflowV2,
} from "../../../types-v2.ts";
import {
  selectedAssetForSlot,
  selectV2FinalVideoSlot,
} from "../../../workflow-v2/selectors.ts";
import {
  activeRenderIdFromPayload,
  claimFinalRenderCompletion,
  finalRenderCancelAction,
  finalRenderEventHints,
  finalRenderGetFailureAction,
  finalRenderSessionMatches,
  flushTimelineForRender,
  isFinalRenderTerminal,
  nextFinalRenderPoll,
  type FinalCompositionEventDetail,
  type FinalRenderEventHint,
  type FinalRenderSessionIdentity,
} from "./finalRenderSession.ts";
import {
  FINAL_COMPOSITION_EVENT_NAME,
  shouldReloadFinalCompositionTimeline,
} from "./finalCompositionEvents.ts";
import { shotTimelineEquals, type TimelineSessionToken } from "./shotTimelineHistory.ts";
import type { TimelinePersistenceDocumentContract } from "./useTimelineDocument.ts";
import {
  isTimelineVersionConflict,
  readableTimelineError,
  type TimelineOperationIdentity,
  type TimelineRenderPersistenceContract,
} from "./useTimelinePersistence.ts";
import {
  classifyFinalCompositionError,
  supportsAdvancedTimelineEditor,
  type V2FinalCompositionIssue,
} from "./v2FinalCompositionPolicy.ts";

export type FinalRenderDocumentContract = TimelinePersistenceDocumentContract;

function finalVideoFromWorkflow(value: unknown): AssetVersionV2 | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const workflow = value as WorkflowV2;
  if (!Array.isArray(workflow.items)
    || !Array.isArray(workflow.slots)
    || !Array.isArray(workflow.asset_versions)) return null;
  const slot = selectV2FinalVideoSlot(workflow);
  return selectedAssetForSlot(workflow, slot ?? undefined) ?? null;
}

export function useFinalRenderSession({
  active,
  workflowId,
  onWorkflowRefresh,
  document,
  persistence,
}: {
  active: boolean;
  workflowId?: string | null;
  onWorkflowRefresh?: (workflowId: string) => Promise<unknown> | unknown;
  document: FinalRenderDocumentContract;
  persistence: TimelineRenderPersistenceContract;
}) {
  const [finalVideo, setFinalVideo] = useState<AssetVersionV2 | null>(null);
  const [autoPlayFinalVideo, setAutoPlayFinalVideo] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [renderJob, setRenderJob] = useState<V2FinalTimelineRenderStartResponse | null>(null);
  const [renderState, setRenderState] = useState<V2FinalTimelineRenderStateResponse | null>(null);
  const [renderHint, setRenderHint] = useState<FinalRenderEventHint | null>(null);
  const [renderSessionError, setRenderSessionError] = useState("");
  const [renderIssue, setRenderIssue] = useState<V2FinalCompositionIssue | null>(null);
  const [cancellingRender, setCancellingRender] = useState(false);
  const [baselineRef, draftRef, , , , , , , finalizeGesture] = document;
  const [
    sessionController,
    operations,
    capabilitiesRef,
    conflictRef,
    load,
    save,
    acceptTimelineResponse,
    setError,
    setVersionConflict,
  ] = persistence;
  const [captureSession, isSessionCurrent] = sessionController;
  const [beginOperation, isOperationCurrent] = operations;

  const activeRef = useRef(active);
  const renderingRef = useRef(rendering);
  const renderJobRef = useRef(renderJob);
  const renderStateRef = useRef(renderState);
  const renderSessionRef = useRef<FinalRenderSessionIdentity | null>(null);
  const renderGenerationRef = useRef(0);
  const renderStateRequestRef = useRef(0);
  const renderCancelRequestRef = useRef(0);
  const renderPollBackoffRef = useRef(0);
  const renderPollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancellingRenderRef = useRef(false);
  const onWorkflowRefreshRef = useRef(onWorkflowRefresh);
  const completedRenderSessionsRef = useRef(new Set<string>());
  const pollRenderRef = useRef<
    (identity: FinalRenderSessionIdentity, resetBackoff?: boolean) => Promise<void>
  >(async () => {});

  onWorkflowRefreshRef.current = onWorkflowRefresh;

  const clearRenderPollTimer = useCallback(() => {
    if (renderPollTimerRef.current !== null) {
      clearTimeout(renderPollTimerRef.current);
      renderPollTimerRef.current = null;
    }
  }, []);
  const invalidateRenderSession = useCallback(() => {
    clearRenderPollTimer();
    renderGenerationRef.current += 1;
    renderStateRequestRef.current += 1;
    renderCancelRequestRef.current += 1;
    renderPollBackoffRef.current = 0;
    renderSessionRef.current = null;
    renderJobRef.current = null;
    renderStateRef.current = null;
    renderingRef.current = false;
    cancellingRenderRef.current = false;
    completedRenderSessionsRef.current.clear();
  }, [clearRenderPollTimer]);
  const resetRenderProgress = useCallback(() => {
    invalidateRenderSession();
    setRenderJob(null);
    setRenderState(null);
    setRenderHint(null);
    setRenderSessionError("");
    setRenderIssue(null);
    setCancellingRender(false);
    setRendering(false);
  }, [invalidateRenderSession]);

  useLayoutEffect(() => {
    activeRef.current = active;
    resetRenderProgress();
    setFinalVideo(null);
    setAutoPlayFinalVideo(false);
    return () => {
      activeRef.current = false;
      invalidateRenderSession();
    };
  }, [active, invalidateRenderSession, resetRenderProgress, workflowId]);

  const applyFinalVideoWorkflow = useCallback((workflow: unknown, autoplay = false) => {
    const next = finalVideoFromWorkflow(workflow);
    if (!next) return null;
    setFinalVideo(next);
    setAutoPlayFinalVideo(autoplay);
    return next;
  }, []);
  const loadFinalVideo = useCallback(async (
    session: TimelineSessionToken,
    workflow?: unknown,
    autoplay = false,
    operation?: TimelineOperationIdentity,
  ) => {
    const isCurrent = () => (
      isSessionCurrent(session)
      && (operation === undefined || isOperationCurrent(operation))
    );
    if (!isCurrent()) return null;
    try {
      const candidate = workflow ?? await v2Api.workflow(session.workflowId!);
      if (!isCurrent()) return null;
      return applyFinalVideoWorkflow(candidate, autoplay);
    } catch {
      return null;
    }
  }, [applyFinalVideoWorkflow, isOperationCurrent, isSessionCurrent]);
  const renderIdentityIsCurrent = useCallback((identity: FinalRenderSessionIdentity) => (
    isSessionCurrent(identity.session)
    && finalRenderSessionMatches(renderSessionRef.current, identity, activeRef.current)
  ), [isSessionCurrent]);
  const scheduleRenderPoll = useCallback((
    identity: FinalRenderSessionIdentity,
    resetBackoff = false,
  ) => {
    if (!renderIdentityIsCurrent(identity)) return;
    clearRenderPollTimer();
    const next = nextFinalRenderPoll(renderPollBackoffRef.current, resetBackoff);
    renderPollBackoffRef.current = next.nextBackoffIndex;
    renderPollTimerRef.current = setTimeout(() => {
      renderPollTimerRef.current = null;
      void pollRenderRef.current(identity);
    }, next.delayMs);
  }, [clearRenderPollTimer, renderIdentityIsCurrent]);
  const applyAuthoritativeRenderState = useCallback((
    identity: FinalRenderSessionIdentity,
    state: V2FinalTimelineRenderStateResponse,
    resetBackoff = false,
  ) => {
    if (!renderIdentityIsCurrent(identity)
      || state.workflow_id !== identity.session.workflowId
      || state.render_id !== identity.renderId) return false;
    renderStateRef.current = state;
    setRenderState(state);
    setRenderHint(null);
    setRenderSessionError("");
    const issue = classifyFinalCompositionError(state.error_code);
    setRenderIssue(issue);
    setError("");
    if (isFinalRenderTerminal(state.status)) {
      clearRenderPollTimer();
      renderingRef.current = false;
      cancellingRenderRef.current = false;
      setRendering(false);
      setCancellingRender(false);
      if (state.status === "completed"
        && claimFinalRenderCompletion(completedRenderSessionsRef.current, identity)) {
        setRenderIssue(null);
        const completionOperation = beginOperation(true);
        const completionIsCurrent = () => (
          isOperationCurrent(completionOperation) && renderIdentityIsCurrent(identity)
        );
        void (async () => {
          const timeline = await load({
            preserveDraft: true,
            operation: completionOperation,
          });
          if (!timeline || !completionIsCurrent()) return;
          const refreshedWorkflow = await onWorkflowRefreshRef.current?.(
            identity.session.workflowId!,
          );
          if (!completionIsCurrent()) return;
          await loadFinalVideo(
            identity.session,
            refreshedWorkflow,
            true,
            completionOperation,
          );
        })();
      }
      return true;
    }
    renderingRef.current = true;
    cancellingRenderRef.current = state.status === "cancellation_requested";
    setRendering(true);
    setCancellingRender(state.status === "cancellation_requested");
    scheduleRenderPoll(identity, resetBackoff);
    return true;
  }, [
    clearRenderPollTimer,
    load,
    loadFinalVideo,
    beginOperation,
    isOperationCurrent,
    renderIdentityIsCurrent,
    scheduleRenderPoll,
    setError,
  ]);
  const pollRender = useCallback(async (
    identity: FinalRenderSessionIdentity,
    resetBackoff = false,
  ) => {
    if (!renderIdentityIsCurrent(identity) || !identity.session.workflowId) return;
    clearRenderPollTimer();
    if (resetBackoff) renderPollBackoffRef.current = 0;
    const requestId = ++renderStateRequestRef.current;
    try {
      const state = await v2Api.getFinalTimelineRender(
        identity.session.workflowId,
        identity.renderId,
      );
      if (requestId !== renderStateRequestRef.current || !renderIdentityIsCurrent(identity)) return;
      applyAuthoritativeRenderState(identity, state, resetBackoff);
    } catch (pollError) {
      if (requestId !== renderStateRequestRef.current || !renderIdentityIsCurrent(identity)) return;
      const status = pollError instanceof V2ApiError ? pollError.status : null;
      if (finalRenderGetFailureAction(status) === "retry") {
        scheduleRenderPoll(identity);
      } else {
        const message = status === 404
          ? "Final render is no longer available. Start a new render to retry."
          : `Final render status could not be loaded: ${readableTimelineError(pollError)} Start a new render to retry.`;
        resetRenderProgress();
        setRenderSessionError(message);
        setError("");
      }
    }
  }, [
    applyAuthoritativeRenderState,
    clearRenderPollTimer,
    renderIdentityIsCurrent,
    resetRenderProgress,
    scheduleRenderPoll,
    setError,
  ]);
  pollRenderRef.current = pollRender;

  useEffect(() => {
    const handleTimelineEvent = (event: Event) => {
      const detail = (event as CustomEvent<FinalCompositionEventDetail>).detail;
      if (!activeRef.current || detail?.workflowId !== workflowId) return;
      const eventTypes = detail.events?.map((item) => item.event_type) ?? detail.eventTypes ?? [];
      if (shouldReloadFinalCompositionTimeline(eventTypes)) {
        void load({ preserveDraft: true });
      }
      const identity = renderSessionRef.current;
      if (!identity || !renderIdentityIsCurrent(identity)) return;
      const hints = finalRenderEventHints(detail, identity, activeRef.current);
      if (!hints.length) return;
      const fastHint = [...hints].reverse().find((hint) => hint.kind === "fast-state");
      if (fastHint && !isFinalRenderTerminal(renderStateRef.current?.status ?? "")) {
        setRenderHint(fastHint);
        renderingRef.current = true;
        setRendering(true);
      }
      clearRenderPollTimer();
      const terminalHint = hints.some((hint) => hint.kind === "authoritative-get");
      const resetBackoff = !terminalHint && hints.some((hint) => hint.resetBackoff);
      void pollRenderRef.current(identity, resetBackoff);
    };
    window.addEventListener(FINAL_COMPOSITION_EVENT_NAME, handleTimelineEvent);
    return () => window.removeEventListener(FINAL_COMPOSITION_EVENT_NAME, handleTimelineEvent);
  }, [clearRenderPollTimer, load, renderIdentityIsCurrent, workflowId]);

  const beginRenderSession = useCallback((
    session: TimelineSessionToken,
    renderGeneration: number,
    operation: TimelineOperationIdentity,
    start: V2FinalTimelineRenderStartResponse,
  ) => {
    if (!activeRef.current
      || !isSessionCurrent(session)
      || !isOperationCurrent(operation)
      || renderGenerationRef.current !== renderGeneration
      || start.workflow_id !== session.workflowId) return null;
    clearRenderPollTimer();
    renderStateRequestRef.current += 1;
    renderPollBackoffRef.current = 0;
    const identity: FinalRenderSessionIdentity = {
      session,
      renderGeneration,
      renderId: start.render_id,
    };
    renderSessionRef.current = identity;
    renderJobRef.current = start;
    renderStateRef.current = null;
    renderingRef.current = true;
    cancellingRenderRef.current = false;
    setRenderJob(start);
    setRenderState(null);
    setRenderHint(null);
    setRenderSessionError("");
    setRenderIssue(null);
    setAutoPlayFinalVideo(false);
    setCancellingRender(false);
    setRendering(true);
    void pollRenderRef.current(identity, true);
    return identity;
  }, [clearRenderPollTimer, isOperationCurrent, isSessionCurrent]);

  const render = useCallback(async () => {
    const session = captureSession();
    const requestedWorkflowId = session.workflowId;
    if (!activeRef.current
      || !requestedWorkflowId
      || !draftRef.current
      || !baselineRef.current
      || renderingRef.current) return null;
    let attached = false;
    const operation = beginOperation(false, () => {
      if (!attached) resetRenderProgress();
    });
    const renderGeneration = ++renderGenerationRef.current;
    clearRenderPollTimer();
    renderStateRequestRef.current += 1;
    renderCancelRequestRef.current += 1;
    renderSessionRef.current = null;
    renderJobRef.current = null;
    renderStateRef.current = null;
    renderingRef.current = true;
    cancellingRenderRef.current = false;
    setRendering(true);
    setCancellingRender(false);
    setRenderJob(null);
    setRenderState(null);
    setRenderHint(null);
    setRenderSessionError("");
    setRenderIssue(null);
    setAutoPlayFinalVideo(false);
    setError("");
    let timeline: V2FinalCompositionTimeline | null = baselineRef.current;
    try {
      if (supportsAdvancedTimelineEditor(capabilitiesRef.current)) {
        timeline = await flushTimelineForRender({
          session,
          isSessionCurrent: () => activeRef.current && isOperationCurrent(operation),
          finalizeGesture,
          readDraft: () => draftRef.current,
          readBaseline: () => baselineRef.current,
          equals: shotTimelineEquals,
          hasConflict: () => conflictRef.current !== null,
          save: () => save(operation),
        });
      } else {
        const response = await v2Api.getFinalTimeline(requestedWorkflowId);
        if (!activeRef.current
          || !isSessionCurrent(session)
          || !isOperationCurrent(operation)) return null;
        acceptTimelineResponse(response);
        timeline = response.timeline;
      }
      if (!timeline
        || !activeRef.current
        || !isSessionCurrent(session)
        || !isOperationCurrent(operation)) return null;
      const response = await v2Api.renderFinalTimeline(requestedWorkflowId, {
        timeline_id: timeline.timeline_id,
        timeline_version: timeline.version,
      });
      attached = beginRenderSession(
        session,
        renderGeneration,
        operation,
        response,
      ) !== null;
      return attached ? response : null;
    } catch (renderError) {
      if (activeRef.current
        && isSessionCurrent(session)
        && isOperationCurrent(operation)) {
        const activeRenderId = renderError instanceof V2ApiError
          ? activeRenderIdFromPayload(renderError.payload)
          : null;
        const activeTimeline = timeline ?? baselineRef.current;
        if (activeRenderId && activeTimeline) {
          const activeStart: V2FinalTimelineRenderStartResponse = {
            workflow_id: requestedWorkflowId,
            render_id: activeRenderId,
            status: "queued",
            timeline_id: activeTimeline.timeline_id,
            timeline_version: activeTimeline.version,
            events_cursor: 0,
          };
          attached = beginRenderSession(
            session,
            renderGeneration,
            operation,
            activeStart,
          ) !== null;
          if (attached) return activeStart;
        } else if (isTimelineVersionConflict(renderError, "v2_timeline_version_conflict")) {
          setVersionConflict(
            "Timeline changed elsewhere. Resolve the version conflict before rendering.",
          );
        }
        const issue = renderError instanceof V2ApiError
          ? classifyFinalCompositionError(renderError.code)
          : null;
        setRenderIssue(issue);
        setError(issue ? "" : readableTimelineError(renderError));
      }
      return null;
    } finally {
      if (!attached
        && isOperationCurrent(operation)) {
        renderingRef.current = false;
        setRendering(false);
      }
    }
  }, [
    acceptTimelineResponse,
    baselineRef,
    beginRenderSession,
    capabilitiesRef,
    clearRenderPollTimer,
    conflictRef,
    draftRef,
    finalizeGesture,
    beginOperation,
    isOperationCurrent,
    resetRenderProgress,
    save,
    captureSession,
    isSessionCurrent,
    setError,
    setVersionConflict,
  ]);

  const cancelRender = useCallback(async () => {
    const identity = renderSessionRef.current;
    if (!identity || !renderIdentityIsCurrent(identity)) return null;
    const currentState = renderStateRef.current;
    const currentStatus = currentState?.status ?? renderJobRef.current?.status ?? "queued";
    const cancelAction = finalRenderCancelAction(currentStatus);
    if (cancelAction === "terminal" || cancelAction === "poll" || cancellingRenderRef.current) {
      return currentState;
    }
    const requestedWorkflowId = identity.session.workflowId;
    if (!requestedWorkflowId) return null;
    clearRenderPollTimer();
    renderStateRequestRef.current += 1;
    const requestId = ++renderCancelRequestRef.current;
    cancellingRenderRef.current = true;
    setCancellingRender(true);
    setError("");
    try {
      const state = await v2Api.cancelFinalTimelineRender(
        requestedWorkflowId,
        identity.renderId,
      );
      if (requestId !== renderCancelRequestRef.current || !renderIdentityIsCurrent(identity)) {
        return null;
      }
      applyAuthoritativeRenderState(identity, state, state.status === "cancellation_requested");
      return state;
    } catch (cancelError) {
      if (requestId === renderCancelRequestRef.current && renderIdentityIsCurrent(identity)) {
        cancellingRenderRef.current = false;
        setCancellingRender(false);
        setError(readableTimelineError(cancelError));
        scheduleRenderPoll(identity, true);
      }
      return null;
    }
  }, [
    applyAuthoritativeRenderState,
    clearRenderPollTimer,
    renderIdentityIsCurrent,
    scheduleRenderPoll,
    setError,
  ]);

  return [{
    finalVideo,
    autoPlayFinalVideo,
    rendering,
    cancellingRender,
    renderJob,
    renderState,
    renderHint,
    renderSessionError,
    renderIssue,
    render,
    cancelRender,
  }, loadFinalVideo, resetRenderProgress] as const;
}
