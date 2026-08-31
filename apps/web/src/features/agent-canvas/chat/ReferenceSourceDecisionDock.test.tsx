import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GuidedInteractionV1 } from "../../../types-v2.ts";
import { ReferenceSourceDecisionDock } from "./ReferenceSourceDecisionDock.tsx";

const uploadFilesWithReceipts = vi.fn();

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
});

describe("ReferenceSourceDecisionDock", () => {
  it("uploads an image and submits the returned exact AssetVersion", async () => {
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
      asset_id: "uploaded-asset",
      asset_version_id: "uploaded-version",
    }));
    expect(uploadFilesWithReceipts).toHaveBeenCalledTimes(1);
  });
});
