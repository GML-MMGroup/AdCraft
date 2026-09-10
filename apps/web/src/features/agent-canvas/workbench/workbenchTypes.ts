import type {
  AgentCanvasImageLibraryCategoryV2,
  AgentCanvasWorkflowV2,
  CanvasBindingPatchRequestV2,
  CanvasConnectionPolicyV2,
  CanvasNodePatchRequestV2,
  CanvasNodeV2,
  NodeRuntimeV2,
  CanvasRuntimeModelResolutionV2,
  ProviderInputManifestAuditV2,
  SaveAgentCanvasImageToLibraryRequestV2,
  UpstreamInputReadinessIssueV2,
} from "../../../types-v2.ts";
import type { ProviderModelSummaryV1 } from "../../../api/providerRegistry.ts";

export type PatchNode = (
  nodeId: string,
  patch: CanvasNodePatchRequestV2,
  options?: { coalesce?: boolean; optimistic?: boolean },
) => Promise<void>;

export type PatchBinding = (
  bindingId: string,
  patch: CanvasBindingPatchRequestV2,
) => Promise<unknown>;

export interface AgentCanvasInlineWorkbenchProps {
  workflow: AgentCanvasWorkflowV2;
  node: CanvasNodeV2;
  runtime?: NodeRuntimeV2 | null;
  patchNode: PatchNode;
  patchBinding?: PatchBinding;
  deleteBinding?: (bindingId: string) => Promise<void>;
  connectionPolicy?: CanvasConnectionPolicyV2 | null;
  providerModels?: ProviderModelSummaryV1[];
  providerDefaultModelRef?: string | null;
  providerModelsLoading?: boolean;
  providerModelsError?: string | null;
  inputManifest?: ProviderInputManifestAuditV2 | null;
  modelResolution?: CanvasRuntimeModelResolutionV2 | null;
  inputReadinessIssue?: UpstreamInputReadinessIssueV2 | null;
  onRun: (node: CanvasNodeV2) => Promise<void>;
  onSaveImageToLibrary: (
    assetId: string,
    request: SaveAgentCanvasImageToLibraryRequestV2,
  ) => Promise<void>;
  onDelete: (nodeId: string) => Promise<void>;
  onOpenEditing: () => void;
  onWorkflowRefresh?: () => Promise<void> | void;
  onOpenAssets: () => void;
  onUploadReferences: () => void;
  onClose: () => void;
}

export interface ImageLibraryDraft {
  category: AgentCanvasImageLibraryCategoryV2;
  displayName: string;
  saved: boolean;
}
