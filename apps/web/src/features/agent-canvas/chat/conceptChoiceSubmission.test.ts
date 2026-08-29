import { describe, expect, it } from "vitest";

import type {
  GuidedInteractionV1,
  ProposedDraftReferenceV2,
} from "../../../types-v2.ts";
import { buildConceptChoiceSubmitRequest } from "./conceptChoiceSubmission.ts";

const interaction: GuidedInteractionV1 & {
  content: Extract<GuidedInteractionV1["content"], { content_kind: "concept_choice" }>;
} = {
  interaction_id: "interaction-1",
  workflow_id: "workflow-1",
  session_id: "session-1",
  checkpoint_id: "checkpoint-1",
  kind: "concept_choice",
  status: "open",
  response_locale: "en-US",
  expected_session_revision: 9,
  revision: 3,
  title: "Choose a direction",
  context: "Pick one direction.",
  content: {
    content_kind: "concept_choice",
    proposal_id: "proposal-1",
    stage: "world_view",
    stage_revision: 5,
    action_id: "action-1",
    occurrence_id: "occurrence-1",
    capability_id: "world_setting",
    allow_custom: true,
    allow_exclusion: false,
    options: [
      {
        option_id: "option-1",
        title: "Warm",
        summary: "A warm direction.",
        difference_tags: [],
        recommended: true,
        reference_preview: [],
      },
    ],
  },
  allowed_actions: ["select", "custom"],
  submit_path: "/submit",
  created_at: "2026-08-27T00:00:00Z",
  updated_at: "2026-08-27T00:00:00Z",
};

const reference: ProposedDraftReferenceV2 = {
  source_kind: "image_asset",
  source_id: "asset-1",
  binding_kind: "image_reference",
  input_role: "visual_reference",
  required: true,
  display_order: 0,
  semantic_reference_role: "world_setting_reference",
  occurrence_id: null,
  character_phase: null,
  display_name: "World reference",
  media_type: "image",
};

describe("buildConceptChoiceSubmitRequest", () => {
  it("builds a structured option submission with authoritative revisions and references", () => {
    expect(buildConceptChoiceSubmitRequest({
      interaction,
      selectedOptionId: "option-1",
      customText: "",
      proposalReferences: [reference],
    })).toEqual({
      submission_kind: "concept_choice",
      expected_interaction_revision: 3,
      expected_session_revision: 9,
      action: "select",
      option_id: "option-1",
      custom_text: null,
      accepted_references: [{
        source_kind: "image_asset",
        source_id: "asset-1",
        display_name: "World reference",
        media_type: "image",
        binding_kind: "image_reference",
        input_role: "visual_reference",
        required: true,
        display_order: 0,
        semantic_reference_role: "world_setting_reference",
      }],
    });
  });

  it("builds a custom direction without image upload fields", () => {
    expect(buildConceptChoiceSubmitRequest({
      interaction,
      selectedOptionId: null,
      customText: "  Use a restrained monochrome world. ",
      proposalReferences: [reference],
    })).toEqual({
      submission_kind: "concept_choice",
      expected_interaction_revision: 3,
      expected_session_revision: 9,
      action: "custom",
      option_id: null,
      custom_text: "Use a restrained monochrome world.",
    });
  });

  it("requires a loaded proposal reference projection before selecting an option", () => {
    expect(buildConceptChoiceSubmitRequest({
      interaction,
      selectedOptionId: "option-1",
      customText: "",
      proposalReferences: null,
    })).toBeNull();
  });

  it("rejects empty custom directions and unknown option IDs", () => {
    expect(buildConceptChoiceSubmitRequest({
      interaction,
      selectedOptionId: null,
      customText: "   ",
      proposalReferences: [],
    })).toBeNull();
    expect(buildConceptChoiceSubmitRequest({
      interaction,
      selectedOptionId: "missing",
      customText: "",
      proposalReferences: [],
    })).toBeNull();
  });
});
