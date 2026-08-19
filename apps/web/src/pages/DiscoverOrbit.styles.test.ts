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

  it("keeps the Discover interaction glow locally purple", () => {
    const orbit = declarationBlock("\\.discover-orbit");
    const orbitFocus = declarationBlock("\\.discover-orbit:focus-visible");
    const selected = declarationBlock(
      "\\.discover-orbit__card:is\\(:hover, :focus-visible, \\.is-selected\\)",
    );
    const focused = declarationBlock("\\.discover-orbit__card:focus-visible");

    expect(orbit).toContain("--discover-selection-glow: rgba(171, 143, 247, 0.22)");
    expect(orbit).toContain("--discover-selection-shadow: rgba(49, 35, 92, 0.32)");
    expect(orbit).toContain("--discover-focus-ring: rgba(190, 167, 252, 0.88)");
    expect(orbitFocus).toContain("var(--focus-ring)");
    expect(selected).toContain("var(--discover-selection-glow)");
    expect(selected).toContain("var(--discover-selection-shadow)");
    expect(selected).not.toContain("var(--brand)");
    expect(focused).toContain("var(--discover-focus-ring)");
  });
});
