import { describe, expect, it } from "vitest";
import { normalizeAgentWorkingDocumentPageV2, normalizeAgentWorkingDocumentV2 } from "./normalizers";

function documentWithContent(extra: Record<string, unknown> = {}) {
  return {
    document_id: "doc-plan-v3",
    workflow_id: "workflow-1",
    guidance_session_id: "session-1",
    kind: "storyboard_production_plan",
    title: "Storyboard Production Plan",
    revision: 4,
    content_schema_version: 3,
    content_digest: "sha256:document-v3",
    created_by_agent_run_id: "run-1",
    updated_by_agent_run_id: "run-2",
    linked_nodes: [],
    created_at: "2026-09-07T04:00:00Z",
    updated_at: "2026-09-07T05:00:00Z",
    content: {
      schema_version: "3",
      narrative_outline: "A product reveal.",
      requirement_revision_id: "requirement-1",
      requirement_revision_no: 1,
      global_parameters: { aspect_ratio: "16:9", total_duration_seconds: 15, segment_count: 1 },
      segments: [{
        sequence_id: "sequence-1", order: 1, start_seconds: 0, end_seconds: 15,
        narrative_goal: "Reveal the product.", start_state: "Closed frame.",
        end_state: "Product hero frame.", continuity_from_previous: null, terminal_policy: "close",
      }],
      rows: [],
      segment_materializations: [],
      ...extra,
    },
  };
}

describe("Storyboard V3 creative direction snapshot", () => {
  it.each(["direction_73f19c946afe4f12ba9a0400af2bddf1", "x", " ", " direction_1 ", "x".repeat(160)])(
    "preserves the backend snapshot identity in detail and list responses (%s)",
    (identity) => {
      const raw = documentWithContent({ creative_direction_snapshot_id: identity });
      expect(normalizeAgentWorkingDocumentV2(raw).content).toMatchObject({ creative_direction_snapshot_id: identity });
      expect(normalizeAgentWorkingDocumentPageV2({ items: [raw], next_cursor: null }).items[0].content)
        .toMatchObject({ creative_direction_snapshot_id: identity });
    },
  );

  it.each([{}, { creative_direction_snapshot_id: null }])("accepts historical or null identity: %j", (extra) => {
    expect(normalizeAgentWorkingDocumentV2(documentWithContent(extra)).content)
      .toMatchObject({ creative_direction_snapshot_id: null });
  });

  it.each(["", "x".repeat(161), 42, false, {}, []])("rejects invalid identity: %j", (identity) => {
    expect(() => normalizeAgentWorkingDocumentV2(documentWithContent({ creative_direction_snapshot_id: identity })))
      .toThrow(/creative_direction_snapshot_id/);
  });

  it("keeps strict rejection for unrelated fields", () => {
    expect(() => normalizeAgentWorkingDocumentV2(documentWithContent({ unexpected_snapshot_field: "bad" })))
      .toThrow(/unexpected_snapshot_field: unknown field/);
  });
});
