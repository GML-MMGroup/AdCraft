import { useRef } from "react";

import type {
  V2FinalTimelineSource,
} from "../../../types-v2.ts";
import {
  moveTimelineClipToTrack,
  useTimelineDocument,
  type V2FinalCompositionEditMode,
  type V2FinalCompositionTool,
} from "./useTimelineDocument.ts";
import { useFinalRenderSession } from "./useFinalRenderSession.ts";
import {
  useTimelinePersistence,
  type TimelineRenderLifecycleBridge,
  type V2FinalCompositionConflict,
} from "./useTimelinePersistence.ts";
import { supportsAdvancedTimelineEditor } from "./v2FinalCompositionPolicy.ts";

export {
  moveTimelineClipToTrack,
  type V2FinalCompositionConflict,
  type V2FinalCompositionEditMode,
  type V2FinalCompositionTool,
};

export type CompositionEditorSession = {
  workflowId: string;
  generation: number;
  active: boolean;
};

export type ScopedTimelineSource = {
  session: CompositionEditorSession;
  source: V2FinalTimelineSource;
};

export function resolveScopedTimelineSource(
  pending: ScopedTimelineSource | null,
  currentSession: CompositionEditorSession,
  sources: V2FinalTimelineSource[],
) {
  if (!pending
    || !pending.session.active
    || !currentSession.active
    || pending.session.workflowId !== currentSession.workflowId
    || pending.session.generation !== currentSession.generation) return null;
  return sources.find((source) => source.asset_id === pending.source.asset_id
    && source.version_id === pending.source.version_id
    && source.media_type === pending.source.media_type) ?? null;
}

export function useV2FinalCompositionEditor({
  workflowId,
  active,
  onWorkflowRefresh,
}: {
  workflowId?: string | null;
  active: boolean;
  onWorkflowRefresh?: (workflowId: string) => Promise<unknown> | unknown;
}) {
  const [document, timelineDocument] = useTimelineDocument();
  const renderLifecycleRef = useRef<TimelineRenderLifecycleBridge>([
    async () => null,
    () => {},
  ]);
  const [persistence, renderPersistence] = useTimelinePersistence({
    workflowId,
    active,
    document: timelineDocument,
    renderLifecycleRef,
  });
  const [finalRender, loadFinalVideo, resetRenderProgress] = useFinalRenderSession({
    active,
    workflowId,
    onWorkflowRefresh,
    document: timelineDocument,
    persistence: renderPersistence,
  });
  renderLifecycleRef.current[0] = loadFinalVideo;
  renderLifecycleRef.current[1] = resetRenderProgress;

  return {
    ...document,
    ...persistence,
    ...finalRender,
    advancedEditorEnabled: supportsAdvancedTimelineEditor(persistence.capabilities),
    selectedClip: document.draft?.clips.find(
      (clip) => clip.clip_id === document.selectedClipId,
    ) ?? null,
    importLibrarySource: persistence.registerLibrarySource,
  };
}
