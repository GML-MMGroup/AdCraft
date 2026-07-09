import { useMemo, useState, type Dispatch, type SetStateAction } from "react";
import type {
  UploadedAsset,
  WorkflowRevisionState,
} from "../../../types";
import type { SlotVersionsResponseV2 } from "../../../types-v2";

export type LocalRevisionPromptMetadataState = {
  prompt?: string | null;
  providerPrompt?: string | null;
  optimizedRevisionPrompt?: string | null;
  providerRevisionPrompt?: string | null;
  revisionRequirements?: unknown;
  revisionId?: string | null;
  generatedAt?: string | null;
  specialistResultId?: string | null;
  qualityStatus?: string | null;
  reviewer?: string | null;
};

export type LocalRevisionCardState = {
  key: string;
  revisionId?: string;
  status?: WorkflowRevisionState["status"];
  message?: string | null;
  error?: string | null;
  activeAsset?: UploadedAsset | null;
  candidates?: WorkflowRevisionState[];
  assets?: UploadedAsset[];
  history?: UploadedAsset[];
  revisions?: WorkflowRevisionState[];
  historyLoading?: boolean;
  historyError?: string | null;
  affectedDownstreamNodes?: string[];
  promptMetadata?: LocalRevisionPromptMetadataState | null;
  updatedAt?: string;
};

export type CanvasCandidateSummaryState = {
  candidateCount?: number;
  candidateWarningCount?: number;
  pendingVisibleCandidateCount?: number;
  dirty?: boolean;
  updatedAt?: string;
};

export type RevisionCandidateBusyState = Record<string, "accept" | "reject" | undefined>;

export type WorkflowAssetOperationsController = {
  state: {
    localRevisionByKey: Record<string, LocalRevisionCardState>;
    canvasCandidateSummaryByNodeId: Record<string, CanvasCandidateSummaryState>;
    v2SlotVersionsById: Record<string, SlotVersionsResponseV2 | undefined>;
    revisionCandidateBusyById: RevisionCandidateBusyState;
  };
  actions: {
    setLocalRevisionByKey: Dispatch<SetStateAction<Record<string, LocalRevisionCardState>>>;
    setCanvasCandidateSummaryByNodeId: Dispatch<SetStateAction<Record<string, CanvasCandidateSummaryState>>>;
    setV2SlotVersionsById: Dispatch<SetStateAction<Record<string, SlotVersionsResponseV2 | undefined>>>;
    setRevisionCandidateBusyById: Dispatch<SetStateAction<RevisionCandidateBusyState>>;
  };
};

export function useWorkflowAssetOperations(): WorkflowAssetOperationsController {
  const [localRevisionByKey, setLocalRevisionByKey] = useState<Record<string, LocalRevisionCardState>>({});
  const [canvasCandidateSummaryByNodeId, setCanvasCandidateSummaryByNodeId] = useState<Record<string, CanvasCandidateSummaryState>>({});
  const [v2SlotVersionsById, setV2SlotVersionsById] = useState<Record<string, SlotVersionsResponseV2 | undefined>>({});
  const [revisionCandidateBusyById, setRevisionCandidateBusyById] = useState<RevisionCandidateBusyState>({});

  return useMemo(
    () => ({
      state: {
        localRevisionByKey,
        canvasCandidateSummaryByNodeId,
        v2SlotVersionsById,
        revisionCandidateBusyById,
      },
      actions: {
        setLocalRevisionByKey,
        setCanvasCandidateSummaryByNodeId,
        setV2SlotVersionsById,
        setRevisionCandidateBusyById,
      },
    }),
    [
      canvasCandidateSummaryByNodeId,
      localRevisionByKey,
      revisionCandidateBusyById,
      v2SlotVersionsById,
    ],
  );
}
