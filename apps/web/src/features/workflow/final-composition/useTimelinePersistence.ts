import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
} from "react";

import { V2ApiError, v2Api } from "../../../api/v2Client.ts";
import type {
  V2CompositionCapabilities,
  V2FinalTimelineResponse,
  V2FinalTimelineSource,
  V2FinalTimelineUpdateResponse,
} from "../../../types-v2.ts";
import {
  createLatestSaveQueue,
  createRemoteStateEpoch,
  createTimelineSessionGuard,
  shotTimelineEquals,
  type TimelineSessionToken,
} from "./shotTimelineHistory.ts";
import type { TimelinePersistenceDocumentContract } from "./useTimelineDocument.ts";

const SIMPLE_SEQUENCE_CAPABILITIES: V2CompositionCapabilities = {
  render_mode: "simple_sequence",
  supports_timeline_controls: false,
  supports_shot_reorder: false,
  supports_bgm_volume_edit: false,
};

export type V2FinalCompositionConflict = {
  kind: "version-conflict";
  message: string;
};

export type LibrarySourceSelection = {
  entityId: string;
  assetId: string;
  mediaType: "video" | "audio";
};

type TimelineSaveSnapshot = {
  session: TimelineSessionToken;
  baseline: NonNullable<TimelinePersistenceDocumentContract[0]["current"]>;
  draft: NonNullable<TimelinePersistenceDocumentContract[1]["current"]>;
};

type TimelineSaveQueue = {
  request: (session: TimelineSessionToken) => Promise<V2FinalTimelineUpdateResponse | null>;
  isRunning: () => boolean;
};

export type TimelineSessionController = readonly [
  capture: () => TimelineSessionToken,
  isCurrent: (session: TimelineSessionToken) => boolean,
];

export type TimelineRenderPersistenceContract = readonly [
  session: TimelineSessionController,
  remoteState: ReturnType<typeof createRemoteStateEpoch>,
  capabilitiesRef: MutableRefObject<V2CompositionCapabilities>,
  conflictRef: MutableRefObject<V2FinalCompositionConflict | null>,
  load: (options?: { preserveDraft?: boolean }) => Promise<V2FinalTimelineResponse | null>,
  save: () => Promise<V2FinalTimelineUpdateResponse | null>,
  acceptTimelineResponse: (
    response: V2FinalTimelineResponse,
    preserveDraft?: boolean,
  ) => { keptDraft: boolean },
  setError: (message: string) => void,
  setVersionConflict: (message: string) => void,
];

export type TimelineRenderLifecycleBridge = [
  loadFinalVideo: (session: TimelineSessionToken) => Promise<unknown>,
  resetRenderProgress: () => void,
];

export function readableTimelineError(error: unknown) {
  const fallback = "Timeline request failed.";
  if (error instanceof V2ApiError) return error.message || error.code || fallback;
  return error instanceof Error ? error.message : fallback;
}

export function isTimelineVersionConflict(error: unknown, code?: string) {
  return error instanceof V2ApiError
    && [409, 412, 428].includes(error.status)
    && (!code || error.code === code);
}

