import { describe, expect, it } from "vitest";

import { resolutionAspectRatio } from "./resolutionAspectRatio.ts";

describe("resolutionAspectRatio", () => {
  it("reduces provider sizes to their aspect ratio", () => {
    expect(resolutionAspectRatio("2048x2048")).toBe("1:1");
    expect(resolutionAspectRatio("2560x1440")).toBe("16:9");
    expect(resolutionAspectRatio("1440x2560")).toBe("9:16");
    expect(resolutionAspectRatio("2304x1728")).toBe("4:3");
    expect(resolutionAspectRatio("1728x2304")).toBe("3:4");
    expect(resolutionAspectRatio("1536x1024")).toBe("3:2");
    expect(resolutionAspectRatio("1024 × 1536")).toBe("2:3");
  });

  it("snaps grid-rounded sizes to the nearest common ratio", () => {
    expect(resolutionAspectRatio("1664x936")).toBe("16:9");
  });

  it("leaves values without dimensions alone", () => {
    expect(resolutionAspectRatio("720p")).toBeNull();
    expect(resolutionAspectRatio("2K")).toBeNull();
    expect(resolutionAspectRatio("0x1024")).toBeNull();
  });
});
