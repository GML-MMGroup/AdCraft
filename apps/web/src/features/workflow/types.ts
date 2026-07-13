import type { Edge, Node } from "@xyflow/react";
import type { AssetVersionV2, WorkflowItemV2, WorkflowRuntimeV2, WorkflowSlotV2 } from "../../types-v2.ts";
import type { QualityReviewSummary, UploadedAsset, WorkflowEdge, WorkflowNode, WorkflowVariable } from "../../types.ts";
import type { SlotMicroEditDraft } from "./v2/slots/useSlotMicroEdit.ts";

export type NodePortType = "prompt" | "text" | "image" | "video" | "audio" | "json" | "resource" | "data";
export type NodeFamily = "Text" | "Image" | "Video" | "Audio" | "Preview" | "Comment" | "Group" | "Utility";
export type NodeLibraryFilter = "All" | "Text" | "Image" | "Video" | "Audio" | "Recently Used";
export type PreviewLoadingType = "text" | "image" | "audio" | "video" | "generic";

export type NodePort = {
  id: string;
  label: string;
  dataType: NodePortType;
  required?: boolean;
  multiple?: boolean;
};

export type NodeTemplate = {
  node_type: string;
  display_name: string;
  category: string;
  description: string;
};

export type NodeDefinition = NodeTemplate & {
  family: NodeFamily;
  inputPorts: NodePort[];
  outputPorts: NodePort[];
};

export type V2SlotReferenceRemoval = {
  source: "reference_asset" | "uploaded_asset" | "library_entity";
  asset_id?: string;
  entity_id?: string;
  relation_id?: string | null;
  library_asset_id?: string | null;
};

export type V2LibraryReferenceOption = {
  entity_id: string;
  display_name?: string;
  library_asset_id?: string | null;
  semantic_type?: string | null;
};

export type WorkflowNodeData = {
  title: string;
  description: string;
  status: string;
  nodeId?: string;
  nodeType: string;
  kind: string;
  family: NodeFamily;
  category: string;
  contentPreview: string;
  output?: Record<string, unknown> | null;
  qualitySummary?: QualityReviewSummary | null;
  outputCount: number;
  candidateCount?: number;
  candidateWarningCount?: number;
  pendingVisibleCandidateCount?: number;
  previewAssets: UploadedAsset[];
  inputPorts: NodePort[];
  outputPorts: NodePort[];
  onOpenMedia?: (asset: UploadedAsset) => void;
  onSelectDynamicItem?: (nodeId: string, itemId: string) => void;
  onOpenScreenplay?: (trigger: HTMLElement) => void;
  projectId?: string | null;
  workflowId?: string | null;
  version?: number;
  locked?: boolean;
  stale?: boolean;
  staleReason?: string | null;
  runningDynamicItemById?: Record<string, boolean | undefined>;
  isV2Region?: boolean;
  v2Items?: WorkflowItemV2[];
  v2Slots?: WorkflowSlotV2[];
  v2AssetVersions?: AssetVersionV2[];
  v2Runtime?: WorkflowRuntimeV2;
  v2SlotRuntimeStatusById?: Record<string, string>;
  v2OpenSlotId?: string | null;
  v2OpenStoryboardItemId?: string | null;
  v2SlotDraftsById?: Record<string, SlotMicroEditDraft>;
  v2ReferenceAssetsBySlotId?: Record<string, AssetVersionV2[]>;
  v2LibraryReferenceOptions?: V2LibraryReferenceOption[];
  onOpenV2SlotEditor?: (slotId: string) => void;
  onOpenV2StoryboardPrompt?: (itemId: string) => void;
  onChangeV2SlotPrompt?: (slotId: string, prompt: string) => void;
  onChangeV2SlotNegativePrompt?: (slotId: string, negativePrompt: string) => void;
  onUploadV2SlotReference?: (slotId: string, files: FileList) => void;
  onSelectV2SlotLibraryReference?: (slotId: string, entityId: string) => void;
  onRemoveV2SlotReference?: (slotId: string, reference: V2SlotReferenceRemoval) => void;
  onOpenV2SlotAssetLibraryReplace?: (slotId: string) => void;
  onOpenV2SlotAssetLibrarySave?: (slotId: string) => void;
  onSaveV2ItemPrompt?: (itemId: string, prompt: string) => void;
  onSubmitV2SlotPrompt?: (slotId: string) => void;
  onSelectV2SlotVersion?: (slotId: string, versionId: string) => void;
  onDiscardV2SlotWorkingVersion?: (slotId: string) => void;
  onLoadV2SlotVersions?: (slotId: string) => void;
};

export type CanvasNode = Node<WorkflowNodeData, "workflowNode">;
export type CanvasEdge = Edge<{ label?: string; dataType?: NodePortType; mapping?: WorkflowEdge["mapping"]; required?: boolean }>;

export type AssetLibraryPickerTarget = "prompt" | "node" | "revision" | "dynamic-item" | "v2-slot-replace";

export type ConnectionLike = {
  source?: string | null;
  target?: string | null;
  sourceHandle?: string | null;
  targetHandle?: string | null;
};

export type CanvasHistoryState = {
  nodes: WorkflowNode[];
  flowNodes: CanvasNode[];
  edges: CanvasEdge[];
  variables: WorkflowVariable[];
};

export type SubtitleLine = {
  text: string;
  start_time: number;
  end_time: number;
  position: string;
  font_size: number;
  color: string;
  alignment: string;
};