export function useTimelinePersistence({
  workflowId,
  active,
  document,
  renderLifecycleRef,
}: {
  workflowId?: string | null;
  active: boolean;
  document: TimelinePersistenceDocumentContract;
  renderLifecycleRef: MutableRefObject<TimelineRenderLifecycleBridge>;
}) {
  const [sources, setSources] = useState<V2FinalTimelineSource[]>([]);
  const [capabilities, setCapabilities] = useState<V2CompositionCapabilities>(
    SIMPLE_SEQUENCE_CAPABILITIES,
  );
  const [staleClipIds, setStaleClipIds] = useState<string[]>([]);
  const [missingSourceClipIds, setMissingSourceClipIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setErrorState] = useState("");
  const [conflict, setConflict] = useState<V2FinalCompositionConflict | null>(null);
  const [
    baselineRef,
    draftRef,
    editRevisionRef,
    resetDocument,
    loadRemote,
    reconcileSave,
    resolveRemoteConflict,
    setExternalUpdate,
    ,
    resetUiForSession,
  ] = document;

  const capabilitiesRef = useRef(capabilities);
  const conflictRef = useRef(conflict);
  const sessionGuardRef = useRef(createTimelineSessionGuard());
  const remoteStateEpochRef = useRef(createRemoteStateEpoch());
  const performSaveRef = useRef<
    (snapshot: TimelineSaveSnapshot) => Promise<V2FinalTimelineUpdateResponse | null>
  >(async () => null);
  const saveQueueRef = useRef<TimelineSaveQueue | null>(null);

  const assignConflict = useCallback((next: V2FinalCompositionConflict | null) => {
    conflictRef.current = next;
    setConflict(next);
  }, []);
  const setVersionConflict = useCallback((message: string) => {
    assignConflict({ kind: "version-conflict", message });
    setExternalUpdate(true);
  }, [assignConflict, setExternalUpdate]);
  const applyResponseMetadata = useCallback((response: V2FinalTimelineResponse) => {
    setSources(response.available_sources);
    setCapabilities(response.composition_capabilities);
    capabilitiesRef.current = response.composition_capabilities;
    setStaleClipIds(response.stale_clip_ids);
    setMissingSourceClipIds(response.missing_source_clip_ids);
  }, []);
  const acceptTimelineResponse = useCallback((
    response: V2FinalTimelineResponse,
    preserveDraft = false,
  ) => {
    const result = loadRemote(response.timeline, preserveDraft);
    applyResponseMetadata(response);
    if (!result.keptDraft) assignConflict(null);
    return result;
  }, [applyResponseMetadata, assignConflict, loadRemote]);

  useLayoutEffect(() => {
    const transition = active
      ? sessionGuardRef.current.update(workflowId ?? null)
      : sessionGuardRef.current.update(null);
    if (transition.changed || !active) {
      remoteStateEpochRef.current.invalidate();
      resetDocument();
      resetUiForSession();
      assignConflict(null);
      setSources([]);
      setCapabilities(SIMPLE_SEQUENCE_CAPABILITIES);
      capabilitiesRef.current = SIMPLE_SEQUENCE_CAPABILITIES;
      setStaleClipIds([]);
      setMissingSourceClipIds([]);
      setLoading(false);
      setSaving(false);
      setErrorState("");
    }
  }, [
    active,
    assignConflict,
    resetDocument,
    resetUiForSession,
    workflowId,
  ]);

  useLayoutEffect(() => {
    const sessionGuard = sessionGuardRef.current;
    const remoteStateEpoch = remoteStateEpochRef.current;
    return () => {
      sessionGuard.update(null);
      remoteStateEpoch.invalidate();
    };
  }, []);

  const load = useCallback(async (
    { preserveDraft = false }: { preserveDraft?: boolean } = {},
  ) => {
    const session = sessionGuardRef.current.capture();
    const requestedWorkflowId = session.workflowId;
    if (!requestedWorkflowId) return null;
    const remoteEpoch = remoteStateEpochRef.current.claim();
    setLoading(true);
    setErrorState("");
    try {
      const response = await v2Api.getFinalTimeline(requestedWorkflowId);
      if (!sessionGuardRef.current.isCurrent(session)
        || !remoteStateEpochRef.current.isCurrent(remoteEpoch)) return null;
      const accepted = acceptTimelineResponse(response, preserveDraft);
      if (!preserveDraft && !accepted.keptDraft) {
        renderLifecycleRef.current[1]();
      }
      await renderLifecycleRef.current[0](session);
      return response;
    } catch (loadError) {
      if (sessionGuardRef.current.isCurrent(session)
        && remoteStateEpochRef.current.isCurrent(remoteEpoch)) {
        setErrorState(readableTimelineError(loadError));
      }
      return null;
    } finally {
      if (sessionGuardRef.current.isCurrent(session)
        && remoteStateEpochRef.current.isCurrent(remoteEpoch)) {
        setLoading(false);
      }
    }
  }, [acceptTimelineResponse, renderLifecycleRef]);

  useEffect(() => {
    if (active && workflowId) void load();
  }, [active, load, workflowId]);

  if (!saveQueueRef.current) {
    saveQueueRef.current = createLatestSaveQueue<
      TimelineSaveSnapshot,
      V2FinalTimelineUpdateResponse | null,
      TimelineSessionToken
    >(
      (session) => {
        if (!sessionGuardRef.current.isCurrent(session)) return null;
        const baseline = baselineRef.current;
        const draft = draftRef.current;
        if (!session.workflowId || !baseline || !draft || conflictRef.current) return null;
        if (shotTimelineEquals(draft, baseline)) return null;
        return { session, baseline, draft };
      },
      (snapshot) => performSaveRef.current(snapshot),
      (left, right) => (
        left.workflowId === right.workflowId && left.generation === right.generation
      ),
    );
  }

  performSaveRef.current = async (snapshot) => {
    const requestedWorkflowId = snapshot.session.workflowId;
    if (!requestedWorkflowId || !sessionGuardRef.current.isCurrent(snapshot.session)) return null;
    const remoteEpoch = remoteStateEpochRef.current.claim();
    setErrorState("");
    try {
      const response = await v2Api.saveFinalTimeline(requestedWorkflowId, {
        expected_version: snapshot.baseline.version,
        timeline: snapshot.draft,
      });
      if (!sessionGuardRef.current.isCurrent(snapshot.session)
        || !remoteStateEpochRef.current.isCurrent(remoteEpoch)) return null;
      reconcileSave(snapshot.draft, response.timeline);
      assignConflict(null);
      return response;
    } catch (saveError) {
      if (!sessionGuardRef.current.isCurrent(snapshot.session)
        || !remoteStateEpochRef.current.isCurrent(remoteEpoch)) return null;
      if (isTimelineVersionConflict(saveError)) {
        const message = "Timeline changed elsewhere. Choose Keep local to rebase your draft or Reload remote to discard it.";
        setVersionConflict(message);
        setErrorState(message);
      } else {
        setErrorState(readableTimelineError(saveError));
      }
      return null;
    }
  };

  const save = useCallback(() => {
    const session = sessionGuardRef.current.capture();
    const queue = saveQueueRef.current!;
    const pending = queue.request(session);
    setSaving(true);
    void pending.then(
      () => {
        if (sessionGuardRef.current.isCurrent(session) && !queue.isRunning()) setSaving(false);
      },
      (saveError) => {
        if (sessionGuardRef.current.isCurrent(session)) {
          if (!queue.isRunning()) setSaving(false);
          setErrorState(readableTimelineError(saveError));
        }
      },
    );
    return pending;
  }, []);

  const resolveConflictWithRemote = useCallback(async (
    resolution: "keep-local" | "reload-remote",
  ) => {
    const session = sessionGuardRef.current.capture();
    const requestedWorkflowId = session.workflowId;
    const requestDraft = draftRef.current;
    if (!requestedWorkflowId || !requestDraft || !conflictRef.current) return null;
    const remoteEpoch = remoteStateEpochRef.current.claim();
    const requestEditRevision = editRevisionRef.current;
    setLoading(true);
    setErrorState("");
    try {
      const response = await v2Api.getFinalTimeline(requestedWorkflowId);
      if (!sessionGuardRef.current.isCurrent(session)
        || !remoteStateEpochRef.current.isCurrent(remoteEpoch)) return null;
      resolveRemoteConflict(
        response.timeline,
        resolution,
        requestDraft,
        requestEditRevision,
      );
      applyResponseMetadata(response);
      assignConflict(null);
      return response;
    } catch (loadError) {
      if (sessionGuardRef.current.isCurrent(session)
        && remoteStateEpochRef.current.isCurrent(remoteEpoch)) {
        setErrorState(readableTimelineError(loadError));
      }
      return null;
    } finally {
      if (sessionGuardRef.current.isCurrent(session)
        && remoteStateEpochRef.current.isCurrent(remoteEpoch)) {
        setLoading(false);
      }
    }
  }, [applyResponseMetadata, assignConflict, draftRef, editRevisionRef, resolveRemoteConflict]);
  const keepLocal = useCallback(
    () => resolveConflictWithRemote("keep-local"),
    [resolveConflictWithRemote],
  );
  const reloadRemote = useCallback(
    () => resolveConflictWithRemote("reload-remote"),
    [resolveConflictWithRemote],
  );
  const registerLibrarySource = useCallback(async (selection: LibrarySourceSelection) => {
    const session = sessionGuardRef.current.capture();
    const requestedWorkflowId = session.workflowId;
    if (!requestedWorkflowId) return null;
    setErrorState("");
    try {
      const response = await v2Api.importFinalTimelineSource(requestedWorkflowId, {
        library_entity_id: selection.entityId,
        library_asset_id: selection.assetId,
        expected_media_type: selection.mediaType,
      });
      if (!sessionGuardRef.current.isCurrent(session)) return null;
      setSources((current) => [
        ...current.filter((item) => item.version_id !== response.source.version_id),
        response.source,
      ]);
      return response.source;
    } catch (importError) {
      if (sessionGuardRef.current.isCurrent(session)) {
        setErrorState(readableTimelineError(importError));
      }
      return null;
    }
  }, []);

  const session = useMemo<TimelineSessionController>(() => [
    () => sessionGuardRef.current.capture(),
    (candidate) => sessionGuardRef.current.isCurrent(candidate),
  ], []);
  const renderContract = useMemo<TimelineRenderPersistenceContract>(() => [
    session,
    remoteStateEpochRef.current,
    capabilitiesRef,
    conflictRef,
    load,
    save,
    acceptTimelineResponse,
    setErrorState,
    setVersionConflict,
  ], [
    acceptTimelineResponse,
    load,
    save,
    session,
    setVersionConflict,
  ]);

  return [{
    sources,
    capabilities,
    staleClipIds,
    missingSourceClipIds,
    loading,
    saving,
    error,
    conflict,
    load,
    save,
    keepLocal,
    reloadRemote,
    registerLibrarySource,
  }, renderContract] as const;
}
