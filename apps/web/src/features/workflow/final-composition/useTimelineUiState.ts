import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
} from "react";

import type { V2FinalCompositionTimeline } from "../../../types-v2.ts";
import type {
  ShotTimelineMutation,
  ShotTimelineSnapTarget,
} from "./shotTimelineDomain.ts";
import { v2TimelineDuration } from "./v2TimelineModel.ts";

const BASE_PIXELS_PER_SECOND = 52;
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 4;

export type V2FinalCompositionTool = "select" | "blade";
export type V2FinalCompositionEditMode = "normal" | "ripple";

export type TimelineDocumentUiContract = {
  selectedClipIdsRef: MutableRefObject<string[]>;
  playheadRef: MutableRefObject<number>;
  editModeRef: MutableRefObject<V2FinalCompositionEditMode>;
  snapEnabledRef: MutableRefObject<boolean>;
  zoomRef: MutableRefObject<number>;
  assignSelectedClipIds: (ids: string[]) => void;
  applyMutationFeedback: (mutation: ShotTimelineMutation) => void;
  clearMutationFeedback: () => void;
};

function clampZoom(value: number) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

export function useTimelineUiState() {
  const [selectedClipIds, setSelectedClipIdsState] = useState<string[]>([]);
  const [playheadSeconds, setPlayheadSecondsState] = useState(0);
  const [tool, setToolState] = useState<V2FinalCompositionTool>("select");
  const [editMode, setEditModeState] = useState<V2FinalCompositionEditMode>("normal");
  const [snapEnabled, setSnapEnabledState] = useState(true);
  const [zoom, setZoomState] = useState(1);
  const [warning, setWarning] = useState("");
  const [snapTarget, setSnapTarget] = useState<ShotTimelineSnapTarget | null>(null);

  const selectedClipIdsRef = useRef(selectedClipIds);
  const playheadRef = useRef(playheadSeconds);
  const editModeRef = useRef(editMode);
  const snapEnabledRef = useRef(snapEnabled);
  const zoomRef = useRef(zoom);

  const assignSelectedClipIds = useCallback((ids: string[]) => {
    const next = [...new Set(ids)];
    selectedClipIdsRef.current = next;
    setSelectedClipIdsState(next);
  }, []);

  const setSelectedClipIds = useCallback(
    (ids: string[]) => assignSelectedClipIds(ids),
    [assignSelectedClipIds],
  );
  const setSelectedClipId = useCallback(
    (clipId: string | null) => assignSelectedClipIds(clipId ? [clipId] : []),
    [assignSelectedClipIds],
  );
  const setPlayheadSeconds = useCallback((seconds: number) => {
    const next = Math.max(0, seconds);
    playheadRef.current = next;
    setPlayheadSecondsState(next);
  }, []);
  const setTool = useCallback((next: V2FinalCompositionTool) => setToolState(next), []);
  const setEditMode = useCallback((next: V2FinalCompositionEditMode) => {
    editModeRef.current = next;
    setEditModeState(next);
  }, []);
  const setSnapEnabled = useCallback((next: boolean) => {
    snapEnabledRef.current = next;
    setSnapEnabledState(next);
  }, []);
  const setZoom = useCallback((next: number) => {
    const clamped = clampZoom(next);
    zoomRef.current = clamped;
    setZoomState(clamped);
  }, []);
  const fitTimeline = useCallback((
    timeline: V2FinalCompositionTimeline | null,
    viewportWidth?: number,
  ) => {
    const duration = timeline ? v2TimelineDuration(timeline) : 0;
    const next = viewportWidth && duration > 0
      ? clampZoom(viewportWidth / (duration * BASE_PIXELS_PER_SECOND))
      : 1;
    zoomRef.current = next;
    setZoomState(next);
    return next;
  }, []);
  const applyMutationFeedback = useCallback((mutation: ShotTimelineMutation) => {
    setWarning(mutation.warning ?? "");
    setSnapTarget(mutation.snapTarget);
  }, []);
  const clearMutationFeedback = useCallback(() => {
    setWarning("");
    setSnapTarget(null);
  }, []);
  const resetForSession = useCallback(() => {
    assignSelectedClipIds([]);
    clearMutationFeedback();
  }, [assignSelectedClipIds, clearMutationFeedback]);

  const documentContract = useMemo<TimelineDocumentUiContract>(() => ({
    selectedClipIdsRef,
    playheadRef,
    editModeRef,
    snapEnabledRef,
    zoomRef,
    assignSelectedClipIds,
    applyMutationFeedback,
    clearMutationFeedback,
  }), [applyMutationFeedback, assignSelectedClipIds, clearMutationFeedback]);

  return {
    tool,
    setTool,
    editMode,
    setEditMode,
    snapEnabled,
    setSnapEnabled,
    zoom,
    setZoom,
    fitTimeline,
    selectedClipIds,
    selectedClipId: selectedClipIds[0] ?? null,
    setSelectedClipIds,
    setSelectedClipId,
    playheadSeconds,
    setPlayheadSeconds,
    warning,
    snapTarget,
    resetForSession,
    documentContract,
  };
}
