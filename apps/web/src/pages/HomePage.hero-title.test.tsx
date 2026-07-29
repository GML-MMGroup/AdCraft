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
const darkAccentPseudoStyles = styles.match(
  /html\[data-theme="dark"\] \.home-product-hero__accent::after\s*\{[^}]*\}/,
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
      "ONE SENTENCE",
      "BECOMES AN",
      "Ad film.",
    ]);
    expect(lines[2]?.classList.contains("home-product-hero__accent")).toBe(true);
    expect(lines[2]?.getAttribute("data-accent-text")).toBe("Ad film.");
    expect(lines[2]?.querySelectorAll(".home-product-hero__glyph")).toHaveLength(8);
    expect(lines[2]?.querySelectorAll(".home-product-hero__accent-glyph")).toHaveLength(0);
  });

  it("uses the approved Space Grotesk, Clash Display, and Inter homepage system", () => {
    expect(styles).toMatch(
      /@font-face\s*\{[^}]*font-family:\s*"Space Grotesk";[^}]*space-grotesk-latin-variable\.woff2/s,
    );
    expect(styles).toMatch(
      /@font-face\s*\{[^}]*font-family:\s*"Clash Display";[^}]*clash-display-bold\.woff2/s,
    );
    expect(styles).toMatch(
      /@font-face\s*\{[^}]*font-family:\s*"Inter";[^}]*inter-latin-variable\.woff2/s,
    );
    expect(styles).toMatch(
      /\.home-page\s*\{[^}]*--home-font-display:\s*"Space Grotesk"[^;]*;[^}]*--home-font-accent:\s*"Clash Display"[^;]*;[^}]*--home-font-ui:\s*"Inter"[^;]*;[^}]*font-family:\s*var\(--home-font-ui\);/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero__title\s*\{[^}]*font-family:\s*var\(--home-font-display\);[^}]*font-size:\s*62px;[^}]*font-weight:\s*700;[^}]*line-height:\s*1\.02;[^}]*letter-spacing:\s*0;/s,
    );
    expect(mobileHeroTitleStyles).toMatch(
      /font-size:\s*40px;[^}]*line-height:\s*1\.02;/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero__title-line\s*\{[^}]*display:\s*block;/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero__accent\s*\{[^}]*font-family:\s*var\(--home-font-accent\);[^}]*font-size:\s*150px;[^}]*font-weight:\s*700;[^}]*line-height:\s*0\.9;[^}]*transform:\s*skewX\(-8deg\) scaleX\(0\.76\) scaleY\(1\.16\);/s,
    );
    expect(styles).toMatch(
      /\.section-title h2\s*\{[^}]*font-family:\s*var\(--home-font-display\);[^}]*font-weight:\s*700;[^}]*text-transform:\s*uppercase;/s,
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

  it("matches the approved wide desktop hero proportions", () => {
    expect(styles).toMatch(
      /\.home-product-hero\s*\{[^}]*--home-product-hero-height:\s*607px;[^}]*--home-product-media-height:\s*458px;[^}]*width:\s*min\(1230px, calc\(100vw - 180px\)\);/s,
    );
    expect(styles).toMatch(
      /\.home-page > \.content-wrap\s*\{[^}]*width:\s*min\(1230px, calc\(100vw - 180px\)\);/s,
    );
    expect(styles).toMatch(
      /\.home-product-film\s*\{[^}]*margin-bottom:\s*22px;/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero__create\s*\{[^}]*min-height:\s*56px;[^}]*font-size:\s*16px;/s,
    );
  });

  it("keeps the dark-theme gold override from resetting text clipping", () => {
    expect(darkAccentPseudoStyles).toContain("background-image:");
    expect(darkAccentPseudoStyles).not.toMatch(/\bbackground\s*:/);
  });
});
