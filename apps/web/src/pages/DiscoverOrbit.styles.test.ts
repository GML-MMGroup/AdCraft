import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const stylesheet = readFileSync(resolve(process.cwd(), "src/pages/home.css"), "utf8");

function declarationBlock(selector: string) {
  const match = stylesheet.match(new RegExp(`(?:^|\\n)${selector}\\s*\\{([^}]*)\\}`));
  return match?.[1] ?? "";
}

describe("Discover orbit vertical clearance", () => {
  it("keeps horizontal masking on the root and reserves room for card glow", () => {
    const orbit = declarationBlock("\\.discover-orbit");
    const interactiveOrbit = declarationBlock("\\.discover-orbit--interactive");
    const track = declarationBlock("\\.discover-orbit__track");

    expect(orbit).toContain("--discover-card-glow-space: 72px");
    expect(orbit).toContain("min-height: clamp(920px, 62vw, 1040px)");
    expect(interactiveOrbit).toContain("mask-image:");
    expect(track).not.toContain("mask-image:");
  });
});
