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
  agentCanvasExecutionSettings: v2Api.agentCanvasExecutionSettings,
  patchAgentCanvasExecutionSettings: v2Api.patchAgentCanvasExecutionSettings,
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
  agentCanvasCreativeSession: v2Api.agentCanvasCreativeSession,
  agentCanvasDecisionBundle: v2Api.agentCanvasDecisionBundle,
  actOnAgentCanvasDecisionBundle: v2Api.actOnAgentCanvasDecisionBundle,
  agentCanvasChatTimeline: v2Api.agentCanvasChatTimeline,
  advanceAgentCanvasGuidance: v2Api.advanceAgentCanvasGuidance,
  agentCanvasPostReadyCheckpoint: v2Api.agentCanvasPostReadyCheckpoint,
  listAgentCanvasDocuments: v2Api.listAgentCanvasDocuments,
  agentCanvasDocument: v2Api.agentCanvasDocument,
  submitAgentCanvasGuidedInteraction: v2Api.submitAgentCanvasGuidedInteraction,
  submitAgentCanvasChatMessage: v2Api.submitAgentCanvasChatMessage,
  retryAgentCanvasChatTurn: v2Api.retryAgentCanvasChatTurn,
  agentCanvasChatTurn: v2Api.agentCanvasChatTurn,
  agentCanvasProposal: v2Api.agentCanvasProposal,
  actOnAgentCanvasProposal: v2Api.actOnAgentCanvasProposal,
  actOnAgentCanvasCommandPlan: v2Api.actOnAgentCanvasCommandPlan,
  applyAgentCanvasGuidedAction: v2Api.applyAgentCanvasGuidedAction,
  listVideoSkills: v2Api.listVideoSkills,
  getVideoSkill: v2Api.getVideoSkill,
  createAgentCanvasVideoSkillRun: v2Api.createAgentCanvasVideoSkillRun,
  runAgentCanvas: v2Api.runAgentCanvas,
  cancelAgentCanvasRun: v2Api.cancelAgentCanvasRun,
  agentCanvasRuntime: v2Api.agentCanvasRuntime,
  agentCanvasEvents: v2Api.agentCanvasEvents,
  openAgentCanvasEventStream: v2Api.openAgentCanvasEventStream,
  exportAgentCanvasEditingNode: v2Api.exportAgentCanvasEditingNode,
  cancelAgentCanvasEditingExport: v2Api.cancelAgentCanvasEditingExport,
} as const;
