import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type MutableRefObject,
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
import type { TimelineRenderPersistenceContract } from "./useTimelinePersistence.ts";
import {
  classifyFinalCompositionError,
  supportsAdvancedTimelineEditor,
  type V2FinalCompositionIssue,
} from "./v2FinalCompositionPolicy.ts";

export type FinalRenderDocumentContract = {
  baselineRef: MutableRefObject<V2FinalCompositionTimeline | null>;
  draftRef: MutableRefObject<V2FinalCompositionTimeline | null>;
  finalizeGesture: () => void;
};

function readableError(error: unknown) {
  if (error instanceof V2ApiError) return error.message || error.code || "Timeline request failed.";
  return error instanceof Error ? error.message : "Timeline request failed.";
}

function finalVideoFromWorkflow(value: unknown): AssetVersionV2 | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const workflow = value as WorkflowV2;
  if (!Array.isArray(workflow.items)
    || !Array.isArray(workflow.slots)
    || !Array.isArray(workflow.asset_versions)) return null;
  const slot = selectV2FinalVideoSlot(workflow);
  return selectedAssetForSlot(workflow, slot ?? undefined) ?? null;
}

function isRenderVersionConflict(error: unknown) {
  return error instanceof V2ApiError
    && [409, 412, 428].includes(error.status)
    && error.code === "v2_timeline_version_conflict";
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
  ) => {
    try {
      const candidate = workflow ?? await v2Api.workflow(session.workflowId!);
      if (!persistence.session.isCurrent(session)) return null;
      return applyFinalVideoWorkflow(candidate, autoplay);
    } catch {
      return null;
    }
  }, [applyFinalVideoWorkflow, persistence.session]);
  const renderIdentityIsCurrent = useCallback((identity: FinalRenderSessionIdentity) => (
    persistence.session.isCurrent(identity.session)
    && finalRenderSessionMatches(renderSessionRef.current, identity, activeRef.current)
  ), [persistence.session]);
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
    persistence.setError("");
    if (isFinalRenderTerminal(state.status)) {
      clearRenderPollTimer();
      renderingRef.current = false;
      cancellingRenderRef.current = false;
      setRendering(false);
      setCancellingRender(false);
      if (state.status === "completed"
        && claimFinalRenderCompletion(completedRenderSessionsRef.current, identity)) {
        setRenderIssue(null);
        void (async () => {
          await persistence.load({ preserveDraft: true });
          const refreshedWorkflow = await onWorkflowRefreshRef.current?.(
            identity.session.workflowId!,
          );
          await loadFinalVideo(identity.session, refreshedWorkflow, true);
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
    loadFinalVideo,
    persistence,
    renderIdentityIsCurrent,
    scheduleRenderPoll,
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
          : `Final render status could not be loaded: ${readableError(pollError)} Start a new render to retry.`;
        resetRenderProgress();
        setRenderSessionError(message);
        persistence.setError("");
      }
    }
  }, [
    applyAuthoritativeRenderState,
    clearRenderPollTimer,
    persistence,
    renderIdentityIsCurrent,
    resetRenderProgress,
    scheduleRenderPoll,
  ]);
  pollRenderRef.current = pollRender;

  useEffect(() => {
    const handleTimelineEvent = (event: Event) => {
      const detail = (event as CustomEvent<FinalCompositionEventDetail>).detail;
      if (!activeRef.current || detail?.workflowId !== workflowId) return;
      const eventTypes = detail.events?.map((item) => item.event_type) ?? detail.eventTypes ?? [];
      if (shouldReloadFinalCompositionTimeline(eventTypes)) {
        void persistence.load({ preserveDraft: true });
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
  }, [clearRenderPollTimer, persistence, renderIdentityIsCurrent, workflowId]);

  const beginRenderSession = useCallback((
    session: TimelineSessionToken,
    renderGeneration: number,
    start: V2FinalTimelineRenderStartResponse,
  ) => {
    if (!activeRef.current
      || !persistence.session.isCurrent(session)
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
  }, [clearRenderPollTimer, persistence.session]);

  const render = useCallback(async () => {
    const session = persistence.session.capture();
    const requestedWorkflowId = session.workflowId;
    if (!activeRef.current
      || !requestedWorkflowId
      || !document.draftRef.current
      || !document.baselineRef.current
      || renderingRef.current) return null;
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
    persistence.setError("");
    let attached = false;
    let timeline: V2FinalCompositionTimeline | null = document.baselineRef.current;
    try {
      if (supportsAdvancedTimelineEditor(persistence.capabilitiesRef.current)) {
        timeline = await flushTimelineForRender({
          session,
          isSessionCurrent: (candidate) => activeRef.current
            && renderGenerationRef.current === renderGeneration
            && persistence.session.isCurrent(candidate),
          finalizeGesture: document.finalizeGesture,
          readDraft: () => document.draftRef.current,
          readBaseline: () => document.baselineRef.current,
          equals: shotTimelineEquals,
          hasConflict: () => persistence.conflictRef.current !== null,
          save: persistence.save,
        });
      } else {
        const response = await v2Api.getFinalTimeline(requestedWorkflowId);
        if (!activeRef.current
          || renderGenerationRef.current !== renderGeneration
          || !persistence.session.isCurrent(session)) return null;
        persistence.acceptTimelineResponse(response);
        timeline = response.timeline;
      }
      if (!timeline
        || !activeRef.current
        || renderGenerationRef.current !== renderGeneration
        || !persistence.session.isCurrent(session)) return null;
      const response = await v2Api.renderFinalTimeline(requestedWorkflowId, {
        timeline_id: timeline.timeline_id,
        timeline_version: timeline.version,
      });
      attached = beginRenderSession(session, renderGeneration, response) !== null;
      return response;
    } catch (renderError) {
      if (activeRef.current
        && renderGenerationRef.current === renderGeneration
        && persistence.session.isCurrent(session)) {
        const activeRenderId = renderError instanceof V2ApiError
          ? activeRenderIdFromPayload(renderError.payload)
          : null;
        const activeTimeline = timeline ?? document.baselineRef.current;
        if (activeRenderId && activeTimeline) {
          const activeStart: V2FinalTimelineRenderStartResponse = {
            workflow_id: requestedWorkflowId,
            render_id: activeRenderId,
            status: "queued",
            timeline_id: activeTimeline.timeline_id,
            timeline_version: activeTimeline.version,
            events_cursor: 0,
          };
          attached = beginRenderSession(session, renderGeneration, activeStart) !== null;
          if (attached) return activeStart;
        } else if (isRenderVersionConflict(renderError)) {
          persistence.setVersionConflict(
            "Timeline changed elsewhere. Resolve the version conflict before rendering.",
          );
        }
        const issue = renderError instanceof V2ApiError
          ? classifyFinalCompositionError(renderError.code)
          : null;
        setRenderIssue(issue);
        persistence.setError(issue ? "" : readableError(renderError));
      }
      return null;
    } finally {
      if (!attached
        && renderGenerationRef.current === renderGeneration
        && persistence.session.isCurrent(session)) {
        renderingRef.current = false;
        setRendering(false);
      }
    }
  }, [
    beginRenderSession,
    clearRenderPollTimer,
    document,
    persistence,
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
    persistence.setError("");
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
        persistence.setError(readableError(cancelError));
        scheduleRenderPoll(identity, true);
      }
      return null;
    }
  }, [
    applyAuthoritativeRenderState,
    clearRenderPollTimer,
    persistence,
    renderIdentityIsCurrent,
    scheduleRenderPoll,
  ]);

  return {
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
    loadFinalVideo,
    resetRenderProgress,
  };
}
