import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HomePage } from "./HomePage";

const startNewProject = vi.fn();
const styles = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");
const mobileHeroTitleStyles = styles.match(
  /@media \(max-width: 620px\)[\s\S]*?\.home-product-hero__title\s*\{[^}]*\}/,
)?.[0] ?? "";

vi.mock("../AppContextValue", () => ({
  useApp: () => ({ startNewProject }),
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
  });

  it("uses a stronger, airier title lockup and layered gilded accent", () => {
    expect(styles).toMatch(
      /\.home-product-hero__title\s*\{[^}]*font-weight:\s*500;[^}]*line-height:\s*1\.2;[^}]*-webkit-text-stroke:\s*0\.18px currentColor;/s,
    );
    expect(mobileHeroTitleStyles).toMatch(/line-height:\s*1\.2;/);
    expect(styles).toMatch(
      /\.home-product-hero__title-line\s*\{[^}]*display:\s*block;/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero__accent\s*\{[^}]*linear-gradient\([^}]*#f8e7a1[^}]*#8f5a12[^}]*\)[^}]*background-clip:\s*text;[^}]*-webkit-text-stroke:\s*0\.16px rgba\(108, 66, 10, 0\.32\);/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero__accent\s*\{[^}]*width:\s*fit-content;[^}]*padding-inline:\s*0\.1em 0\.12em;[^}]*margin-inline:\s*-0\.1em -0\.12em;/s,
    );
  });
});
