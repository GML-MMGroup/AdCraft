import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GuidedInteractionV1 } from "../../../types-v2.ts";
import { GuidedInteractionCard } from "./GuidedInteractionCard.tsx";

vi.mock("../assets/useAgentCanvasAssets.ts", () => ({
  useAgentCanvasAssets: () => ({
    items: [{
      id: "project:asset-front",
      assetId: "asset-front",
      source: "project",
      mediaType: "image",
      displayName: "Existing Front",
      previewUrl: "/asset-front.png",
      mediaUrl: "/asset-front.png",
      status: "ready",
      tags: [],
      identity: {
        source: "project",
        assetId: "asset-front",
        entityId: null,
        versionId: "version-front",
      },
      projectAsset: null,
    }],
    loading: false,
    error: null,
    uploading: false,
    uploadError: null,
    retry: vi.fn(),
    uploadFiles: vi.fn(),
    uploadFilesWithReceipts: vi.fn(),
  }),
}));

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

const productSourceInteraction: GuidedInteractionV1 = {
  ...conceptInteraction,
  interaction_id: "interaction-product-1",
  kind: "product_source",
  title: "Choose Product source",
  content: {
    content_kind: "product_source",
    input_kind: "main",
    question_id: "product_main_source",
    prompt: "Choose one Product image.",
    expected_guidance_revision: 5,
    min_asset_count: 1,
    max_asset_count: 1,
  },
  allowed_actions: ["select_source"],
};

const referenceSourceInteraction: GuidedInteractionV1 = {
  ...conceptInteraction,
  interaction_id: "interaction-reference-character-2",
  kind: "reference_source",
  title: "Choose a reference",
  context: "Character 2",
  content: {
    content_kind: "reference_source",
    reference_kind: "character_main",
    target_node_id: "character-main-draft-2",
    target_node_revision: 4,
    occurrence_id: "character-occurrence-2",
    question: "Use a reference for Character 2?",
    use_reference_label: "Use reference",
    skip_reference_label: "Skip reference",
    expected_guidance_revision: 9,
  },
  allowed_actions: ["use_reference", "skip_reference"],
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

    expect(screen.getByRole("article", { name: conceptInteraction.context })).toBeTruthy();
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

  it("keeps Product source content on its dedicated dock", () => {
    render(
      <GuidedInteractionCard
        interaction={productSourceInteraction}
        pending={false}
        issue={null}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );

    expect(screen.getByRole("article", { name: "Choose Product source" })).toBeTruthy();
    expect(screen.getByText("Use uploaded Product source")).toBeTruthy();
    expect(screen.queryByText("Accept")).toBeNull();
    expect(screen.queryByText("Retry")).toBeNull();
  });

  it("renders a typed reference source dock with separate use and skip actions", () => {
    render(
      <GuidedInteractionCard
        interaction={referenceSourceInteraction}
        referenceOccurrenceLabel="Character 2"
        pending={false}
        issue={null}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );

    expect(screen.getByRole("article", { name: "Use a reference for Character 2?" })).toBeTruthy();
    expect(screen.getByText("Character 2 · Main")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Use reference" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Skip reference" })).toBeTruthy();
    expect(screen.queryByText("Continue")).toBeNull();
  });

  it("submits exact AssetVersion identity for use_reference and omits it for skip_reference", async () => {
    const onSubmit = vi.fn().mockResolvedValue(true);
    const { rerender } = render(
      <GuidedInteractionCard
        interaction={referenceSourceInteraction}
        referenceOccurrenceLabel="Character 2"
        pending={false}
        issue={null}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Select Existing Front" }));
    fireEvent.click(screen.getByRole("button", { name: "Use reference" }));
    expect(onSubmit).toHaveBeenCalledWith({
      submission_kind: "reference_source",
      expected_interaction_revision: 2,
      expected_session_revision: 4,
      action: "use_reference",
      reference_kind: "character_main",
      asset_id: "asset-front",
      asset_version_id: "version-front",
    });

    onSubmit.mockClear();
    rerender(
      <GuidedInteractionCard
        interaction={{
          ...referenceSourceInteraction,
          interaction_id: "interaction-reference-scene",
          content: {
            ...referenceSourceInteraction.content,
            content_kind: "reference_source",
            reference_kind: "scene_main",
            occurrence_id: null,
            question: "Use a Scene reference?",
          },
        }}
        pending={false}
        issue={null}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Skip reference" }));
    expect(onSubmit).toHaveBeenCalledWith({
      submission_kind: "reference_source",
      expected_interaction_revision: 2,
      expected_session_revision: 4,
      action: "skip_reference",
      reference_kind: "scene_main",
    });
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

  it("keeps a submitted interaction visible and non-interactive while authority is pending", () => {
    render(
      <GuidedInteractionCard
        interaction={{ ...conceptInteraction, status: "submitted" }}
        pending
        issue={null}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );

    expect(screen.getByRole("article", { name: conceptInteraction.context })).toBeTruthy();
    expect(screen.getAllByRole("radio").every((control) => control.hasAttribute("disabled"))).toBe(true);
  });

  it("keeps proposal choices free of references and secondary actions", () => {
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
    expect(screen.queryByRole("button", { name: "References" })).toBeNull();
    expect(screen.queryByRole("button", { name: "More" })).toBeNull();
    expect(screen.queryByText("Choose an option above, or describe your own direction below.")).toBeNull();

    rerender(
      <GuidedInteractionCard
        interaction={conceptInteraction}
        pending={false}
        issue={null}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );
    expect(screen.queryByRole("button", { name: "References" })).toBeNull();
    expect(screen.queryByRole("button", { name: "More" })).toBeNull();
  });

  it("preserves a Product draft when stale authority replaces the interaction revision", () => {
    const { rerender } = render(
      <GuidedInteractionCard
        interaction={productSourceInteraction}
        pending={false}
        issue={null}
        onSubmit={vi.fn().mockResolvedValue(false)}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Select Existing Front" }));
    expect(screen.getByText("Existing Front", { selector: ".agent-chat__product-source-selected-name" })).toBeTruthy();

    rerender(
      <GuidedInteractionCard
        interaction={{
          ...productSourceInteraction,
          interaction_id: "interaction-product-2",
          expected_session_revision: 8,
          revision: 4,
        }}
        pending={false}
        issue={{
          summary: "The workflow changed before this response was saved. Review the latest options and try again.",
          detail: "guided_interaction_stale",
          fieldId: null,
          retryable: true,
        }}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );

    expect(screen.getByText("Existing Front", { selector: ".agent-chat__product-source-selected-name" })).toBeTruthy();
  });
});
