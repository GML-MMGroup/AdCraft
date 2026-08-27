import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GuidedInteractionV1 } from "../../../types-v2.ts";
import { MediaReviewDecisionDock } from "./MediaReviewDecisionDock.tsx";

const interaction: GuidedInteractionV1 = {
  interaction_id: "media-review-1",
  workflow_id: "workflow-1",
  session_id: "session-1",
  checkpoint_id: "checkpoint-review",
  kind: "media_review",
  status: "open",
  response_locale: "en-US",
  expected_session_revision: 12,
  revision: 5,
  title: "Review generated video",
  context: "Choose what should happen next.",
  content: {
    content_kind: "media_review",
    node_id: "node-video-1",
    node_revision: 4,
    asset_id: "asset-video-1",
    asset_version_id: "asset-version-1",
    summary: "The generated video is ready for review.",
  },
  allowed_actions: ["accept", "retry", "replace", "exclude"],
  submit_path: "/api/v2/workflows/workflow-1/chat/interactions/media-review-1/submit",
  created_at: "2026-08-27T10:00:00Z",
  updated_at: "2026-08-27T10:00:00Z",
};

afterEach(cleanup);

describe("MediaReviewDecisionDock", () => {
  it("defaults to Accept and submits the existing media review payload", () => {
    const submit = vi.fn().mockResolvedValue(true);
    render(<MediaReviewDecisionDock interaction={interaction} pending={false} issue={null} onSubmit={submit} />);

    expect(screen.getByText("The generated video is ready for review.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(submit).toHaveBeenCalledWith({
      submission_kind: "media_review",
      expected_interaction_revision: 5,
      expected_session_revision: 12,
      action: "accept",
      instruction: null,
    });
  });

  it("selects Retry as a mode before exposing it as the primary action", () => {
    const submit = vi.fn().mockResolvedValue(true);
    render(<MediaReviewDecisionDock interaction={interaction} pending={false} issue={null} onSubmit={submit} />);

    fireEvent.click(screen.getByRole("button", { name: "Choose Retry" }));
    expect(submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ action: "retry", instruction: null }));
  });

  it("requires and trims a replacement instruction", () => {
    const submit = vi.fn().mockResolvedValue(true);
    render(<MediaReviewDecisionDock interaction={interaction} pending={false} issue={null} onSubmit={submit} />);

    fireEvent.click(screen.getByRole("button", { name: "Choose Replace" }));
    const primary = screen.getByRole("button", { name: "Submit replacement" }) as HTMLButtonElement;
    expect(primary.disabled).toBe(true);
    fireEvent.change(screen.getByRole("textbox", { name: "Describe the replacement" }), {
      target: { value: "  Use a slower camera move  " },
    });
    expect(primary.disabled).toBe(false);
    fireEvent.click(primary);
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({
      action: "replace",
      instruction: "Use a slower camera move",
    }));
  });

  it("keeps Exclude in More and requires confirmation", () => {
    const submit = vi.fn().mockResolvedValue(true);
    render(<MediaReviewDecisionDock interaction={interaction} pending={false} issue={null} onSubmit={submit} />);

    fireEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.click(screen.getByRole("button", { name: "Exclude this media" }));
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Confirm exclusion" }));
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ action: "exclude", instruction: null }));
  });

  it("retains the selected mode and instruction while only the primary action submits", () => {
    const { rerender } = render(
      <MediaReviewDecisionDock interaction={interaction} pending={false} issue={null} onSubmit={vi.fn().mockResolvedValue(true)} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Choose Replace" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Describe the replacement" }), {
      target: { value: "Keep the product centered" },
    });

    rerender(
      <MediaReviewDecisionDock interaction={interaction} pending issue={null} onSubmit={vi.fn().mockResolvedValue(true)} />,
    );

    expect((screen.getByRole("textbox", { name: "Describe the replacement" }) as HTMLTextAreaElement).value)
      .toBe("Keep the product centered");
    expect(screen.getAllByText("Submitting")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Choose Retry" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Choose Replace" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "More" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("does not render actions omitted by backend authority", () => {
    render(
      <MediaReviewDecisionDock
        interaction={{ ...interaction, allowed_actions: ["accept"] }}
        pending={false}
        issue={null}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );

    expect(screen.queryByRole("button", { name: "Choose Retry" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Choose Replace" })).toBeNull();
    expect(screen.queryByRole("button", { name: "More" })).toBeNull();
  });

  it("keeps an issue local without clearing replacement input", () => {
    const { rerender } = render(
      <MediaReviewDecisionDock interaction={interaction} pending={false} issue={null} onSubmit={vi.fn().mockResolvedValue(true)} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Choose Replace" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Describe the replacement" }), {
      target: { value: "Use a wider shot" },
    });

    rerender(
      <MediaReviewDecisionDock
        interaction={interaction}
        pending={false}
        issue={{ summary: "The agent could not submit this response. Try again.", detail: null, fieldId: null, retryable: true }}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );

    expect(screen.getByRole("alert")).toBeTruthy();
    expect((screen.getByRole("textbox", { name: "Describe the replacement" }) as HTMLTextAreaElement).value)
      .toBe("Use a wider shot");
  });
});
