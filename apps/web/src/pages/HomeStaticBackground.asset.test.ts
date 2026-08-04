import { existsSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("shared static cosmic background", () => {
  it("ships the original optimized WebP and removes the animated ring asset", () => {
    const path = resolve(
      process.cwd(),
      "public/assets/home-dark-cosmic.webp",
    );
    const removedRingPath = resolve(
      process.cwd(),
      "public/assets/home-cosmic-ring.webp",
    );

    expect(existsSync(path)).toBe(true);
    expect(statSync(path).size).toBeLessThan(900_000);
    expect(existsSync(removedRingPath)).toBe(false);
  });

  it("does not retain the removed Three.js background dependency", () => {
    const packageJson = JSON.parse(
      readFileSync(resolve(process.cwd(), "package.json"), "utf8"),
    ) as {
      dependencies?: Record<string, string>;
      devDependencies?: Record<string, string>;
    };

    expect(packageJson.dependencies?.three).toBeUndefined();
    expect(packageJson.devDependencies?.["@types/three"]).toBeUndefined();
  });
});
