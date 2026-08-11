import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HomePage } from "./HomePage";

const startNewProject = vi.fn();
const styles = readFileSync(resolve(process.cwd(), "src/pages/home.css"), "utf8");
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
    expect(lines[2]?.getAttribute("data-home-typography-region")).toBe("heroAccent");
    expect(lines[2]?.querySelectorAll(".home-product-hero__character")).toHaveLength(0);
  });

  it("plays the bundled product film when no environment override is configured", () => {
    const view = render(<HomePage navigate={vi.fn()} />);

    const media = view.container.querySelector<HTMLElement>(".home-product-film");
    expect(media.querySelector("video")?.getAttribute("src")).toBe(
      "/assets/home-product-film.mp4",
    );
  });

  it("uses the exported typography system while retaining the accent treatment", () => {
    expect(styles).toMatch(
      /\.home-page\s*\{[^}]*--home-font-display:\s*"Trebuchet MS"[^;]*;[^}]*--home-font-accent:\s*Georgia[^;]*;[^}]*--home-font-ui:\s*Arial[^;]*;[^}]*font-family:\s*var\(--home-font-ui\);/s,
    );
    expect(styles).toMatch(
      /\[data-home-typography-region="heroMain"\]\s*\{[^}]*font-family:\s*"Trebuchet MS"[^}]*font-size:\s*60px;[^}]*font-weight:\s*400;[^}]*font-style:\s*italic;[^}]*line-height:\s*1\.1;[^}]*letter-spacing:\s*0\.016em;/s,
    );
    expect(styles).toMatch(
      /@media \(max-width: 620px\)\s*\{\s*\.home-page \.home-product-hero__title\[data-home-typography-region="heroMain"\]\s*\{[^}]*font-size:\s*40px;/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero__title-line\s*\{[^}]*display:\s*block;/s,
    );
    expect(styles).toMatch(
      /\[data-home-typography-region="heroAccent"\]\s*\{[^}]*font-family:\s*Georgia[^}]*font-size:\s*70px;[^}]*font-weight:\s*400;[^}]*font-style:\s*italic;[^}]*line-height:\s*1\.2;[^}]*letter-spacing:\s*0\.046em;/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero__accent::after\s*\{[^}]*content:\s*attr\(data-accent-text\);[^}]*background-size:\s*240% 100%;[^}]*-webkit-background-clip:\s*text;[^}]*background-clip:\s*text;[^}]*-webkit-text-fill-color:\s*transparent;[^}]*pointer-events:\s*none;/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero__accent\s*\{[^}]*opacity:\s*1;[^}]*filter:\s*none;[^}]*will-change:\s*auto;/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero\.is-motion-ready \.home-product-hero__accent\s*\{[^}]*animation:\s*none;/s,
    );
    expect(styles).toMatch(
      /html\[data-theme="dark"\] \.home-product-hero__accent\s*\{[^}]*color:\s*transparent;/s,
    );
    expect(styles).toMatch(
      /html\[data-theme="dark"\] \.home-product-hero__accent::after\s*\{[^}]*#d7ae59[^}]*#ffe7a6[^}]*#bc8d36/s,
    );
    expect(styles).not.toContain("home-product-hero__accent-glyph");
    expect(styles).not.toContain("home-hero-character-wave");
    expect(styles).not.toContain("home-hero-gold-sweep");
    expect(styles).not.toMatch(/\.home-product-hero__accent::after\s*\{[^}]*text-shadow:/s);
    expect(styles).not.toMatch(/\.home-product-hero__accent::after\s*\{[^}]*filter:/s);
    expect(styles).not.toContain("Clash Display");
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
      /\.home-product-hero__create\s*\{[^}]*min-height:\s*56px;/s,
    );
  });

  it("keeps the dark-theme gold override from resetting text clipping", () => {
    expect(darkAccentPseudoStyles).toContain("background-image:");
    expect(darkAccentPseudoStyles).not.toMatch(/\bbackground\s*:/);
  });
});
