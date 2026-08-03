import { isV2ApiError, V2ApiError, v2Api } from "./v2Client.ts";

export { isV2ApiError, V2ApiError };

/**
 * Capability boundary for the production Agent Canvas application.
 *
 * Legacy V2 methods remain on v2Api only while isolated legacy modules still
 * compile. Agent Canvas code imports this object so retired route families
 * cannot be reached accidentally.
 */
export const agentCanvasApi = {
  createAgentCanvasProject: v2Api.createAgentCanvasProject,
  agentCanvasWorkflowWithEtag: v2Api.agentCanvasWorkflowWithEtag,
  agentCanvasNode: v2Api.agentCanvasNode,
  patchAgentCanvasLayout: v2Api.patchAgentCanvasLayout,
  createAgentCanvasNode: v2Api.createAgentCanvasNode,
  patchAgentCanvasNode: v2Api.patchAgentCanvasNode,
  deleteAgentCanvasNode: v2Api.deleteAgentCanvasNode,
  saveAgentCanvasVariationDraft: v2Api.saveAgentCanvasVariationDraft,
  discardAgentCanvasVariationDraft: v2Api.discardAgentCanvasVariationDraft,
  materializeAgentCanvasVariationDraft: v2Api.materializeAgentCanvasVariationDraft,
  createAgentCanvasBinding: v2Api.createAgentCanvasBinding,
  patchAgentCanvasBinding: v2Api.patchAgentCanvasBinding,
  deleteAgentCanvasBinding: v2Api.deleteAgentCanvasBinding,
  agentCanvasConnectionPolicy: v2Api.agentCanvasConnectionPolicy,
  createAgentCanvasConnectedNode: v2Api.createAgentCanvasConnectedNode,
  uploadAgentCanvasAsset: v2Api.uploadAgentCanvasAsset,
  listAgentCanvasProjectAssets: v2Api.listAgentCanvasProjectAssets,
  listAgentCanvasMyAssets: v2Api.listAgentCanvasMyAssets,
  listAgentCanvasRecommendedAssets: v2Api.listAgentCanvasRecommendedAssets,
  saveAgentCanvasImageToLibrary: v2Api.saveAgentCanvasImageToLibrary,
  deleteAgentCanvasAsset: v2Api.deleteAgentCanvasAsset,
  agentCanvasChatTimeline: v2Api.agentCanvasChatTimeline,
  submitAgentCanvasChatMessage: v2Api.submitAgentCanvasChatMessage,
  agentCanvasChatTurn: v2Api.agentCanvasChatTurn,
  agentCanvasProposal: v2Api.agentCanvasProposal,
  actOnAgentCanvasProposal: v2Api.actOnAgentCanvasProposal,
  actOnAgentCanvasCommandPlan: v2Api.actOnAgentCanvasCommandPlan,
  applyAgentCanvasGuidedAction: v2Api.applyAgentCanvasGuidedAction,
  createAgentCanvasVideoSkillRun: v2Api.createAgentCanvasVideoSkillRun,
  runAgentCanvas: v2Api.runAgentCanvas,
  cancelAgentCanvasRun: v2Api.cancelAgentCanvasRun,
  agentCanvasRuntime: v2Api.agentCanvasRuntime,
  agentCanvasEvents: v2Api.agentCanvasEvents,
  openAgentCanvasEventStream: v2Api.openAgentCanvasEventStream,
  exportAgentCanvasEditingNode: v2Api.exportAgentCanvasEditingNode,
  cancelAgentCanvasEditingExport: v2Api.cancelAgentCanvasEditingExport,
} as const;
