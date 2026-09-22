import { afterEach, expect, it, vi } from "vitest";
import { v2Api } from "./v2Client.ts";

afterEach(() => vi.unstubAllGlobals());

it("accepts no next question after all treatment choices are confirmed", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
  await expect(v2Api.brandNextQuestion("workflow-1")).resolves.toBeNull();
});

it("locks treatment through the explicit confirmation endpoint", async () => {
  const journey = { policy_version: "brand_professional_v1", stage: "production", stage_revision: 18, stage_status: "ready", treatment_substep: null };
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(journey), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await expect(v2Api.brandLockTreatment("workflow-1", "a".repeat(64))).resolves.toEqual(journey);
  expect(fetchMock.mock.calls[0][0]).toContain("/brand/decisions/workflow-1/lock-treatment");
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ confirm: true, content_digest: "a".repeat(64) });
});
