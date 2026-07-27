import { describe, expect, it } from "vitest";

import { PlanningCoordinator } from "../src/planning-coordinator.js";

describe("PlanningCoordinator", () => {
  it("accepts the canonical script before dispatching independent experts", async () => {
    const calls: string[] = [];
    let releaseExperts: (() => void) | undefined;
    const expertsStarted = new Promise<void>((resolve) => {
      releaseExperts = resolve;
    });
    const coordinator = new PlanningCoordinator({
      writeScript: async () => {
        calls.push("script");
        return { accepted: true, script_id: "script-1" };
      },
      planExpert: async (expert) => {
        calls.push(expert);
        releaseExperts?.();
        return { expert, accepted: true };
      },
    });

    const pending = coordinator.createWorkflowPlan({
      experts: ["product_designer", "character_designer", "scene_designer", "bgm_director"],
    });
    await expertsStarted;

    expect(calls[0]).toBe("script");
    expect(new Set(calls.slice(1))).toEqual(
      new Set(["product_designer", "character_designer", "scene_designer", "bgm_director"]),
    );
    await expect(pending).resolves.toMatchObject({ script: { script_id: "script-1" } });
  });

  it("does not dispatch children when Python rejects the script contract", async () => {
    const calls: string[] = [];
    const coordinator = new PlanningCoordinator({
      writeScript: async () => ({ accepted: false }),
      planExpert: async (expert) => {
        calls.push(expert);
        return { expert, accepted: true };
      },
    });

    await expect(
      coordinator.createWorkflowPlan({ experts: ["product_designer", "scene_designer"] }),
    ).rejects.toThrow("agent_script_contract_rejected");
    expect(calls).toEqual([]);
  });
});
