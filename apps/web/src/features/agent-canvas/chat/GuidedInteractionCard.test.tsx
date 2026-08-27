import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GuidedInteractionV1 } from "../../../types-v2.ts";
import { GuidedInteractionCard } from "./GuidedInteractionCard.tsx";

const conceptInteraction: GuidedInteractionV1 = {
  interaction_id: "interaction-concept",
  workflow_id: "workflow-1",
  session_id: "session-1",
  checkpoint_id: "checkpoint-1",
  kind: "concept_choice",
  status: "open",
  response_locale: "zh-CN",
  expected_session_revision: 4,
  revision: 2,
  title: "Choose a direction",
  context: "Pick the visual approach.",
  content: {
    content_kind: "concept_choice",
    proposal_id: null,
    stage: "world_view",
    stage_revision: 4,
    action_id: "action-world-view-1",
    occurrence_id: "occurrence:world_view:1",
    capability_id: "world_setting",
    allow_custom: true,
    allow_exclusion: true,
    options: [
      { option_id: "option-a", title: "Warm", summary: "Warm and intimate.", difference_tags: [], recommended: true, reference_preview: [] },
      { option_id: "option-b", title: "Precise", summary: "Clean precision.", difference_tags: [], recommended: false, reference_preview: [] },
      { option_id: "option-c", title: "Playful", summary: "Bright energy.", difference_tags: [], recommended: false, reference_preview: [] },
    ],
  },
  allowed_actions: ["select", "custom", "exclude", "delegate"],
  submit_path: "/submit",
  created_at: "2026-08-27T10:00:00Z",
  updated_at: "2026-08-27T10:00:00Z",
};

const questionnaireInteraction: GuidedInteractionV1 = {
  ...conceptInteraction,
  interaction_id: "interaction-questionnaire",
  kind: "clarification_questionnaire",
  title: "Set duration",
  content: {
    content_kind: "questionnaire",
    questions: [{
      question_id: "production_duration_seconds",
      prompt: "How long should the ad be?",
      input_kind: "single_select",
      options: [],
      allow_custom: true,
      allow_skip: false,
      required: true,
    }],
  },
  allowed_actions: ["answer"],
};

const mediaReviewInteraction: GuidedInteractionV1 = {
  ...conceptInteraction,
  interaction_id: "interaction-review",
  kind: "media_review",
  title: "Review media",
  content: {
    content_kind: "media_review",
    node_id: "node-1",
    node_revision: 2,
    asset_id: "asset-1",
    asset_version_id: "version-1",
    summary: "The generated video is ready.",
  },
  allowed_actions: ["accept", "retry"],
};

afterEach(cleanup);

describe("GuidedInteractionCard", () => {
  it("dispatches an open concept interaction without technical metadata", () => {
    render(
      <GuidedInteractionCard
        interaction={conceptInteraction}
        pending={false}
        issue={null}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );

    expect(screen.getByRole("article", { name: conceptInteraction.title })).toBeTruthy();
    expect(screen.getAllByRole("radio")).toHaveLength(3);
    expect(screen.queryByText(conceptInteraction.response_locale)).toBeNull();
  });

  it("dispatches questionnaire and media review content", () => {
    const { rerender } = render(
      <GuidedInteractionCard
        interaction={questionnaireInteraction}
        pending={false}
        issue={null}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );
    expect(screen.getByRole("article", { name: "Set duration" })).toBeTruthy();
    expect(screen.getByRole("spinbutton", { name: "Custom duration in seconds" })).toBeTruthy();

    rerender(
      <GuidedInteractionCard
        interaction={mediaReviewInteraction}
        pending={false}
        issue={null}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );
    expect(screen.getByRole("article", { name: "Review media" })).toBeTruthy();
    expect(screen.getByText("The generated video is ready.")).toBeTruthy();
  });

  it("does not render a closed interaction", () => {
    const { container } = render(
      <GuidedInteractionCard
        interaction={{ ...conceptInteraction, status: "closed" }}
        pending={false}
        issue={null}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("treats omitted proposal references as pending only for proposal-backed choices", () => {
    const { rerender } = render(
      <GuidedInteractionCard
        interaction={{
          ...conceptInteraction,
          content: conceptInteraction.content.content_kind === "concept_choice"
            ? { ...conceptInteraction.content, proposal_id: "proposal-1" }
            : conceptInteraction.content,
        }}
        pending={false}
        issue={null}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );
    expect(screen.getByRole("button", { name: "References" })).toBeTruthy();

    rerender(
      <GuidedInteractionCard
        interaction={conceptInteraction}
        pending={false}
        issue={null}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );
    expect(screen.queryByRole("button", { name: "References" })).toBeNull();
  });
});
