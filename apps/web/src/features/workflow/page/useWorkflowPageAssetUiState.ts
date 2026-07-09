import { useMemo, useRef, useState, type Dispatch, type RefObject, type SetStateAction } from "react";
import type { AssetLibraryUploadKind, UploadedAsset } from "../../../types";

type StateSetter<T> = Dispatch<SetStateAction<T>>;

export type WorkflowPageAssetUiState = {
  nodeAssetInputRef: RefObject<HTMLInputElement | null>;
  uploadingAsset: boolean;
  nodeUploadKind: AssetLibraryUploadKind;
  nodeUploadName: string;
  nodeUploadTags: string;
  revisionTarget: UploadedAsset | null;
  revisionInstruction: string;
  v2ProviderTaskRefreshKeyBySlotId: Record<string, number>;
  revisionHistoryTarget: UploadedAsset | null;
  qualityOverrideRevisionId: string | null;
};

export type WorkflowPageAssetUiActions = {
  setUploadingAsset: StateSetter<boolean>;
  setNodeUploadKind: StateSetter<AssetLibraryUploadKind>;
  setNodeUploadName: StateSetter<string>;
  setNodeUploadTags: StateSetter<string>;
  setRevisionTarget: StateSetter<UploadedAsset | null>;
  setRevisionInstruction: StateSetter<string>;
  setV2ProviderTaskRefreshKeyBySlotId: StateSetter<Record<string, number>>;
  setRevisionHistoryTarget: StateSetter<UploadedAsset | null>;
  setQualityOverrideRevisionId: StateSetter<string | null>;
};

export function useWorkflowPageAssetUiState(): {
  state: WorkflowPageAssetUiState;
  actions: WorkflowPageAssetUiActions;
} {
  const nodeAssetInputRef = useRef<HTMLInputElement | null>(null);
  const [uploadingAsset, setUploadingAsset] = useState(false);
  const [nodeUploadKind, setNodeUploadKind] = useState<AssetLibraryUploadKind>("");
  const [nodeUploadName, setNodeUploadName] = useState("");
  const [nodeUploadTags, setNodeUploadTags] = useState("");
  const [revisionTarget, setRevisionTarget] = useState<UploadedAsset | null>(null);
  const [revisionInstruction, setRevisionInstruction] = useState("");
  const [v2ProviderTaskRefreshKeyBySlotId, setV2ProviderTaskRefreshKeyBySlotId] = useState<Record<string, number>>({});
  const [revisionHistoryTarget, setRevisionHistoryTarget] = useState<UploadedAsset | null>(null);
  const [qualityOverrideRevisionId, setQualityOverrideRevisionId] = useState<string | null>(null);

  const state = useMemo<WorkflowPageAssetUiState>(() => ({
    nodeAssetInputRef,
    uploadingAsset,
    nodeUploadKind,
    nodeUploadName,
    nodeUploadTags,
    revisionTarget,
    revisionInstruction,
    v2ProviderTaskRefreshKeyBySlotId,
    revisionHistoryTarget,
    qualityOverrideRevisionId,
  }), [
    nodeAssetInputRef,
    nodeUploadKind,
    nodeUploadName,
    nodeUploadTags,
    qualityOverrideRevisionId,
    revisionHistoryTarget,
    revisionInstruction,
    revisionTarget,
    uploadingAsset,
    v2ProviderTaskRefreshKeyBySlotId,
  ]);

  const actions = useMemo<WorkflowPageAssetUiActions>(() => ({
    setUploadingAsset,
    setNodeUploadKind,
    setNodeUploadName,
    setNodeUploadTags,
    setRevisionTarget,
    setRevisionInstruction,
    setV2ProviderTaskRefreshKeyBySlotId,
    setRevisionHistoryTarget,
    setQualityOverrideRevisionId,
  }), []);

  return { state, actions };
}
