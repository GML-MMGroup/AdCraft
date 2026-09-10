import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GuidedInteractionV1 } from "../../../types-v2.ts";
import { ReferenceSourceDecisionDock } from "./ReferenceSourceDecisionDock.tsx";

const fixtures = vi.hoisted(() => ({
  uploadFilesWithReceipts: vi.fn(),
  useGuidedReferenceCandidates: vi.fn(),
}));
const { uploadFilesWithReceipts, useGuidedReferenceCandidates } = fixtures;

vi.mock("../assets/useAgentCanvasAssets.ts", () => ({
  useAgentCanvasAssets: () => ({
    items: [],
    loading: false,
    error: null,
    uploading: false,
    uploadError: null,
    retry: vi.fn(),
    uploadFiles: vi.fn(),
    uploadFilesWithReceipts,
  }),
}));

vi.mock("./useGuidedReferenceCandidates.ts", () => ({
  useGuidedReferenceCandidates: fixtures.useGuidedReferenceCandidates,
}));

const interaction: GuidedInteractionV1 = {
  interaction_id: "interaction-reference-1",
  workflow_id: "workflow-1",
  session_id: "session-1",
  checkpoint_id: "checkpoint-1",
  kind: "reference_source",
  status: "open",
  response_locale: "en-US",
  expected_session_revision: 7,
  revision: 3,
  title: "Choose a reference",
  context: "Choose a Character reference.",
  content: {
    content_kind: "reference_source",
    reference_kind: "character_main",
    target_node_id: "character-main-1",
    target_node_revision: 2,
    occurrence_id: "character-occurrence-1",
    question: "Use a reference for Character 1?",
    use_reference_label: "Use reference",
    skip_reference_label: "Skip reference",
    expected_guidance_revision: 8,
  },
  allowed_actions: ["use_reference", "skip_reference"],
  submit_path: "/submit",
  created_at: "2026-08-31T08:00:00Z",
  updated_at: "2026-08-31T08:00:00Z",
};

afterEach(() => {
  cleanup();
  uploadFilesWithReceipts.mockReset();
  useGuidedReferenceCandidates.mockReset();
});

