import { useCallback, useMemo, useState } from "react";
import { api } from "../../../api/client.ts";
import { v2Api } from "../../../api/v2Client.ts";
import type {
  FinalCompositionTimeline,
  FinalCompositionTimelineRenderRequest,
  FinalCompositionTimelineResponse,
  FinalCompositionTimelineSaveRequest,
} from "../../../types.ts";
import type { V2TimelineClipCreateRequest, WorkflowV2 } from "../../../types-v2.ts";

export type FinalCompositionTimelineView = {
  loading: boolean;
  saving: boolean;
  rendering: boolean;
  timeline: FinalCompositionTimeline | null;
  draft: FinalCompositionTimeline | null;
  response: FinalCompositionTimelineResponse | null;
  conflict: string | null;
  error: string | null;
  renderError: string | null;
  eventDirty: boolean;
};

export type FinalCompositionModuleArgs = {
  workflowId: string | null;
  isV2: boolean;
  onWorkflowRefresh?: (workflowId: string) => Promise<void> | void;
  onV2Workflow?: (workflow: WorkflowV2) => Promise<void> | void;
  onError?: (message: string) => void;
};

export type FinalCompositionModule = {
  timelineView: FinalCompositionTimelineView;
  loadTimeline: (options?: { preserveDraft?: boolean; eventDirty?: boolean }) => Promise<void>;
  saveTimeline: () => Promise<void>;
  renderCandidate: () => Promise<void>;
  createTimelineClip: (sourceAssetId: string, body?: Partial<V2TimelineClipCreateRequest>) => Promise<void>;
  deleteTimelineClip: (clipId: string) => Promise<void>;
  setDraft: (timeline: FinalCompositionTimeline | null) => void;
};

const emptyTimelineView: FinalCompositionTimelineView = {
  loading: false,
  saving: false,
  rendering: false,
  timeline: null,
  draft: null,
  response: null,
  conflict: null,
  error: null,
  renderError: null,
  eventDirty: false,
};

function cloneTimeline(timeline: FinalCompositionTimeline): FinalCompositionTimeline {
  return {
    ...timeline,
    tracks: timeline.tracks.map((track) => ({
      ...track,
      clips: track.clips.map((clip) => ({ ...clip })),
    })),
  };
}

function finalCompositionErrorMessage(error: unknown) {
  const code = typeof error === "object" && error && "code" in error ? String((error as { code?: unknown }).code) : "";
  if (code === "timeline_version_conflict") return "Timeline version conflict. Current active final video remains available.";
  return error instanceof Error ? error.message : "Final composition timeline request failed. Current active final video remains available.";
}

export function useFinalCompositionModule(args: FinalCompositionModuleArgs): FinalCompositionModule {
  const [timelineView, setTimelineView] = useState<FinalCompositionTimelineView>(emptyTimelineView);
  const [baselineVersion, setBaselineVersion] = useState<number | null>(null);

  const workflowId = args.workflowId;
  const isV2 = args.isV2;

  const applyResponse = useCallback((response: FinalCompositionTimelineResponse, options: { preserveDraft?: boolean; eventDirty?: boolean } = {}) => {
    setBaselineVersion(response.timeline.version);
    setTimelineView((current) => ({
      ...current,
      loading: false,
      saving: false,
      response,
      timeline: response.timeline,
      draft: options.preserveDraft && current.draft ? current.draft : cloneTimeline(response.timeline),
      conflict: null,
      error: null,
      eventDirty: Boolean(options.eventDirty),
    }));
  }, []);

  const loadTimeline = useCallback(async (options: { preserveDraft?: boolean; eventDirty?: boolean } = {}) => {
    if (!workflowId || isV2) return;
    setTimelineView((current) => ({ ...current, loading: true, error: null }));
    try {
      const response = await api.getFinalCompositionTimeline(workflowId);
      applyResponse(response, options);
    } catch (error) {
      setTimelineView((current) => ({ ...current, loading: false, error: finalCompositionErrorMessage(error) }));
      args.onError?.(finalCompositionErrorMessage(error));
    }
  }, [applyResponse, args, isV2, workflowId]);

  const saveTimeline = useCallback(async () => {
    if (!workflowId || isV2 || !timelineView.draft) return;
    setTimelineView((current) => ({ ...current, saving: true, error: null }));
    const payload: FinalCompositionTimelineSaveRequest = {
      timeline: timelineView.draft,
      expected_version: baselineVersion ?? timelineView.draft.version,
    };
    try {
      const response = await api.saveFinalCompositionTimeline(workflowId, payload);
      applyResponse(response);
      await args.onWorkflowRefresh?.(workflowId);
    } catch (error) {
      const message = finalCompositionErrorMessage(error);
      setTimelineView((current) => ({
        ...current,
        saving: false,
        conflict: message.includes("conflict") ? "Timeline was updated on the backend. Review the refreshed timeline, then retry save." : current.conflict,
        error: message,
      }));
      args.onError?.(message);
    }
  }, [applyResponse, args, baselineVersion, isV2, timelineView.draft, workflowId]);

  const renderCandidate = useCallback(async () => {
    if (!workflowId || isV2 || !timelineView.draft) return;
    setTimelineView((current) => ({ ...current, rendering: true, renderError: null }));
    const payload: FinalCompositionTimelineRenderRequest = {
      timeline_id: timelineView.draft.timeline_id,
      timeline_version: timelineView.draft.version,
      acceptance_policy: "manual_candidate",
    };
    try {
      await api.renderFinalCompositionTimeline(workflowId, payload);
      await args.onWorkflowRefresh?.(workflowId);
    } catch (error) {
      const message = finalCompositionErrorMessage(error);
      setTimelineView((current) => ({ ...current, renderError: message }));
      args.onError?.(message);
    } finally {
      setTimelineView((current) => ({ ...current, rendering: false }));
    }
  }, [args, isV2, timelineView.draft, workflowId]);

  const createTimelineClip = useCallback(async (sourceAssetId: string, body: Partial<V2TimelineClipCreateRequest> = {}) => {
    if (!workflowId || !isV2 || !sourceAssetId) return;
    const response = await v2Api.createTimelineClip(workflowId, {
      source_asset_id: sourceAssetId,
      clip_type: body.clip_type ?? "video",
      duration: body.duration ?? 3,
      ...body,
    });
    if (response.workflow) await args.onV2Workflow?.(response.workflow);
    await args.onWorkflowRefresh?.(workflowId);
  }, [args, isV2, workflowId]);

  const deleteTimelineClip = useCallback(async (clipId: string) => {
    if (!workflowId || !isV2 || !clipId) return;
    const response = await v2Api.deleteTimelineClip(workflowId, clipId);
    if (response.workflow) await args.onV2Workflow?.(response.workflow);
    await args.onWorkflowRefresh?.(workflowId);
  }, [args, isV2, workflowId]);

  const setDraft = useCallback((timeline: FinalCompositionTimeline | null) => {
    setTimelineView((current) => ({ ...current, draft: timeline, eventDirty: false }));
  }, []);

  return useMemo(() => ({
    timelineView,
    loadTimeline,
    saveTimeline,
    renderCandidate,
    createTimelineClip,
    deleteTimelineClip,
    setDraft,
  }), [createTimelineClip, deleteTimelineClip, loadTimeline, renderCandidate, saveTimeline, setDraft, timelineView]);
}
