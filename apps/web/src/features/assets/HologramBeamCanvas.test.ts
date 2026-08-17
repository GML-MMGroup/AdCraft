import { describe, expect, it } from "vitest";

import {
  createHologramBeamGeometry,
  renderHologramBeam,
} from "./hologramBeamModel.ts";

function recordingContext() {
  const operations = {
    clear: 0,
    fills: 0,
    strokes: 0,
    filters: [] as string[],
  };
  let filter = "none";
  const context = {
    globalCompositeOperation: "source-over",
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 1,
    lineCap: "butt",
    get filter() {
      return filter;
    },
    set filter(value: string) {
      filter = value;
      operations.filters.push(value);
    },
    clearRect() { operations.clear += 1; },
    save() {},
    restore() {},
    beginPath() {},
    closePath() {},
    moveTo() {},
    lineTo() {},
    bezierCurveTo() {},
    arc() {},
    fill() { operations.fills += 1; },
    stroke() { operations.strokes += 1; },
  } as unknown as CanvasRenderingContext2D;

  return { context, operations };
}

describe("HologramBeamCanvas", () => {
  it("builds a stable 108-ray and 150-mote projection field", () => {
    const first = createHologramBeamGeometry();
    const second = createHologramBeamGeometry();

    expect(first.rays).toHaveLength(108);
    expect(first.dust).toHaveLength(150);
    expect(second).toEqual(first);
  });

  it("draws the four cached beam layers in the documented proportions", () => {
    const { context, operations } = recordingContext();

    renderHologramBeam(context, 1_000, 625, createHologramBeamGeometry());

    expect(context.globalCompositeOperation).toBe("lighter");
    expect(operations.clear).toBe(1);
    expect(operations.filters).toContain("blur(2.2px)");
    expect(operations.fills).toBe(108 + 150);
    expect(operations.strokes).toBe(27 + 15);
  });
});
