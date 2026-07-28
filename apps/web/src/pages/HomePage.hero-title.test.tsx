import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HomePage } from "./HomePage";

const startNewProject = vi.fn();
const styles = readFileSync(resolve(process.cwd(), "src/pages/home.css"), "utf8");
const mobileHeroTitleStyles = styles.match(
  /@media \(max-width: 620px\)[\s\S]*?\.home-product-hero__title\s*\{[^}]*\}/,
)?.[0] ?? "";

vi.mock("../app/useHealth", () => ({
  useHealth: () => ({ startNewProject }),
}));

describe("HomePage hero title", () => {
  beforeEach(() => {
    startNewProject.mockReset();
  });

  it("renders the brand statement as three deliberate lines", () => {
    render(<HomePage navigate={vi.fn()} />);

    const title = screen.getByRole("heading", {
      level: 1,
      name: "One Sentence Becomes an Ad film.",
    });
    const lines = Array.from(
      title.querySelectorAll(".home-product-hero__title-line"),
    );

    expect(lines).toHaveLength(3);
    expect(lines.map((line) => line.textContent)).toEqual([
      "One Sentence",
      "Becomes an",
      "Ad film.",
    ]);
    expect(lines[2]?.classList.contains("home-product-hero__accent")).toBe(true);
    expect(lines[2]?.querySelectorAll(".home-product-hero__accent-glyph")).toHaveLength(8);
  });

  it("uses a lower, more open title lockup and a restrained champagne-gold glint", () => {
    expect(styles).toMatch(
      /\.home-product-hero__title\s*\{[^}]*font-size:\s*clamp\(46px, 4\.6vw, 64px\);[^}]*font-weight:\s*500;[^}]*line-height:\s*1\.15;[^}]*letter-spacing:\s*0\.012em;[^}]*-webkit-text-stroke:\s*0\.18px currentColor;/s,
    );
    expect(mobileHeroTitleStyles).toMatch(
      /font-size:\s*clamp\(40px, 11vw, 52px\);[^}]*line-height:\s*1\.15;/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero__title-line\s*\{[^}]*display:\s*block;/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero__accent-glyph\s*\{[^}]*linear-gradient\([^}]*#6f531c[^}]*#956f27[^}]*\)[^}]*background-size:\s*100% 100%;[^}]*background-clip:\s*text;[^}]*-webkit-text-stroke:\s*0\.16px rgba\(89, 65, 22, 0\.42\);/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero__accent\s*\{[^}]*animation:\s*home-hero-champagne-glint 6\.8s ease-in-out infinite;[^}]*animation-delay:\s*1\.3s;[^}]*transform-origin:\s*50% 50%;/s,
    );
    expect(styles).toMatch(
      /@keyframes home-hero-champagne-glint[\s\S]*?72%\s*\{[^}]*transform:\s*translate3d\(0, 0, 0\) scale\(1\.012\);/,
    );
    expect(styles).toMatch(
      /html\[data-theme="dark"\] \.home-product-hero__accent-glyph\s*\{[^}]*#d7ae59[^}]*#ffe7a6[^}]*#bc8d36[^}]*-webkit-text-stroke:\s*0\.16px rgba\(255, 232, 171, 0\.44\);/s,
    );
    expect(styles).toMatch(
      /@media \(prefers-reduced-motion:\s*reduce\)[\s\S]*?\.home-product-hero__accent[\s\S]*?animation:\s*none !important;/,
    );
    expect(styles).toMatch(
      /\.home-product-hero__accent\s*\{[^}]*width:\s*fit-content;[^}]*padding-inline:\s*0\.1em 0\.12em;[^}]*margin-inline:\s*-0\.1em -0\.12em;/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero__accent-glyph\s*\{[^}]*padding-inline:\s*0\.08em;[^}]*margin-inline:\s*-0\.08em;/s,
    );
    expect(styles).not.toContain("#b18839");
  });
});
