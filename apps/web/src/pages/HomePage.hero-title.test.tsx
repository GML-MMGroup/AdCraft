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
    expect(lines[2]?.getAttribute("data-accent-text")).toBe("Ad film.");
    expect(lines[2]?.querySelectorAll(".home-product-hero__glyph")).toHaveLength(8);
    expect(lines[2]?.querySelectorAll(".home-product-hero__accent-glyph")).toHaveLength(0);
  });

  it("uses a lower, more open title lockup and a phrase-level gold sweep clipped to text", () => {
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
      /\.home-product-hero__accent\s*\{[^}]*position:\s*relative;[^}]*width:\s*fit-content;[^}]*color:\s*#8f6722;[^}]*font-style:\s*italic;[^}]*font-weight:\s*400;/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero__accent::after\s*\{[^}]*content:\s*attr\(data-accent-text\);[^}]*background-size:\s*240% 100%;[^}]*-webkit-background-clip:\s*text;[^}]*background-clip:\s*text;[^}]*-webkit-text-fill-color:\s*transparent;[^}]*pointer-events:\s*none;/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero\.is-motion-ready \.home-product-hero__accent::after\s*\{[^}]*home-hero-accent-reveal[^}]*home-hero-gold-sweep/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero\.is-motion-ready \.home-product-hero__accent \.home-product-hero__character\s*\{[^}]*home-hero-character-wave[^}]*home-hero-accent-source-hide/s,
    );
    expect(styles).toMatch(
      /@keyframes home-hero-gold-sweep[\s\S]*?background-position:\s*0% 50%;/,
    );
    expect(styles).toMatch(
      /html\[data-theme="dark"\] \.home-product-hero__accent\s*\{[^}]*color:\s*#d7ae59;/s,
    );
    expect(styles).toMatch(
      /html\[data-theme="dark"\] \.home-product-hero__accent::after\s*\{[^}]*#d7ae59[^}]*#ffe7a6[^}]*#bc8d36/s,
    );
    expect(styles).toMatch(
      /@media \(prefers-reduced-motion:\s*reduce\)[\s\S]*?\.home-product-hero__accent::after[\s\S]*?animation:\s*none !important;[\s\S]*?opacity:\s*1 !important;/,
    );
    expect(styles).not.toContain("home-product-hero__accent-glyph");
    expect(styles).not.toMatch(/\.home-product-hero__accent::after\s*\{[^}]*text-shadow:/s);
    expect(styles).not.toMatch(/\.home-product-hero__accent::after\s*\{[^}]*filter:/s);
  });
});
