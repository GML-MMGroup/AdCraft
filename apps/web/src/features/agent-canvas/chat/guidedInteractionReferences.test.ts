import { describe, expect, it } from "vitest";

import type {
  AgentCanvasWorkflowV2,
  ChatProposalCardV2,
  GuidedInteractionV1,
  ProposedDraftReferenceV2,
} from "../../../types-v2.ts";
import {
  guidedInteractionReferenceMediaUrls,
  guidedInteractionReferences,
} from "./guidedInteractionReferences.ts";

const references: ProposedDraftReferenceV2[] = [{
  source_kind: "node",
  source_id: "node-character",
  binding_kind: "image_reference",
  input_role: "visual_reference",
  required: true,
  display_order: 0,
  semantic_reference_role: "subject_reference",
  display_name: "Character Three-view",
  media_type: "image",
}, {
  source_kind: "image_asset",
  source_id: "asset-scene",
  binding_kind: "image_reference",
  input_role: "visual_reference",
  required: true,
  display_order: 1,
  semantic_reference_role: "environment_reference",
  display_name: "Scene Reference Board",
  media_type: "image",
}];

const interaction: GuidedInteractionV1 = {
  interaction_id: "interaction-1",
  workflow_id: "workflow-1",
  session_id: "session-1",
  checkpoint_id: "checkpoint-1",
  kind: "concept_choice",
  status: "open",
  response_locale: "en-US",
  expected_session_revision: 4,
  revision: 2,
  title: "Choose storyboard direction",
  context: "Choose one direction.",
  content: {
    content_kind: "concept_choice",
    proposal_id: "proposal-storyboard-1",
    stage: "storyboard_grids",
    stage_revision: 4,
    action_id: "action-1",
    occurrence_id: "occurrence:storyboard_grids:1",
    capability_id: "storyboard_design",
    options: [],
    allow_custom: true,
    allow_exclusion: false,
  },
  allowed_actions: ["select", "delegate"],
  submit_path: "/submit",
  created_at: "2026-08-21T00:00:00Z",
  updated_at: "2026-08-21T00:00:00Z",
};

const proposalCard = {
  item_type: "proposal",
  proposal: {
    proposal_id: "proposal-storyboard-1",
    proposed_references: references,
  },
} as ChatProposalCardV2;

describe("guided interaction references", () => {
  it("projects the full authoritative references from the matching Proposal", () => {
    expect(guidedInteractionReferences(interaction, [proposalCard])).toEqual(references);
  });

  it("returns unresolved while the Proposal projection is not loaded", () => {
    expect(guidedInteractionReferences(interaction, [])).toBeNull();
  });

  it("resolves image previews from node outputs and direct image assets", () => {
    const workflow = {
      nodes: [{ node_id: "node-character", output_asset_id: "asset-character" }],
      assets: [{
        asset_id: "asset-character",
        preview_url: "/api/v2/assets/asset-character/content",
        media_url: "/api/v2/assets/asset-character/content",
      }, {
        asset_id: "asset-scene",
        preview_url: "/api/v2/assets/asset-scene/preview",
        media_url: "/api/v2/assets/asset-scene/content",
      }],
    } as AgentCanvasWorkflowV2;

    expect(guidedInteractionReferenceMediaUrls(references, workflow)).toEqual({
      "node:node-character": "/api/v2/assets/asset-character/content",
      "image_asset:asset-scene": "/api/v2/assets/asset-scene/content",
    });
  });
});
