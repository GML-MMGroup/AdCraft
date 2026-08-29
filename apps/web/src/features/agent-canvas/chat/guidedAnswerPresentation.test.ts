import { describe, expect, it } from "vitest";

import type {
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
} from "../../../types-v2.ts";
import { buildGuidedAnswerBubbles } from "./guidedAnswerPresentation.ts";

function interaction(): GuidedInteractionV1 {
  return {
    interaction_id: "interaction-1",
    workflow_id: "workflow-1",
    session_id: "session-1",
    checkpoint_id: "checkpoint-1",
    kind: "clarification_questionnaire",
    status: "open",
    response_locale: "en-US",
    expected_session_revision: 4,
    revision: 2,
    title: "Set production details",
    context: "Choose the production details.",
    content: {
      content_kind: "questionnaire",
      questions: [{
        question_id: "character_count",
        prompt: "How many characters should appear?",
        input_kind: "single_select",
        options: [{
          option_id: "characters-2",
          title: "Two characters",
          summary: "A pair of characters.",
          difference_tags: [],
          recommended: false,
          reference_preview: [],
        }],
        allow_custom: true,
        allow_skip: false,
        required: true,
      }, {
        question_id: "production_duration_seconds",
        prompt: "How long should the ad be?",
        input_kind: "single_select",
        options: [{
          option_id: "duration-30",
          title: "30 seconds",
          summary: "Balanced runtime.",
          difference_tags: [],
          recommended: true,
          reference_preview: [],
        }],
        allow_custom: true,
        allow_skip: false,
        required: true,
      }],
    },
    allowed_actions: ["answer"],
    submit_path: "/submit",
    created_at: "2026-08-29T00:00:00Z",
    updated_at: "2026-08-29T00:00:00Z",
  };
}

describe("buildGuidedAnswerBubbles", () => {
  it("projects structured questionnaire answers in question order", () => {
    const request: GuidedInteractionSubmitRequestV1 = {
      submission_kind: "questionnaire",
      expected_interaction_revision: 2,
      expected_session_revision: 4,
      answers: [
        { answer_kind: "custom", question_id: "production_duration_seconds", value: "45" },
        { answer_kind: "option", question_id: "character_count", option_id: "characters-2" },
      ],
    };

    expect(buildGuidedAnswerBubbles(interaction(), request, 12)).toEqual([
      {
        bubble_id: "guided-answer:interaction-1:character_count",
        interaction_id: "interaction-1",
        question_id: "character_count",
        label: "How many characters should appear?",
        value: "Two characters",
        sequence: 12.01,
      },
      {
        bubble_id: "guided-answer:interaction-1:production_duration_seconds",
        interaction_id: "interaction-1",
        question_id: "production_duration_seconds",
        label: "How long should the ad be?",
        value: "45",
        sequence: 12.02,
      },
    ]);
  });

  it("does not infer a bubble for an answer that is absent from the typed interaction", () => {
    const request: GuidedInteractionSubmitRequestV1 = {
      submission_kind: "questionnaire",
      expected_interaction_revision: 2,
      expected_session_revision: 4,
      answers: [{ answer_kind: "option", question_id: "unknown", option_id: "unknown" }],
    };

    expect(buildGuidedAnswerBubbles(interaction(), request, 12)).toEqual([]);
  });
});
