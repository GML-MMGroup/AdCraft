import { describe, expect, it } from "vitest";
import { edgeFlowMetrics } from "./edgeFlowController.ts";

describe("edge flow geometry", () => {
  it("keeps corresponding packet heads synchronized on unequal paths", () => {
    for (const length of [150, 500, 1500]) {
      const { keyframes, dasharray } = edgeFlowMetrics(length, 1);
      const dash = Number(dasharray.split(" ")[0]);
      for (const progress of [0, .25, .5, 1]) {
        const offset = Number(keyframes[0].strokeDashoffset)
          + (Number(keyframes[1].strokeDashoffset) - Number(keyframes[0].strokeDashoffset)) * progress;
        expect(dash - offset).toBeCloseTo(progress * 100);
      }
    }
  });

  it("keeps a 28px optical length under zoom and caps short paths", () => {
    for (const zoom of [.5, 1, 2]) {
      const dash = Number(edgeFlowMetrics(1000, zoom).dasharray.split(" ")[0]);
      expect(dash / 100 * 1000 * zoom).toBeCloseTo(28);
    }
    expect(edgeFlowMetrics(50, .5).dasharray).toBe("12 38");
  });
});
