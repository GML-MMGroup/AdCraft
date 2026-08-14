"""Generate deterministic Pi Agent runtime contracts from canonical Pydantic models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from app.schemas import agent_capabilities
from app.schemas import agent_runtime
from app.schemas import agent_canvas_video_parameters
from app.schemas import agent_canvas
from app.schemas import agent_canvas_ad_media
from app.schemas import agent_canvas_editing
from app.schemas import agent_canvas_creative_session
from app.schemas import agent_canvas_production_journey
from app.schemas import agent_canvas_prompt_preparation
from app.schemas import agent_canvas_capabilities
from app.schemas import agent_canvas_materialization
from app.schemas import agent_canvas_requirements
from app.schemas import agent_canvas_decision_bundles
from app.schemas import agent_canvas_world_setting
from app.schemas import agent_canvas_storyboard_sequences
from app.schemas import agent_working_documents
from app.schemas import agent_operation_contexts
from app.schemas import agent_operation_recovery
from app.schemas import workflow_v2_expert_brief_contracts
from app.schemas import workflow_v2_planning
from app.schemas import workflow_v2_prompt_contracts
from app.schemas import v2_agent_conversations
from app.schemas import v2_quick_media
from app.services.v2_agent_contract_registry import AGENT_STRUCTURED_CONTRACT_REGISTRY
from app.services.agent_run_context_registry import AGENT_RUN_CONTEXT_REGISTRY
from app.services.video_agent_operation_registry import VideoAgentOperationRegistry


CONTRACT_MODELS = (
    agent_canvas_prompt_preparation.NodePromptPreparationV1,
    agent_canvas_decision_bundles.CreativeDirectiveDecisionEffectV1,
    agent_canvas_decision_bundles.SetDurationSecondsDecisionEffectV1,
    agent_canvas_decision_bundles.SetAspectRatioDecisionEffectV1,
    agent_canvas_decision_bundles.SetOutputResolutionDecisionEffectV1,
    agent_canvas_decision_bundles.SetFrameRateDecisionEffectV1,
    agent_canvas_decision_bundles.SetSpokenLanguageDecisionEffectV1,
    agent_canvas_decision_bundles.SetAudioModeDecisionEffectV1,
    agent_canvas_decision_bundles.SetProductCountDecisionEffectV1,
    agent_canvas_decision_bundles.SetPropCountDecisionEffectV1,
    agent_canvas_decision_bundles.SetCharacterCountDecisionEffectV1,
    agent_canvas_decision_bundles.SetSceneCountDecisionEffectV1,
    agent_canvas_decision_bundles.SetStoryboardSequenceCountDecisionEffectV1,
    agent_canvas_decision_bundles.SetVideoSegmentCountDecisionEffectV1,
    agent_canvas_decision_bundles.SetControlDecisionEffectV1,
    agent_canvas_decision_bundles.SetElementPresenceDecisionEffectV1,
    agent_canvas_decision_bundles.DecisionBundleOptionDraftV1,
    agent_canvas_decision_bundles.DecisionBundleQuestionDraftV1,
    agent_canvas_decision_bundles.DecisionBundleDraftV1,
    agent_canvas_decision_bundles.DecisionBundleOptionV1,
    agent_canvas_decision_bundles.DecisionBundleQuestionV1,
    agent_canvas_decision_bundles.DecisionBundleAnswerV1,
    agent_canvas_decision_bundles.DecisionBundleV1,
    agent_canvas_decision_bundles.DecisionBundleActionAcceptedV1,
    agent_canvas_storyboard_sequences.StoryboardSequenceRowDraftV2,
    agent_canvas_storyboard_sequences.StoryboardOutlineSegmentDraftV2,
    agent_canvas_storyboard_sequences.StoryboardSequenceOutlineDraftV2,
    agent_canvas_storyboard_sequences.StoryboardSegmentMaterializationDraftV2,
    agent_canvas_storyboard_sequences.StoryboardSegmentAuthoringContextV2,
    agent_canvas.CanvasPositionV2,
    agent_canvas.CanvasNodeErrorV2,
    agent_canvas.CanvasModelSummaryV2,
    agent_canvas.CanvasVariationDraftV2,
    agent_canvas.CanvasBindingSourceNodeV2,
    agent_canvas.CanvasBindingSourceImageAssetV2,
    agent_canvas_video_parameters.CanvasParameterProvenanceV2,
    agent_canvas.CanvasNodeV2,
    agent_canvas.CanvasBindingV2,
    agent_canvas_editing.EditingOutputSettingsV2,
    agent_canvas_editing.EditingVideoEntryV2,
    agent_canvas_editing.EditingBgmEntryV2,
    agent_canvas_editing.EditingManifestV2,
    agent_canvas_ad_media.VisualStyleContractV2,
    agent_canvas_ad_media.DesignAssetContentV2,
    agent_canvas_ad_media.CharacterDesignAssetContentV2,
    agent_canvas_ad_media.SceneBoardPanelV2,
    agent_canvas_ad_media.SceneDesignBoardContentV2,
    agent_canvas_ad_media.StoryboardPanelV2,
    agent_canvas_ad_media.StoryboardGridContentV2,
    agent_canvas_ad_media.VideoSegmentContentV2,
    agent_canvas_ad_media.BgmContentV2,
    agent_operation_contexts.FrozenPlanningFacts,
    agent_operation_contexts.PlanningReferenceSummary,
    agent_operation_contexts.PlanningItemSummary,
    agent_operation_contexts.PlanningSlotSummary,
    agent_operation_contexts.FrontDeskIntentAgentContext,
    agent_operation_contexts.IntentContractAgentContext,
    agent_operation_contexts.ScriptWriterAgentContext,
    agent_operation_contexts.ProductExpertAgentContext,
    agent_operation_contexts.CharacterExpertAgentContext,
    agent_operation_contexts.SceneExpertAgentContext,
    agent_operation_contexts.BgmExpertAgentContext,
    agent_operation_contexts.VideoParameterTextSourceV2,
    agent_operation_contexts.VideoParameterCapabilityContextV2,
    agent_operation_contexts.VideoParameterIntentContextV2,
    agent_canvas_video_parameters.VideoParameterCandidateV2,
    agent_canvas_video_parameters.VideoParameterIntentV2,
    agent_canvas_creative_session.CreationModeDecisionV2,
    agent_canvas_creative_session.CreativeGoalV2,
    agent_canvas_creative_session.CreativeElementDecisionV2,
    agent_canvas_creative_session.GuidanceTopicStateV2,
    agent_canvas_creative_session.GuidanceCompletionProjectionV2,
    agent_canvas_creative_session.CreativeAuthorityStateV2,
    agent_canvas_creative_session.CreativeAuthorityActionV2,
    agent_canvas_creative_session.CreativeAuthorityResolutionV2,
    agent_canvas_creative_session.GuidedStepCheckpointV2,
    agent_canvas_creative_session.GuidanceStagePolicyResultV2,
    agent_canvas_production_journey.JourneyElementDecisionV1,
    agent_canvas_production_journey.FoundationJourneyItemV1,
    agent_canvas_production_journey.JourneyActionProjectionV1,
    agent_canvas_production_journey.JourneyTransitionEvidenceV1,
    agent_canvas_production_journey.JourneyEvidenceV1,
    agent_canvas_production_journey.GuidedProductionJourneyV1,
    agent_canvas_production_journey.JourneyPolicyContextV1,
    agent_canvas_production_journey.JourneyPolicyResultV1,
    agent_canvas_creative_session.GuidedSessionStateV2,
    agent_canvas_capabilities.ExplicitElementIntentV2,
    agent_canvas_capabilities.CompactRequirementDirectivePatchV1,
    agent_canvas_capabilities.CompactDurationSecondsControlV2,
    agent_canvas_capabilities.CompactAspectRatioControlV2,
    agent_canvas_capabilities.CompactOutputResolutionControlV2,
    agent_canvas_capabilities.CompactFrameRateControlV2,
    agent_canvas_capabilities.CompactSpokenLanguageControlV2,
    agent_canvas_capabilities.CompactAudioModeControlV2,
    agent_canvas_capabilities.CompactProductCountControlV2,
    agent_canvas_capabilities.CompactPropCountControlV2,
    agent_canvas_capabilities.CompactCharacterCountControlV2,
    agent_canvas_capabilities.CompactSceneCountControlV2,
    agent_canvas_capabilities.CompactStoryboardSequenceCountControlV2,
    agent_canvas_capabilities.CompactVideoSegmentCountControlV2,
    agent_canvas_capabilities.CompactRequirementControlsV2,
    agent_canvas_capabilities.CompactExplicitElementValueV3,
    agent_canvas_capabilities.CompactExplicitElementsV3,
    agent_canvas_capabilities.CompactGlobalRequirementDirectivePatchV3,
    agent_canvas_capabilities.CompactCapabilityRequirementDirectivePatchV3,
    agent_canvas_capabilities.CompactRequirementDirectivePatchV3,
    agent_canvas_capabilities.CompactRequirementPatchV3,
    agent_canvas_capabilities.CompactTurnIntentDecisionV3,
    agent_canvas_capabilities.TurnIntentDecisionV2,
    agent_canvas_capabilities.TurnIntentContextV2,
    agent_canvas_requirements.RequirementLedgerV1,
    agent_canvas_requirements.RequirementLedgerRevisionV1,
    agent_canvas_requirements.RequirementLedgerResponseV1,
    agent_canvas_requirements.RequirementPatchV1,
    agent_canvas_requirements.RequirementLedgerPatchRequestV1,
    agent_canvas_requirements.CapabilityRequirementProjectionV1,
    agent_canvas_requirements.DurationSecondsControlV1,
    agent_canvas_requirements.AspectRatioControlV1,
    agent_canvas_requirements.OutputResolutionControlV1,
    agent_canvas_requirements.FrameRateControlV1,
    agent_canvas_requirements.SpokenLanguageControlV1,
    agent_canvas_requirements.AudioModeControlV1,
    agent_canvas_requirements.ProductCountControlV1,
    agent_canvas_requirements.PropCountControlV1,
    agent_canvas_requirements.CharacterCountControlV1,
    agent_canvas_requirements.SceneCountControlV1,
    agent_canvas_requirements.StoryboardSequenceCountControlV1,
    agent_canvas_requirements.VideoSegmentCountControlV1,
    agent_canvas_requirements.DurationSecondsControlPatchV1,
    agent_canvas_requirements.AspectRatioControlPatchV1,
    agent_canvas_requirements.OutputResolutionControlPatchV1,
    agent_canvas_requirements.FrameRateControlPatchV1,
    agent_canvas_requirements.SpokenLanguageControlPatchV1,
    agent_canvas_requirements.AudioModeControlPatchV1,
    agent_canvas_requirements.ProductCountControlPatchV1,
    agent_canvas_requirements.PropCountControlPatchV1,
    agent_canvas_requirements.CharacterCountControlPatchV1,
    agent_canvas_requirements.SceneCountControlPatchV1,
    agent_canvas_requirements.StoryboardSequenceCountControlPatchV1,
    agent_canvas_requirements.VideoSegmentCountControlPatchV1,
    agent_canvas_requirements.ManualDurationSecondsControlPatchV1,
    agent_canvas_requirements.ManualAspectRatioControlPatchV1,
    agent_canvas_requirements.ManualOutputResolutionControlPatchV1,
    agent_canvas_requirements.ManualFrameRateControlPatchV1,
    agent_canvas_requirements.ManualSpokenLanguageControlPatchV1,
    agent_canvas_requirements.ManualAudioModeControlPatchV1,
    agent_canvas_requirements.ManualProductCountControlPatchV1,
    agent_canvas_requirements.ManualPropCountControlPatchV1,
    agent_canvas_requirements.ManualCharacterCountControlPatchV1,
    agent_canvas_requirements.ManualSceneCountControlPatchV1,
    agent_canvas_requirements.ManualStoryboardSequenceCountControlPatchV1,
    agent_canvas_requirements.ManualVideoSegmentCountControlPatchV1,
    agent_canvas_requirements.RequirementDirectiveV1,
    agent_canvas_requirements.RequirementDirectivePatchV1,
    agent_canvas_requirements.ManualRequirementDirectivePatchV1,
    agent_canvas_requirements.RequirementElementPresenceV1,
    agent_canvas_requirements.RequirementElementPresencePatchV1,
    agent_canvas_requirements.RequirementConflictV1,
    agent_canvas_requirements.RequirementConflictPatchV1,
    agent_canvas_requirements.EditableRequirementDirectiveV1,
    agent_canvas_requirements.OmittedRequirementDirectiveV1,
    agent_canvas_requirements.RequirementApplicationDeltaV1,
    agent_canvas_requirements.RequirementApplicationResultV1,
    agent_canvas_capabilities.AskUserNextActionCommandV1,
    agent_canvas_capabilities.AuthorDecisionBundleNextActionCommandV1,
    agent_canvas_capabilities.InvokeCapabilityNextActionCommandV1,
    agent_canvas_capabilities.ReplyNextActionCommandV1,
    agent_canvas_capabilities.FinishNextActionCommandV1,
    agent_canvas_capabilities.NextActionCommandV1,
    agent_canvas_capabilities.NextActionContextV1,
    agent_canvas_capabilities.CapabilityDefinitionV1,
    agent_canvas_capabilities.CapabilityPolicyContextV1,
    agent_canvas_capabilities.CapabilityPolicyResultV1,
    agent_canvas_capabilities.PlannedCapabilityReferenceV1,
    agent_canvas_capabilities.CapabilityReferencePlanV1,
    agent_canvas_capabilities.ValidatedNextActionV1,
    agent_canvas_capabilities.CapabilityContextSnapshotV2,
    agent_canvas_capabilities.CapabilityInvocationContextV2,
    agent_capabilities.VideoAgentOperationDefinitionV1,
    agent_canvas_capabilities.CapabilityCommandEnvelopeV2,
    agent_canvas_capabilities.NextActionEnvelopeV1,
    agent_canvas_capabilities.CapabilityDispatchReceiptV1,
    agent_canvas_capabilities.CapabilityExecutionResultV1,
    agent_canvas_materialization.SelectedConceptOptionV1,
    agent_canvas_materialization.ProposalReferenceSnapshotV1,
    agent_canvas_materialization.ProposalReferencePlanV1,
    agent_canvas_materialization.CapabilityMaterializationEnvelopeV1,
    agent_canvas_materialization.ProposalPublicationEnvelopeV1,
    agent_canvas_materialization.CapabilityMaterializationContextV1,
    agent_canvas_materialization.CapabilityMaterializationExecutionResultV1,
    agent_canvas_materialization.WorldSettingMaterializationContentV1,
    agent_canvas_materialization.QuickMediaMaterializationContentV1,
    agent_canvas_materialization.WorldSettingMaterializationResultV1,
    agent_canvas_materialization.ScriptMaterializationResultV1,
    agent_canvas_materialization.ProductMaterializationResultV1,
    agent_canvas_materialization.PropMaterializationResultV1,
    agent_canvas_materialization.CharacterMaterializationResultV1,
    agent_canvas_materialization.SceneMaterializationResultV1,
    agent_canvas_materialization.StoryboardMaterializationResultV1,
    agent_canvas_materialization.VideoMaterializationResultV1,
    agent_canvas_materialization.BgmMaterializationResultV1,
    agent_canvas_materialization.QuickMediaMaterializationResultV1,
    agent_canvas_capabilities.WorldSettingProposalOptionV1,
    agent_canvas_capabilities.ProductProposalOptionV1,
    agent_canvas_capabilities.PropProposalOptionV1,
    agent_canvas_capabilities.CharacterProposalOptionV1,
    agent_canvas_capabilities.SceneProposalOptionV1,
    agent_canvas_capabilities.ScriptProposalOptionV1,
    agent_canvas_capabilities.StoryboardProposalOptionV1,
    agent_canvas_capabilities.VideoProposalOptionV1,
    agent_canvas_capabilities.BgmProposalOptionV1,
    agent_canvas_capabilities.QuickMediaProposalOptionV1,
    agent_canvas_capabilities.WorldSettingProposalResultV1,
    agent_canvas_capabilities.ProductProposalResultV1,
    agent_canvas_capabilities.PropProposalResultV1,
    agent_canvas_capabilities.CharacterProposalResultV1,
    agent_canvas_capabilities.SceneProposalResultV1,
    agent_canvas_capabilities.ScriptProposalResultV1,
    agent_canvas_capabilities.StoryboardProposalResultV1,
    agent_canvas_capabilities.VideoProposalResultV1,
    agent_canvas_capabilities.BgmProposalResultV1,
    agent_canvas_capabilities.QuickMediaProposalResultV1,
    agent_canvas_creative_session.CreativeDirectionSnapshotV2,
    agent_canvas_creative_session.StyleGuidanceContextV2,
    agent_canvas_creative_session.ProjectCreativeMemoryV2,
    agent_canvas_creative_session.DraftReferenceIntentV2,
    agent_canvas_creative_session.ProposedDraftReferenceV2,
    agent_canvas_creative_session.ScriptDraftContentV2,
    agent_canvas_creative_session.ExpertActivityV2,
    agent_canvas_creative_session.ResolvedImageTargetV2,
    agent_working_documents.AgentAnchorV2,
    agent_working_documents.AnchorRegistryContentV2,
    agent_working_documents.StoryboardPlanGlobalParametersV2,
    agent_working_documents.StoryboardNarrativeSegmentV2,
    agent_working_documents.StoryboardPlanRowV2,
    agent_working_documents.StoryboardNodeRecordV2,
    agent_working_documents.StoryboardSegmentMaterializationV2,
    agent_working_documents.StoryboardVisualAnchorV2,
    agent_working_documents.AgentDocumentLinkedNodeRuntimeV2,
    agent_working_documents.StoryboardProductionPlanContentV2,
    agent_working_documents.AgentWorkingDocumentV2,
    agent_working_documents.AgentWorkingDocumentReferenceV2,
    agent_working_documents.AgentDocumentContextExcerptV2,
    agent_working_documents.AgentDocumentProvenanceV2,
    agent_working_documents.InitializeAnchorRegistryPatchV2,
    agent_working_documents.UpsertAnchorPatchV2,
    agent_working_documents.InitializeStoryboardPlanPatchV2,
    agent_working_documents.ReplaceNarrativeSegmentPatchV2,
    agent_working_documents.ReplaceStoryboardRowsPatchV2,
    agent_working_documents.MaterializeStoryboardSegmentPatchV2,
    agent_working_documents.FreezeStoryboardVisualAnchorPatchV2,
    agent_working_documents.AttachStoryboardNodePatchV2,
    agent_working_documents.AttachVideoNodePatchV2,
    agent_working_documents.AttachAudioNodePatchV2,
    agent_working_documents.AttachEditingNodePatchV2,
    agent_working_documents.AgentDocumentPatchSubmissionV2,
    agent_canvas_creative_session.GuidanceSessionActionV2,
    agent_canvas_world_setting.WorldSettingAuthoringProvenanceV2,
    agent_canvas_world_setting.WorldSettingCoreV2,
    agent_canvas_world_setting.WorldSettingDocumentV2,
    agent_canvas_world_setting.WorldSettingContextEnvelopeV2,
    agent_canvas_world_setting.WorldSettingResolvedInputV2,
    agent_operation_contexts.InteractionMessageSummary,
    agent_operation_contexts.InteractionTargetSummary,
    agent_operation_contexts.AssetRevisionAgentContext,
    agent_operation_contexts.QuickMediaAgentContext,
    agent_operation_contexts.WorkflowConversationAgentContext,
    agent_operation_contexts.ConversationSummaryAgentContext,
    agent_operation_contexts.DirectorTurnContextV2,
    agent_operation_contexts.AgentCommandReplanContextV2,
    agent_operation_contexts.CreativeAnchorSetV2,
    agent_operation_contexts.ProposalRevisionOptionV2,
    agent_operation_contexts.ProposalRevisionContextV2,
    v2_agent_conversations.WorkflowConversationReply,
    v2_agent_conversations.ConversationSummaryResult,
    workflow_v2_planning.V2ProductBrief,
    workflow_v2_planning.V2CharacterBrief,
    workflow_v2_planning.V2SceneBrief,
    workflow_v2_planning.V2BgmBrief,
    workflow_v2_expert_brief_contracts.V2ProductExpertPlan,
    workflow_v2_expert_brief_contracts.V2CharacterExpertPlan,
    workflow_v2_expert_brief_contracts.V2SceneExpertPlan,
    workflow_v2_expert_brief_contracts.V2BgmExpertPlan,
    workflow_v2_prompt_contracts.V2ProductMainPromptPlan,
    workflow_v2_prompt_contracts.V2ProductMultiViewPromptPlan,
    workflow_v2_prompt_contracts.V2ProductPromptPlan,
    workflow_v2_prompt_contracts.V2CharacterMainPromptPlan,
    workflow_v2_prompt_contracts.V2CharacterThreeViewPromptPlan,
    workflow_v2_prompt_contracts.V2CharacterPromptPlan,
    workflow_v2_prompt_contracts.V2SceneMainPromptPlan,
    workflow_v2_prompt_contracts.V2SceneMultiViewPromptPlan,
    workflow_v2_prompt_contracts.V2ScenePromptPlan,
    workflow_v2_prompt_contracts.V2BgmPromptPlan,
    v2_quick_media.V2QuickMediaPromptPlan,
    agent_runtime.AgentReferenceSummary,
    agent_runtime.AgentTargetContext,
    agent_runtime.AgentRunContext,
    agent_runtime.AgentRunPolicy,
    agent_runtime.AgentModelExecutionPolicyV1,
    agent_runtime.AgentTransportAttemptMetadataV1,
    agent_operation_recovery.AgentOperationPolicyV2,
    agent_operation_recovery.AgentOperationFailureV2,
    agent_runtime.AgentRunRequest,
    agent_runtime.AgentProviderConformanceInputV1,
    agent_runtime.AgentRuntimeEvent,
    agent_runtime.AgentToolCall,
    agent_runtime.AgentToolResult,
    agent_runtime.AgentStructuredSubmission,
    agent_runtime.StructuredViolation,
    agent_runtime.AgentStructuredNormalizationAuditV1,
    agent_runtime.AgentStructuredValidationResult,
    agent_runtime.AgentRuntimeHealth,
    agent_runtime.AgentRuntimeError,
    agent_runtime.SpecialistDraft,
    agent_runtime.AgentNodeIdRefV2,
    agent_runtime.AgentOperationResultRefV2,
    agent_runtime.AgentAssetRefV2,
    agent_runtime.AgentPlacementHintV2,
    agent_runtime.AgentCreateDraftNodeOperationV2,
    agent_runtime.AgentPatchEditableNodeOperationV2,
    agent_runtime.AgentCreateBindingOperationV2,
    agent_runtime.AgentPatchBindingOperationV2,
    agent_runtime.AgentDeleteBindingOperationV2,
    agent_runtime.AgentDeleteNodeOperationV2,
    agent_runtime.AgentMaterializeSiblingDraftOperationV2,
    agent_runtime.AgentRequestNodeRunOperationV2,
    agent_runtime.AgentCommandPlanDraftV2,
    agent_runtime.AgentCommandPlanCreateV2,
    agent_runtime.AgentCommandPlanV2,
    agent_runtime.AgentCommandReplanResultV2,
    agent_runtime.AgentOperationResultV2,
    agent_runtime.AgentActionEnvelopeV2,
)


def generate_agent_contracts(output_dir: Path) -> tuple[Path, Path]:
    """Write canonical JSON Schema and TypeScript declarations in stable byte order."""

    output_dir.mkdir(parents=True, exist_ok=True)
    combined_schema = TypeAdapter(
        tuple[tuple(CONTRACT_MODELS)]  # type: ignore[valid-type]
    ).json_schema()
    # Pydantic's tuple adapter provides one shared $defs graph for all contracts.
    definitions = _canonicalize_schema(combined_schema.get("$defs", {}))
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://adcraft.local/contracts/agent-runtime-v1.schema.json",
        "protocol_version": "1",
        "x-agent-context-contracts": list(AGENT_RUN_CONTEXT_REGISTRY.names()),
        "x-agent-structured-contracts": list(AGENT_STRUCTURED_CONTRACT_REGISTRY.names()),
        "x-video-agent-operations": [
            definition.model_dump(mode="json")
            for definition in VideoAgentOperationRegistry().definitions()
        ],
        "$defs": definitions,
    }
    schema = _canonicalize_schema(schema)
    schema_path = output_dir / "agent-runtime.schema.json"
    schema_path.write_text(
        json.dumps(schema, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    declarations = [
        "/* Generated by app.cli.generate_agent_contracts. Do not edit manually. */",
        "",
        'export const AGENT_PROTOCOL_VERSION = "1" as const;',
        "",
    ]
    for model in CONTRACT_MODELS:
        model_schema = definitions[model.__name__]
        declarations.append(f"export type {model.__name__} = {_typescript_type(model_schema)};")
        declarations.append("")
    typescript_path = output_dir / "agent-runtime.ts"
    typescript_path.write_text("\n".join(declarations), encoding="utf-8")
    return schema_path, typescript_path


def _typescript_type(schema: dict[str, Any]) -> str:
    if "$ref" in schema:
        reference_name = str(schema["$ref"]).rsplit("/", 1)[-1]
        return "unknown" if reference_name == "JsonValue" else reference_name
    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=True)
    if "enum" in schema:
        return " | ".join(json.dumps(item, ensure_ascii=True) for item in schema["enum"])
    if "anyOf" in schema:
        return " | ".join(_typescript_type(option) for option in schema["anyOf"])
    if "oneOf" in schema:
        return " | ".join(_typescript_type(option) for option in schema["oneOf"])
    schema_type = schema.get("type")
    if schema_type == "object" or "properties" in schema:
        additional = schema.get("additionalProperties")
        if additional is not None and additional is not False:
            value_type = _typescript_type(additional) if isinstance(additional, dict) else "unknown"
            return f"Readonly<Record<string, {value_type}>>"
        required = frozenset(schema.get("required", []))
        members = []
        for name, member_schema in schema.get("properties", {}).items():
            optional = "" if name in required else "?"
            members.append(
                f"readonly {json.dumps(name)}{optional}: {_typescript_type(member_schema)}"
            )
        return "{ " + "; ".join(members) + " }"
    if schema_type == "array":
        return f"ReadonlyArray<{_typescript_type(schema.get('items', {}))}>"
    if schema_type == "string":
        return "string"
    if schema_type in {"integer", "number"}:
        return "number"
    if schema_type == "boolean":
        return "boolean"
    if schema_type == "null":
        return "null"
    return "unknown"


def _canonicalize_schema(value: Any, *, parent_key: str | None = None) -> Any:
    """Normalize order-insensitive schema arrays before serializing contracts."""

    if isinstance(value, dict):
        return {key: _canonicalize_schema(child, parent_key=key) for key, child in value.items()}
    if isinstance(value, list):
        normalized = [_canonicalize_schema(child) for child in value]
        if parent_key in {"enum", "required"}:
            return sorted(normalized, key=lambda child: json.dumps(child, sort_keys=True))
        return normalized
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("agent/src/generated"),
    )
    arguments = parser.parse_args()
    generate_agent_contracts(arguments.output)


if __name__ == "__main__":
    main()