describe("ReferenceSourceDecisionDock", () => {
  it("uploads an image and submits the returned exact AssetVersion", async () => {
    useGuidedReferenceCandidates.mockReturnValue({
      items: [], loading: false, loadingMore: false, error: null,
      hasMore: false, retry: vi.fn(), loadMore: vi.fn(),
    });
    uploadFilesWithReceipts.mockResolvedValue([{
      asset: {
        asset_id: "uploaded-asset",
        version_id: "uploaded-version",
        display_name: "Uploaded reference",
        preview_url: "/uploaded-reference.png",
        media_url: "/uploaded-reference.png",
      },
    }]);
    const onSubmit = vi.fn().mockResolvedValue(true);
    render(<ReferenceSourceDecisionDock interaction={interaction} pending={false} issue={null} onSubmit={onSubmit} />);

    expect(screen.getByText("单张参考图不应超过 4 MB。")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Upload reference"), {
      target: { files: [new File(["image"], "reference.png", { type: "image/png" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Use reference" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({
      submission_kind: "reference_source",
      expected_interaction_revision: 3,
      expected_session_revision: 7,
      action: "use_reference",
      reference_kind: "character_main",
      source_scope: "project",
      asset_id: "uploaded-asset",
      asset_version_id: "uploaded-version",
    }));
    expect(uploadFilesWithReceipts).toHaveBeenCalledWith(
      [expect.any(File)],
      { semanticRole: "character_reference" },
      [expect.any(String)],
    );
  });

  it("uploads a scene reference with the canonical project candidate role", async () => {
    useGuidedReferenceCandidates.mockReturnValue({
      items: [], loading: false, loadingMore: false, error: null,
      hasMore: false, retry: vi.fn(), loadMore: vi.fn(),
    });
    uploadFilesWithReceipts.mockResolvedValue([{
      asset: {
        asset_id: "uploaded-scene",
        version_id: "uploaded-scene-version",
        display_name: "Uploaded scene",
        preview_url: "/uploaded-scene.png",
        media_url: "/uploaded-scene.png",
      },
    }]);
    const sceneInteraction: GuidedInteractionV1 = {
      ...interaction,
      interaction_id: "interaction-scene-reference-1",
      content: {
        ...interaction.content,
        content_kind: "reference_source",
        reference_kind: "scene_main",
        occurrence_id: null,
        target_node_id: "scene-main-1",
      },
    };
    const onSubmit = vi.fn().mockResolvedValue(true);
    render(<ReferenceSourceDecisionDock interaction={sceneInteraction} pending={false} issue={null} onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText("Upload reference"), {
      target: { files: [new File(["scene"], "scene.png", { type: "image/png" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Use reference" }));

    await waitFor(() => expect(uploadFilesWithReceipts).toHaveBeenCalledWith(
      [expect.any(File)],
      { semanticRole: "scene_reference" },
      [expect.any(String)],
    ));
  });

  it("selects a catalog candidate and submits its exact provenance", async () => {
    useGuidedReferenceCandidates.mockReturnValue({
      items: [{
        entity_id: "entity-scene-1",
        member_id: "member-scene-1",
        asset_id: "asset-scene-1",
        asset_version_id: "version-scene-1",
        media_type: "image",
        display_name: "Recommended studio",
        preview_url: "/api/v2/assets/asset-scene-1/content",
        content_url: "/api/v2/assets/asset-scene-1/content",
        reference_kind: "character_main",
        semantic_reference_role: "character_reference",
        reference_purpose: "identity_guidance",
        selectable: true,
      }],
      loading: false, loadingMore: false, error: null,
      hasMore: false, retry: vi.fn(), loadMore: vi.fn(),
    });
    const onSubmit = vi.fn().mockResolvedValue(true);
    render(<ReferenceSourceDecisionDock interaction={interaction} pending={false} issue={null} onSubmit={onSubmit} />);

    fireEvent.click(screen.getByRole("tab", { name: "Asset Library" }));
    expect(screen.queryByText("单张参考图不应超过 4 MB。")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Recommended" }));
    fireEvent.click(screen.getByRole("button", { name: "Select Recommended studio" }));
    fireEvent.click(screen.getByRole("button", { name: "Use reference" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({
      submission_kind: "reference_source",
      expected_interaction_revision: 3,
      expected_session_revision: 7,
      action: "use_reference",
      reference_kind: "character_main",
      source_scope: "recommended",
      entity_id: "entity-scene-1",
      member_id: "member-scene-1",
      asset_id: "asset-scene-1",
      asset_version_id: "version-scene-1",
    }));
  });

  it("clears and reloads a library selection invalidated by a structured submit error", async () => {
    const retry = vi.fn().mockResolvedValue(undefined);
    const candidate = {
      entity_id: null,
      member_id: null,
      asset_id: "asset-character-1",
      asset_version_id: "version-character-1",
      media_type: "image" as const,
      display_name: "Project character",
      preview_url: "/api/v2/assets/asset-character-1/content",
      content_url: "/api/v2/assets/asset-character-1/content",
      reference_kind: "character_main" as const,
      semantic_reference_role: "character_reference" as const,
      reference_purpose: "identity_guidance" as const,
      selectable: true,
    };
    useGuidedReferenceCandidates.mockReturnValue({
      items: [candidate], loading: false, loadingMore: false, error: null,
      hasMore: false, retry, loadMore: vi.fn(),
    });
    const onSubmit = vi.fn().mockResolvedValue(false);
    const { rerender } = render(
      <ReferenceSourceDecisionDock interaction={interaction} pending={false} issue={null} onSubmit={onSubmit} />,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Asset Library" }));
    fireEvent.click(screen.getByRole("button", { name: "Select Project character" }));
    expect(screen.getByRole("button", { name: "Remove" })).toBeTruthy();

    const invalidCandidateIssue = {
      code: "reference_candidate_not_found",
      summary: "The selected reference is no longer available.",
      detail: "reference_candidate_not_found: Candidate changed",
      fieldId: null,
      retryable: true,
    };
    rerender(
      <ReferenceSourceDecisionDock
        interaction={interaction}
        pending={false}
        issue={invalidCandidateIssue}
        onSubmit={onSubmit}
      />,
    );

    await waitFor(() => expect(retry).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
  });
});
