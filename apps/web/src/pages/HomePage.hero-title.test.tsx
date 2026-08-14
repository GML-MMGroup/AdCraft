import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HomePage } from "./HomePage";

const startNewProject = vi.fn();
const styles = readFileSync(resolve(process.cwd(), "src/pages/home.css"), "utf8");
const darkAccentPseudoStyles = styles.match(
  /:root \.home-product-hero__accent::after\s*\{[^}]*\}/,
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
    expect(lines.slice(0, 2).map((line) => line.textContent?.replace(/\u00a0/g, " "))).toEqual([
      "ONE SENTENCE",
      "BECOMES AN",
    ]);
    expect(lines[0]?.getAttribute("data-home-hero-queue-origin")).toBe("line-start");
    expect(lines[1]?.getAttribute("data-home-hero-queue-origin")).toBe("line-end");
    expect(
      Array.from(lines[0]?.querySelectorAll<HTMLElement>(".home-product-hero__title-character") ?? [])
        .map((character) => character.dataset.homeHeroCharacterOrder),
    ).toEqual(["10", "9", "8", "7", "6", "5", "4", "3", "2", "1", "0"]);
    expect(
      Array.from(lines[1]?.querySelectorAll<HTMLElement>(".home-product-hero__title-character") ?? [])
        .map((character) => character.dataset.homeHeroCharacterOrder),
    ).toEqual(["0", "1", "2", "3", "4", "5", "6", "7", "8"]);
    expect(lines[0]?.querySelectorAll(".home-product-hero__title-character--collision")).toHaveLength(0);
    expect(lines[1]?.querySelectorAll(".home-product-hero__title-character--collision")).toHaveLength(0);
    expect(lines[0]?.querySelectorAll(".home-product-hero__title-character--bump-target")).toHaveLength(0);
    expect(lines[1]?.querySelectorAll(".home-product-hero__title-character--bump-target")).toHaveLength(0);
    expect(lines[2]?.classList.contains("home-product-hero__accent")).toBe(true);
    expect(lines[2]?.getAttribute("data-accent-text")).toBe("Ad film.");
    expect(lines[2]?.getAttribute("data-home-hero-accent-reveal")).toBe("diagonal");
    expect(lines[2]?.getAttribute("data-home-typography-region")).toBe("heroAccent");
    expect(lines[2]?.querySelectorAll(".home-product-hero__character")).toHaveLength(0);
    expect(lines[2]?.textContent).toBe("Ad film.");
    expect(lines[2]?.querySelector("svg")).toBeNull();
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
      /\.home-page\s*\{[^}]*--home-font-display:\s*"Trebuchet MS"[^;]*;[^}]*--home-font-accent:\s*"Water Brush"[^;]*;[^}]*--home-font-ui:\s*Arial[^;]*;[^}]*font-family:\s*var\(--home-font-ui\);/s,
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
      /\[data-home-typography-region="heroAccent"\]\s*\{[^}]*font-family:\s*"Water Brush"[^}]*font-size:\s*80px;[^}]*font-weight:\s*400;[^}]*font-style:\s*normal;[^}]*line-height:\s*1\.25;[^}]*letter-spacing:\s*0\.100em;/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero__accent::after\s*\{[^}]*content:\s*attr\(data-accent-text\);[^}]*background-size:\s*240% 100%;[^}]*-webkit-background-clip:\s*text;[^}]*background-clip:\s*text;[^}]*-webkit-text-fill-color:\s*transparent;[^}]*pointer-events:\s*none;/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero__accent\s*\{[^}]*opacity:\s*1;[^}]*filter:\s*none;[^}]*will-change:\s*auto;/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero\.is-motion-enabled \.home-product-hero__accent::after\s*\{[^}]*clip-path:\s*polygon\(0 0, -8% 0, -24% 100%, 0 100%\);/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero\.is-motion-ready \.home-product-hero__accent::after\s*\{[^}]*home-hero-accent-diagonal-reveal[^}]*var\(--home-hero-accent-start-delay\)/s,
    );
    expect(styles).toMatch(
      /@keyframes home-hero-accent-diagonal-reveal\s*\{[\s\S]*?polygon\(0 0, -8% 0, -24% 100%, 0 100%\)[\s\S]*?polygon\(0 0, 118% 0, 102% 100%, 0 100%\)/,
    );
    expect(styles).not.toContain("home-hero-accent-writing");
    expect(styles).not.toContain("home-hero-accent-write");
    expect(styles).toMatch(
      /:root \.home-product-hero__accent\s*\{[^}]*color:\s*transparent;/s,
    );
    expect(styles).toMatch(
      /:root \.home-product-hero__accent::after\s*\{[^}]*#d7ae59[^}]*#ffe7a6[^}]*#bc8d36/s,
    );
    expect(styles).not.toContain("home-product-hero__accent-glyph");
    expect(styles).not.toContain("home-hero-character-wave");
    expect(styles).not.toContain("home-hero-gold-sweep");
    expect(styles).not.toMatch(/\.home-product-hero__accent::after\s*\{[^}]*text-shadow:/s);
    expect(styles).not.toMatch(/\.home-product-hero__accent::after\s*\{[^}]*filter:/s);
    expect(styles).not.toContain("Clash Display");
  });

  it("matches the approved wide desktop hero proportions", () => {
    render(<HomePage navigate={vi.fn()} />);

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
      /\.home-product-hero__create\s*\{[^}]*min-height:\s*44px;[^}]*gap:\s*8px;[^}]*padding:\s*0 18px 0 15px;/s,
    );
    const [createButton] = screen.getAllByRole("button", { name: "Create Your Project" });
    const createIcon = createButton.querySelector("svg.home-product-hero__create-icon");
    expect(createIcon?.getAttribute("viewBox")).toBe("0 0 256 256");
    expect(createIcon?.querySelector("path")?.getAttribute("d")).toBe(
      "M220,128a4,4,0,0,1-4,4H132v84a4,4,0,0,1-8,0V132H40a4,4,0,0,1,0-8h84V40a4,4,0,0,1,8,0v84h84A4,4,0,0,1,220,128Z",
    );
  });

  it("keeps the dark-theme gold override from resetting text clipping", () => {
    expect(darkAccentPseudoStyles).toContain("background-image:");
    expect(darkAccentPseudoStyles).not.toMatch(/\bbackground\s*:/);
  });

  it("keeps the Recent Projects card group free of an outer border", () => {
    expect(styles).toMatch(
      /\.recent-strip\s*\{[^}]*border:\s*0;[^}]*background:\s*rgba\(255, 255, 255, 0\.38\);/s,
    );
  });

  it("keeps the dark home CTA transparent until interaction", () => {
    expect(styles).toMatch(
      /:root \.home-product-hero__create\s*\{[^}]*border-color:\s*rgba\(255, 255, 255, 0\.075\);[^}]*background:\s*transparent;[^}]*box-shadow:\s*0 8px 22px rgba\(0, 13, 24, 0\.12\);[^}]*-webkit-backdrop-filter:\s*none;[^}]*backdrop-filter:\s*none;[^}]*will-change:\s*auto;[^}]*color:\s*rgba\(255, 255, 255, 0\.96\);/s,
    );
    expect(styles).toMatch(
      /:root \.home-product-hero__create:(?:hover|active)[^{]*\{[^}]*background:\s*rgba\(157, 175, 230, 0\.3\);[^}]*border-color:\s*rgba\(207, 217, 255, 0\.52\);/s,
    );
    expect(styles).toMatch(
      /:root \.home-product-hero__create:active\s*\{[^}]*background:\s*rgba\(157, 175, 230, 0\.3\);[^}]*border-color:\s*rgba\(207, 217, 255, 0\.52\);/s,
    );
  });
});
