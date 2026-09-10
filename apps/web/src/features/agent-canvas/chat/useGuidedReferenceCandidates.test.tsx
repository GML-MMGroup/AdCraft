import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { agentCanvasApi } from "../../../api/agentCanvasApi.ts";
import type { GuidedReferenceCandidateListResponseV2 } from "../../../types-v2.ts";
import { useGuidedReferenceCandidates } from "./useGuidedReferenceCandidates.ts";

const page: GuidedReferenceCandidateListResponseV2 = {
  workflow_id: "workflow-1",
  reference_kind: "character_main",
  scope: "mine",
  items: [{
    entity_id: "character-entity-1",
    member_id: "character-member-1",
    asset_id: "asset-character-1",
    asset_version_id: "version-character-1",
    media_type: "image",
    display_name: "Character portrait",
    preview_url: "/api/v2/assets/asset-character-1/content",
    content_url: "/api/v2/assets/asset-character-1/content",
    reference_kind: "character_main",
    semantic_reference_role: "character_reference",
    reference_purpose: "identity_guidance",
    selectable: true,
  }],
  next_cursor: "cursor-2",
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useGuidedReferenceCandidates", () => {
  it("loads typed candidates and appends the next cursor page", async () => {
    const list = vi.spyOn(agentCanvasApi, "listAgentCanvasReferenceCandidates")
      .mockResolvedValueOnce(page)
      .mockResolvedValueOnce({ ...page, items: [{ ...page.items[0], asset_id: "asset-character-2" }], next_cursor: null });
    const { result } = renderHook(() => useGuidedReferenceCandidates({
      workflowId: "workflow-1",
      referenceKind: "character_main",
      scope: "mine",
      query: "portrait",
    }));

    await waitFor(() => expect(result.current.items).toHaveLength(1));
    expect(list).toHaveBeenCalledWith("workflow-1", expect.objectContaining({
      referenceKind: "character_main",
      scope: "mine",
      query: "portrait",
      cursor: null,
      signal: expect.any(AbortSignal),
    }));

    await act(async () => {
      await result.current.loadMore();
    });

    expect(result.current.items.map((item) => item.asset_id)).toEqual([
      "asset-character-1",
      "asset-character-2",
    ]);
    expect(list).toHaveBeenLastCalledWith("workflow-1", expect.objectContaining({ cursor: "cursor-2" }));
    expect(result.current.hasMore).toBe(false);
  });

  it("does not query while the library view is disabled", async () => {
    const list = vi.spyOn(agentCanvasApi, "listAgentCanvasReferenceCandidates").mockResolvedValue(page);
    const { result, rerender } = renderHook(
      ({ enabled }) => useGuidedReferenceCandidates({
        workflowId: "workflow-1",
        referenceKind: "scene_main",
        scope: "project",
        enabled,
      }),
      { initialProps: { enabled: false } },
    );

    expect(result.current.items).toEqual([]);
    expect(list).not.toHaveBeenCalled();
    rerender({ enabled: true });
    await waitFor(() => expect(list).toHaveBeenCalledOnce());
  });
});
