import { afterEach, expect, it, vi } from "vitest";
import { v2Api } from "./v2Client.ts";
import { normalizeBrandDecisionPanelV1 } from "../features/agent-canvas/brand/brandDecisionNormalizers.ts";

afterEach(() => vi.unstubAllGlobals());

const panel = {
  project_id: "project-1", workflow_id: "workflow-1", mode: "brand", brand_name: "Brand",
  journey: { stage: "skill-stack", stage_revision: 5, stage_status: "waiting_user" },
  skill_stack: { entries: [{ skill_kind: "creative_method", skill_id: "visual-metaphor", title: "Visual metaphor", selected: true, version: "1.0.0", reason: "说明产品价值" }] },
};

it("preserves recommendation versions and reasons, including legacy nulls", () => {
  expect(normalizeBrandDecisionPanelV1(panel).skill_stack?.entries[0]).toMatchObject({ version: "1.0.0", reason: "说明产品价值" });
  expect(normalizeBrandDecisionPanelV1({ ...panel, skill_stack: { entries: [{ ...panel.skill_stack.entries[0], version: undefined, reason: undefined }] } }).skill_stack?.entries[0]).toMatchObject({ version: null, reason: null });
});

it("loads the method catalog through the public brand API", async () => {
  const items = [{ skill_id: "visual-metaphor", version: "1.0.0", skill_kind: "creative_method", title: "Visual metaphor", summary: "Make value visible" }];
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items })));
  vi.stubGlobal("fetch", fetchMock);
  await expect(v2Api.brandCreativeMethodSkills()).resolves.toEqual({ items });
  expect(fetchMock.mock.calls[0][0]).toContain("/brand/creative-method-skills");
});

it("submits a revision-fenced stack and normalizes the full panel", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(panel)));
  vi.stubGlobal("fetch", fetchMock);
  const body = { card_id: "card-5", expected_stage_revision: 5, creative_methods: [{ skill_id: "visual-metaphor", version: "1.0.0" }], audiovisual_style: { skill_id: "cinematic", version: "1.0.0" }, confirm: false };
  const result = await v2Api.brandSelectSkills("workflow/1", body);
  expect(fetchMock.mock.calls[0][0]).toContain("/brand/decisions/workflow%2F1/select-skills");
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual(body);
  expect(result.journey.stage_revision).toBe(5);
});
