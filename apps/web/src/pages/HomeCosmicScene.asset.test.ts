import { existsSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("Home cosmic source asset", () => {
  it("ships an optimized WebP source image", () => {
    const path = resolve(
      process.cwd(),
      "public/assets/home-cosmic-ring.webp",
    );

    expect(existsSync(path)).toBe(true);
    expect(statSync(path).size).toBeLessThan(900_000);
  });
});
